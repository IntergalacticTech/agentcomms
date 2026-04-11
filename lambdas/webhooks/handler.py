"""Webhooks Lambda handler."""

import secrets

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, delete_item, query_gsi
from shared.models import webhook_keys, webhook_gsi1, now_iso
from shared.pagination import get_pagination_params, decode_page_token, paginated_response
from shared.response import success, created, bad_request, not_found, no_content
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

VALID_EVENTS = {
    "message.received",
    "message.sent",
    "message.bounced",
    "message.complained",
    "message.delayed",
    "inbox.created",
    "inbox.deleted",
    "domain.verified",
    "domain.failed",
    "subscription.updated",
}


WEBHOOK_FIELDS = [
    "id", "url", "events", "status", "secret", "filter",
    "delivery_stats", "created_at", "updated_at",
]


def _filter_webhook(item: dict) -> dict:
    return {k: item[k] for k in WEBHOOK_FIELDS if k in item}


def _validate_events(events: list) -> str | None:
    """Validate webhook events. Returns error message or None."""
    if not events:
        return "events must not be empty"
    invalid = [e for e in events if e not in VALID_EVENTS]
    if invalid:
        return f"Invalid events: {', '.join(invalid)}"
    return None


def _list_webhooks(org_id: str, event: dict) -> dict:
    """List webhooks for an org."""
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)

    items, last_key = query_gsi(
        "GSI1",
        f"ORG#{org_id}#WEBHOOKS",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )
    filtered = [_filter_webhook(i) for i in items]
    return success(paginated_response(filtered, last_key))


def _get_webhook(org_id: str, webhook_id: str) -> dict:
    """Get a single webhook."""
    keys = webhook_keys(org_id, webhook_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Webhook")
    return success(_filter_webhook(item))


def _create_webhook(org_id: str, body: dict) -> dict:
    """Create a new webhook."""
    err = require_fields(body, ["url", "events"])
    if err:
        return bad_request(err)

    events = body["events"]
    if not isinstance(events, list):
        return bad_request("events must be a list")

    event_err = _validate_events(events)
    if event_err:
        return bad_request(event_err)

    webhook_id = generate_ulid()
    now = now_iso()
    secret = f"whsec_{secrets.token_hex(32)}"

    item = {
        **webhook_keys(org_id, webhook_id),
        **webhook_gsi1(org_id, webhook_id),
        "id": webhook_id,
        "org_id": org_id,
        "url": body["url"],
        "events": events,
        "secret": secret,
        "status": "active",
        "filter": body.get("filter", {}),
        "delivery_stats": {
            "total": 0,
            "success": 0,
            "failed": 0,
            "last_delivered_at": None,
            "last_failed_at": None,
        },
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return created(_filter_webhook(item))


def _update_webhook(org_id: str, webhook_id: str, body: dict) -> dict:
    """Update webhook fields."""
    keys = webhook_keys(org_id, webhook_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Webhook")

    allowed = {"url", "events", "status", "filter"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return bad_request("No valid fields to update")

    # Validate events if being updated
    if "events" in updates:
        if not isinstance(updates["events"], list):
            return bad_request("events must be a list")
        event_err = _validate_events(updates["events"])
        if event_err:
            return bad_request(event_err)

    updates["updated_at"] = now_iso()
    updated = update_item(keys["PK"], keys["SK"], updates)
    return success(_filter_webhook(updated))


def _delete_webhook(org_id: str, webhook_id: str) -> dict:
    """Hard delete a webhook."""
    keys = webhook_keys(org_id, webhook_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Webhook")

    delete_item(keys["PK"], keys["SK"])
    return no_content()


def handler(event, context):
    """Route webhooks requests."""
    method = event.get("httpMethod", "")
    params = event.get("pathParameters") or {}
    webhook_id = params.get("id", "")
    org_id = get_org_id(event)
    body = parse_body(event)

    if method == "GET":
        if webhook_id:
            return _get_webhook(org_id, webhook_id)
        return _list_webhooks(org_id, event)

    if method == "POST":
        return _create_webhook(org_id, body)

    if method == "PATCH":
        return _update_webhook(org_id, webhook_id, body)

    if method == "DELETE":
        return _delete_webhook(org_id, webhook_id)

    return bad_request("Unsupported method")
