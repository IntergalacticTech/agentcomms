"""Inboxes Lambda handler."""

import random
import string

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, query, query_gsi, update_item
from shared.models import inbox_gsi1, inbox_gsi2, inbox_keys, now_iso
from shared.quotas import check_quota, decrement_usage, increment_usage
from shared.pagination import (
    decode_page_token,
    get_pagination_params,
    paginated_response,
)
from shared.response import bad_request, created, no_content, not_found, success
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

DEFAULT_DOMAIN = "victorymail.dev"

INBOX_FIELDS = [
    "id", "org_id", "pod_id", "email", "display_name",
    "status", "message_count", "unread_count", "settings", "forwarding",
    "created_at", "updated_at",
]


def _generate_email() -> str:
    """Generate a random email address."""
    chars = string.ascii_lowercase + string.digits
    local = "".join(random.choices(chars, k=12))
    return f"{local}@{DEFAULT_DOMAIN}"


def _filter_inbox(item: dict) -> dict:
    return {k: item[k] for k in INBOX_FIELDS if k in item}


def _list_inboxes(event):
    """GET /inboxes: list inboxes for org."""
    org_id = get_org_id(event)
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)

    params = event.get("queryStringParameters") or {}
    pod_id = params.get("pod_id")

    if pod_id:
        items, last_key = query_gsi(
            "GSI1",
            f"POD#{pod_id}#INBOXES",
            limit=limit,
            ascending=ascending,
            exclusive_start_key=start_key,
        )
    else:
        items, last_key = query(
            pk=f"ORG#{org_id}",
            sk_prefix="INBOX#",
            limit=limit,
            ascending=ascending,
            exclusive_start_key=start_key,
        )

    # Filter out deleted
    active_items = [_filter_inbox(i) for i in items if i.get("status") != "deleted"]

    return success(paginated_response(active_items, last_key))


def _get_inbox(event):
    """GET /inboxes/{id}: get a single inbox."""
    org_id = get_org_id(event)
    inbox_id = event["pathParameters"]["id"]
    keys = inbox_keys(org_id, inbox_id)
    item = get_item(keys["PK"], keys["SK"])

    if not item or item.get("status") == "deleted":
        return not_found("Inbox")

    return success(_filter_inbox(item))


def _create_inbox(event):
    """POST /inboxes: create a new inbox."""
    org_id = get_org_id(event)

    quota_error = check_quota(org_id, "inboxes")
    if quota_error:
        return quota_error

    body = parse_body(event)

    pod_id = body.get("pod_id", "default")
    email = body.get("email") or _generate_email()
    display_name = body.get("display_name", "")

    inbox_id = generate_ulid()
    now = now_iso()

    inbox_item = {
        **inbox_keys(org_id, inbox_id),
        **inbox_gsi1(pod_id, inbox_id),
        **inbox_gsi2(email, inbox_id),
        "id": inbox_id,
        "org_id": org_id,
        "pod_id": pod_id,
        "email": email,
        "display_name": display_name,
        "status": "active",
        "settings": body.get("settings", {}),
        "forwarding": body.get("forwarding", {}),
        "created_at": now,
        "updated_at": now,
    }
    put_item(inbox_item)
    increment_usage(org_id, "inboxes")

    return created(_filter_inbox(inbox_item))


def _update_inbox(event):
    """PATCH /inboxes/{id}: update inbox fields."""
    org_id = get_org_id(event)
    inbox_id = event["pathParameters"]["id"]
    body = parse_body(event)

    keys = inbox_keys(org_id, inbox_id)
    item = get_item(keys["PK"], keys["SK"])

    if not item or item.get("status") == "deleted":
        return not_found("Inbox")

    updates = {}
    for field in ("display_name", "settings", "forwarding"):
        if field in body:
            updates[field] = body[field]

    if not updates:
        return bad_request("No valid fields to update")

    updates["updated_at"] = now_iso()
    updated = update_item(keys["PK"], keys["SK"], updates)

    return success(_filter_inbox(updated))


def _delete_inbox(event):
    """DELETE /inboxes/{id}: soft delete."""
    org_id = get_org_id(event)
    inbox_id = event["pathParameters"]["id"]

    keys = inbox_keys(org_id, inbox_id)
    item = get_item(keys["PK"], keys["SK"])

    if not item or item.get("status") == "deleted":
        return not_found("Inbox")

    now = now_iso()
    update_item(keys["PK"], keys["SK"], {
        "status": "deleted",
        "deleted_at": now,
        "updated_at": now,
    })
    decrement_usage(org_id, "inboxes")

    return no_content()


def handler(event, context):
    """Route inbox requests."""
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if method == "GET" and path_params.get("id"):
        return _get_inbox(event)
    elif method == "GET":
        return _list_inboxes(event)
    elif method == "POST":
        return _create_inbox(event)
    elif method == "PATCH" and path_params.get("id"):
        return _update_inbox(event)
    elif method == "DELETE" and path_params.get("id"):
        return _delete_inbox(event)
    else:
        return bad_request("Unknown route")
