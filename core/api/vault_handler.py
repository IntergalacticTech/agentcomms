# core/api/vault_handler.py
"""Vault API handler — KMS-wrapped secrets and TOTP generation.

Routes (all org-scoped):
  POST   /v1/vault                  — create a vault entry
  GET    /v1/vault                  — list metadata (no ciphertext)
  GET    /v1/vault/{id}             — metadata + decrypted value (not for totp seed)
  GET    /v1/vault/{id}/totp        — current 6-digit TOTP code
  DELETE /v1/vault/{id}             — delete

All routes require ORG scope; agent-scoped keys receive 403.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timezone

from core.api._common import (
    Caller, err, get_repo, no_content, ok, parse_body, require_org_scope,
)
from core.data.models import VaultItem, VaultType
from core.vault import kms as vault_kms
from core.vault.totp import generate_totp_code, totp_valid_until

_VAULT_TYPES = {v.value for v in VaultType}


def _new_vault_id() -> str:
    import secrets
    import time
    ts = int(time.time() * 1000)
    rnd = secrets.token_hex(6)
    return f"vlt_{ts}_{rnd}"


def _meta(item: VaultItem) -> dict:
    """Return only safe metadata — no ciphertext, no plaintext."""
    return {
        "vault_id": item.vault_id,
        "org_id": item.org_id,
        "type": item.type.value,
        "label": item.label,
        "kms_key_id": item.kms_key_id,
        "tags": item.tags,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Route implementations
# ---------------------------------------------------------------------------

def _create(caller: Caller, body: dict, repo) -> dict:
    vault_type_str = body.get("type", "")
    if vault_type_str not in _VAULT_TYPES:
        return err(f"'type' must be one of: {sorted(_VAULT_TYPES)}")

    label = body.get("label", "").strip()
    if not label:
        return err("'label' is required")

    vault_type = VaultType(vault_type_str)

    # For TOTP items the caller passes 'seed'; for all others 'value'
    if vault_type == VaultType.TOTP:
        plaintext_str = body.get("seed", "")
        if not plaintext_str:
            return err("'seed' is required for type='totp'")
        # Validate base32
        try:
            _normalised = plaintext_str.strip().replace(" ", "").upper()
            padding = (8 - len(_normalised) % 8) % 8
            base64.b32decode(_normalised + "=" * padding, casefold=True)
        except Exception:
            return err("'seed' must be a valid base32-encoded string")
    else:
        plaintext_str = body.get("value", "")
        if not plaintext_str:
            return err("'value' is required")

    tags = body.get("tags") or {}
    if not isinstance(tags, dict):
        return err("'tags' must be a JSON object")

    kms_key_id_override = os.environ.get("AGENTCOMMS_VAULT_KMS_KEY_ID")
    try:
        ciphertext, key_id_used = vault_kms.encrypt(
            plaintext_str.encode("utf-8"), kms_key_id=kms_key_id_override
        )
    except Exception as exc:
        return err(f"KMS encryption failed: {exc}", status=500)

    vault_id = _new_vault_id()
    now = datetime.now(timezone.utc)
    item = VaultItem(
        vault_id=vault_id,
        org_id=caller.org_id,
        type=vault_type,
        label=label,
        encrypted_blob=ciphertext,
        kms_key_id=key_id_used,
        tags=tags,
        created_at=now,
        updated_at=now,
    )
    repo.put_vault(item)
    return ok(_meta(item), status=201)


def _list(caller: Caller, event: dict, repo) -> dict:
    qs = event.get("queryStringParameters") or {}
    type_filter_str = qs.get("type")
    tag_filter = qs.get("tag")  # format "key:value"
    label_starts = qs.get("label_starts_with")

    type_filter = VaultType(type_filter_str) if type_filter_str in _VAULT_TYPES else None

    items = repo.list_vault(
        org_id=caller.org_id,
        type=type_filter,
        tag=tag_filter,
    )

    if label_starts:
        items = [i for i in items if i.label.lower().startswith(label_starts.lower())]

    return ok({"items": [_meta(i) for i in items]})


def _get(caller: Caller, vault_id: str, repo) -> dict:
    item = repo.get_vault(org_id=caller.org_id, vault_id=vault_id)
    if not item:
        return err("Vault item not found", status=404)

    result = _meta(item)

    # For TOTP items: do NOT expose the seed; return metadata only
    if item.type != VaultType.TOTP:
        try:
            plaintext = vault_kms.decrypt(item.encrypted_blob)
            result["value"] = plaintext.decode("utf-8")
        except Exception as exc:
            return err(f"KMS decryption failed: {exc}", status=500)

    return ok(result)


def _get_totp(caller: Caller, vault_id: str, repo) -> dict:
    item = repo.get_vault(org_id=caller.org_id, vault_id=vault_id)
    if not item:
        return err("Vault item not found", status=404)
    if item.type != VaultType.TOTP:
        return err("Vault item is not of type 'totp'", status=400)

    try:
        seed = vault_kms.decrypt(item.encrypted_blob).decode("utf-8")
        code = generate_totp_code(seed)
        valid_until = totp_valid_until()
    except Exception as exc:
        return err(f"Could not generate TOTP code: {exc}", status=500)

    return ok({"code": code, "valid_until": valid_until})


def _delete(caller: Caller, vault_id: str, repo) -> dict:
    existing = repo.get_vault(org_id=caller.org_id, vault_id=vault_id)
    if not existing:
        return err("Vault item not found", status=404)
    repo.delete_vault(org_id=caller.org_id, vault_id=vault_id)
    return no_content()


# ---------------------------------------------------------------------------
# Lambda entry-point
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    caller = Caller.from_event(event)

    # All vault routes require org scope
    if denied := require_org_scope(caller):
        return denied

    method = event.get("httpMethod", "")
    path = event.get("path", "")
    params = event.get("pathParameters") or {}
    vault_id = params.get("vault_id") or params.get("id", "")

    repo = get_repo()

    # GET /v1/vault/{id}/totp
    if method == "GET" and vault_id and path.endswith("/totp"):
        return _get_totp(caller, vault_id, repo)

    # GET /v1/vault/{id}
    if method == "GET" and vault_id:
        return _get(caller, vault_id, repo)

    # GET /v1/vault
    if method == "GET":
        return _list(caller, event, repo)

    # POST /v1/vault
    if method == "POST":
        body = parse_body(event)
        return _create(caller, body, repo)

    # DELETE /v1/vault/{id}
    if method == "DELETE" and vault_id:
        return _delete(caller, vault_id, repo)

    return err("Not found", status=404)
