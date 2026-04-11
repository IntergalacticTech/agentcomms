"""Signup and verification Lambda handler."""

import hashlib
import os
import random
import secrets
import string

from shared.auth import get_org_id
from shared.dynamo import put_item
from shared.models import api_key_gsi1, api_key_keys, now_iso, org_keys
from shared.response import bad_request, created, not_found, success
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

# In-memory OTP store (module-level)
_otp_store: dict[str, str] = {}

# Base62 alphabet
_BASE62 = string.ascii_letters + string.digits

FREE_TIER_QUOTAS = {
    "max_inboxes": 5,
    "max_messages_per_day": 1000,
    "max_api_keys": 5,
    "max_pods": 3,
    "max_domains": 1,
    "max_webhooks": 5,
}


def _generate_api_key() -> str:
    """Generate an API key: am_live_ + base62 encoded 32 random bytes."""
    raw = secrets.token_bytes(32)
    # Base62 encode
    num = int.from_bytes(raw, "big")
    encoded = []
    while num > 0:
        num, remainder = divmod(num, 62)
        encoded.append(_BASE62[remainder])
    encoded_str = "".join(reversed(encoded))
    return f"am_live_{encoded_str}"


def _handle_signup(event):
    """Handle POST /v1/agent/signup."""
    body = parse_body(event)
    err = require_fields(body, ["email"])
    if err:
        return bad_request(err)

    email = body["email"]

    # Generate 6-digit OTP
    code = f"{random.randint(0, 999999):06d}"
    _otp_store[email] = code

    return created({
        "message": "Verification code sent",
        "email": email,
    })


def _handle_verify(event):
    """Handle POST /v1/agent/verify."""
    body = parse_body(event)
    err = require_fields(body, ["email", "code"])
    if err:
        return bad_request(err)

    email = body["email"]
    code = body["code"]

    # Validate OTP
    stored_code = _otp_store.get(email)
    if stored_code is None or stored_code != code:
        return {"statusCode": 401, "headers": {"Content-Type": "application/json"},
                "body": '{"error": {"code": "UNAUTHORIZED", "message": "Invalid verification code"}}'}

    # Clean up OTP
    del _otp_store[email]

    # Create organization
    org_id = generate_ulid()
    now = now_iso()

    org_item = {
        **org_keys(org_id),
        "id": org_id,
        "name": email.split("@")[0],
        "email": email,
        "tier": "free",
        "status": "active",
        "settings": {},
        "quotas": FREE_TIER_QUOTAS,
        "usage": {},
        "created_at": now,
        "updated_at": now,
    }
    put_item(org_item)

    # Generate API key
    api_key_plaintext = _generate_api_key()
    key_hash = hashlib.sha256(api_key_plaintext.encode()).hexdigest()
    key_id = generate_ulid()

    key_item = {
        **api_key_keys(org_id, key_id),
        **api_key_gsi1(key_hash, key_id),
        "id": key_id,
        "key_id": key_id,
        "org_id": org_id,
        "name": "Default API Key",
        "key_hash": key_hash,
        "key_prefix": api_key_plaintext[:12],
        "scope": "org",
        "scope_resource_id": org_id,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    put_item(key_item)

    return created({
        "organization": {
            "id": org_id,
            "name": org_item["name"],
            "email": email,
            "tier": "free",
            "status": "active",
        },
        "api_key": {
            "id": key_id,
            "key": api_key_plaintext,
            "key_prefix": api_key_plaintext[:12],
            "scope": "org",
        },
    })


def handler(event, context):
    """Route signup requests."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")

    if method == "POST" and path.endswith("/signup"):
        return _handle_signup(event)
    elif method == "POST" and path.endswith("/verify"):
        return _handle_verify(event)
    else:
        return bad_request("Unknown route")
