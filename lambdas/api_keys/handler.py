"""API Keys Lambda handler."""

import hashlib
import secrets
import string

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, query, update_item
from shared.models import api_key_gsi1, api_key_keys, now_iso
from shared.pagination import get_pagination_params, paginated_response
from shared.response import bad_request, created, no_content, not_found, success
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

_BASE62 = string.ascii_letters + string.digits

API_KEY_LIST_FIELDS = [
    "id", "name", "key_prefix", "scope", "scope_resource_id",
    "status", "created_at", "updated_at",
]


def _generate_api_key() -> str:
    """Generate an API key: am_live_ + base62 encoded 32 random bytes."""
    raw = secrets.token_bytes(32)
    num = int.from_bytes(raw, "big")
    encoded = []
    while num > 0:
        num, remainder = divmod(num, 62)
        encoded.append(_BASE62[remainder])
    return f"am_live_{''.join(reversed(encoded))}"


def _filter_key(item: dict) -> dict:
    """Filter key item to only return safe metadata fields."""
    return {k: item[k] for k in API_KEY_LIST_FIELDS if k in item}


def _list_keys(event):
    """GET /api-keys: list keys for org."""
    org_id = get_org_id(event)
    limit, page_token, ascending = get_pagination_params(event)

    from shared.pagination import decode_page_token
    start_key = decode_page_token(page_token)

    items, last_key = query(
        pk=f"ORG#{org_id}",
        sk_prefix="APIKEY#",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )

    # Filter active only
    active_items = [_filter_key(i) for i in items if i.get("status") == "active"]

    return success(paginated_response(active_items, last_key))


def _create_key(event):
    """POST /api-keys: create a new API key."""
    org_id = get_org_id(event)
    body = parse_body(event)
    err = require_fields(body, ["name", "scope"])
    if err:
        return bad_request(err)

    scope = body["scope"]
    if scope in ("pod", "inbox"):
        err = require_fields(body, ["scope_resource_id"])
        if err:
            return bad_request(err)

    api_key_plaintext = _generate_api_key()
    key_hash = hashlib.sha256(api_key_plaintext.encode()).hexdigest()
    key_id = generate_ulid()
    now = now_iso()

    scope_resource_id = body.get("scope_resource_id", org_id)

    key_item = {
        **api_key_keys(org_id, key_id),
        **api_key_gsi1(key_hash, key_id),
        "id": key_id,
        "key_id": key_id,
        "org_id": org_id,
        "name": body["name"],
        "key_hash": key_hash,
        "key_prefix": api_key_plaintext[:12],
        "scope": scope,
        "scope_resource_id": scope_resource_id,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    put_item(key_item)

    return created({
        "id": key_id,
        "name": body["name"],
        "key": api_key_plaintext,
        "key_prefix": api_key_plaintext[:12],
        "scope": scope,
        "scope_resource_id": scope_resource_id,
        "status": "active",
        "created_at": now,
    })


def _delete_key(event):
    """DELETE /api-keys/{id}: revoke a key."""
    org_id = get_org_id(event)
    key_id = event.get("pathParameters", {}).get("id", "")

    keys = api_key_keys(org_id, key_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("API Key")

    update_item(
        keys["PK"], keys["SK"],
        {"status": "revoked", "updated_at": now_iso()},
    )

    return no_content()


def handler(event, context):
    """Route API key requests."""
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if method == "GET":
        return _list_keys(event)
    elif method == "POST":
        return _create_key(event)
    elif method == "DELETE" and path_params.get("id"):
        return _delete_key(event)
    else:
        return bad_request("Unknown route")
