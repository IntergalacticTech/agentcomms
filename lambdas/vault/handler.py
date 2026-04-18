"""Vault Lambda handler — encrypted secret storage for agents.

Secrets are encrypted under a per-org AWS KMS CMK that is created lazily on
the first vault write. Ciphertext lives in S3; DynamoDB holds only metadata
(label, created_at, last_accessed, TOTP flag). TOTP codes are computed
server-side from the stored seed so the seed itself never leaves the vault.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time

import boto3
from botocore.exceptions import ClientError

from shared.auth import get_org_id
from shared.dynamo import delete_item, get_item, put_item, query
from shared.models import now_iso, org_keys, vault_gsi1, vault_keys
from shared.pagination import (
    decode_page_token,
    get_pagination_params,
    paginated_response,
)
from shared.response import bad_request, created, no_content, not_found, success
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

VAULT_BUCKET = os.environ.get("VAULT_BUCKET", "")

VAULT_FIELDS = [
    "id", "label", "is_totp", "description", "metadata",
    "created_at", "last_accessed_at", "updated_at",
]

_kms = None
_s3 = None


def _get_kms():
    global _kms
    if _kms is None:
        _kms = boto3.client("kms")
    return _kms


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _filter_secret(item: dict) -> dict:
    return {k: item[k] for k in VAULT_FIELDS if k in item}


def _ensure_org_cmk(org_id: str) -> str:
    """Create a per-org KMS CMK on first use and cache the key ARN on the org
    record. Returns the key ARN."""
    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        raise ValueError(f"Organization {org_id} not found")

    existing = org.get("vault_kms_key_arn")
    if existing:
        return existing

    kms = _get_kms()
    alias_name = f"alias/freemail-vault-{org_id}"
    resp = kms.create_key(
        Description=f"FreeMail vault CMK for org {org_id}",
        KeyUsage="ENCRYPT_DECRYPT",
        KeySpec="SYMMETRIC_DEFAULT",
        Origin="AWS_KMS",
        Tags=[
            {"TagKey": "freemail:org_id", "TagValue": org_id},
            {"TagKey": "freemail:purpose", "TagValue": "vault"},
        ],
    )
    key_arn = resp["KeyMetadata"]["Arn"]
    key_id = resp["KeyMetadata"]["KeyId"]

    try:
        kms.create_alias(AliasName=alias_name, TargetKeyId=key_id)
    except ClientError:
        logger.exception("failed to create alias %s; continuing with raw ARN", alias_name)

    from shared.dynamo import update_item as _update
    _update(keys["PK"], keys["SK"], {"vault_kms_key_arn": key_arn, "updated_at": now_iso()})
    return key_arn


def _encrypt_secret(key_arn: str, plaintext: bytes) -> bytes:
    """Encrypt a secret blob with KMS and return the raw CiphertextBlob."""
    resp = _get_kms().encrypt(KeyId=key_arn, Plaintext=plaintext)
    return resp["CiphertextBlob"]


def _decrypt_secret(ciphertext: bytes) -> bytes:
    resp = _get_kms().decrypt(CiphertextBlob=ciphertext)
    return resp["Plaintext"]


def _s3_key(org_id: str, secret_id: str) -> str:
    return f"{org_id}/{secret_id}.bin"


def _store_ciphertext(org_id: str, secret_id: str, ciphertext: bytes) -> None:
    _get_s3().put_object(
        Bucket=VAULT_BUCKET,
        Key=_s3_key(org_id, secret_id),
        Body=ciphertext,
        ContentType="application/octet-stream",
        ServerSideEncryption="AES256",
    )


def _fetch_ciphertext(org_id: str, secret_id: str) -> bytes:
    resp = _get_s3().get_object(Bucket=VAULT_BUCKET, Key=_s3_key(org_id, secret_id))
    return resp["Body"].read()


def _delete_ciphertext(org_id: str, secret_id: str) -> None:
    try:
        _get_s3().delete_object(Bucket=VAULT_BUCKET, Key=_s3_key(org_id, secret_id))
    except ClientError:
        logger.exception("failed to delete vault ciphertext")


def _totp_code(secret_b32: str, step: int = 30, digits: int = 6) -> str:
    """Compute an RFC 6238 TOTP code from a base32-encoded shared secret."""
    key = base64.b32decode(secret_b32.strip().replace(" ", "").upper(), casefold=True)
    counter = int(time.time()) // step
    msg = struct.pack(">Q", counter)
    mac = hmac.new(key, msg, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code_int = (
        ((mac[offset] & 0x7F) << 24)
        | ((mac[offset + 1] & 0xFF) << 16)
        | ((mac[offset + 2] & 0xFF) << 8)
        | (mac[offset + 3] & 0xFF)
    )
    return str(code_int % (10 ** digits)).zfill(digits)


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

def _list_secrets(org_id: str, event: dict) -> dict:
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)
    items, last_key = query(
        pk=f"ORG#{org_id}",
        sk_prefix="VAULT#",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )
    filtered = [_filter_secret(i) for i in items]
    return success(paginated_response(filtered, last_key))


def _get_secret(org_id: str, secret_id: str, include_value: bool = False) -> dict:
    keys = vault_keys(org_id, secret_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Secret")

    # Touch last_accessed_at
    from shared.dynamo import update_item as _update
    _update(keys["PK"], keys["SK"], {"last_accessed_at": now_iso()})

    result = _filter_secret(item)
    if include_value:
        try:
            ciphertext = _fetch_ciphertext(org_id, secret_id)
            plaintext = _decrypt_secret(ciphertext)
            result["value"] = plaintext.decode("utf-8")
        except Exception:
            logger.exception("failed to decrypt secret %s", secret_id)
            return bad_request("Secret ciphertext could not be decrypted")
    return success(result)


def _create_secret(org_id: str, body: dict) -> dict:
    err = require_fields(body, ["label", "value"])
    if err:
        return bad_request(err)
    label = body["label"]
    value = body["value"]
    is_totp = bool(body.get("is_totp", False))
    description = body.get("description", "")
    metadata = body.get("metadata", {}) or {}

    if is_totp:
        # Validate that the base32 seed is parseable
        try:
            base64.b32decode(value.strip().replace(" ", "").upper(), casefold=True)
        except Exception:
            return bad_request("is_totp=true requires a base32-encoded seed")

    try:
        key_arn = _ensure_org_cmk(org_id)
    except Exception as e:
        logger.exception("failed to ensure org CMK")
        return bad_request(f"Could not initialize vault KMS key: {e}")

    secret_id = generate_ulid()
    ciphertext = _encrypt_secret(key_arn, value.encode("utf-8"))
    _store_ciphertext(org_id, secret_id, ciphertext)

    now = now_iso()
    item = {
        **vault_keys(org_id, secret_id),
        **vault_gsi1(org_id, label, secret_id),
        "entity_type": "Secret",
        "id": secret_id,
        "org_id": org_id,
        "label": label,
        "is_totp": is_totp,
        "description": description,
        "metadata": metadata,
        "created_at": now,
        "last_accessed_at": None,
        "updated_at": now,
    }
    put_item(item)
    return created(_filter_secret(item))


def _delete_secret(org_id: str, secret_id: str) -> dict:
    keys = vault_keys(org_id, secret_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Secret")
    _delete_ciphertext(org_id, secret_id)
    delete_item(keys["PK"], keys["SK"])
    return no_content()


def _get_totp(org_id: str, secret_id: str) -> dict:
    keys = vault_keys(org_id, secret_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Secret")
    if not item.get("is_totp"):
        return bad_request("This secret is not a TOTP seed")

    try:
        ciphertext = _fetch_ciphertext(org_id, secret_id)
        seed = _decrypt_secret(ciphertext).decode("utf-8")
        code = _totp_code(seed)
    except Exception as e:
        logger.exception("failed to compute TOTP code")
        return bad_request(f"Could not compute TOTP code: {e}")

    from shared.dynamo import update_item as _update
    _update(keys["PK"], keys["SK"], {"last_accessed_at": now_iso()})
    return success({"id": secret_id, "code": code, "period_seconds": 30})


def handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    params = event.get("pathParameters") or {}
    secret_id = params.get("id", "")
    org_id = get_org_id(event)
    body = parse_body(event) if method in ("POST", "PATCH") else {}

    if path.endswith("/totp") and method == "GET":
        return _get_totp(org_id, secret_id)

    if method == "GET":
        if secret_id:
            qs = event.get("queryStringParameters") or {}
            include_value = qs.get("reveal") == "true"
            return _get_secret(org_id, secret_id, include_value=include_value)
        return _list_secrets(org_id, event)

    if method == "POST":
        return _create_secret(org_id, body)

    if method == "DELETE" and secret_id:
        return _delete_secret(org_id, secret_id)

    return bad_request("Unknown route")
