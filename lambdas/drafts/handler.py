"""Drafts Lambda handler."""

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, delete_item, query_gsi
from shared.models import draft_keys, draft_gsi1, now_iso
from shared.pagination import get_pagination_params, decode_page_token, paginated_response
from shared.response import success, created, bad_request, not_found, no_content
from shared.ulid import generate_ulid
from shared.validation import parse_body


def _list_drafts(inbox_id: str, event: dict) -> dict:
    """List drafts in an inbox."""
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)

    items, last_key = query_gsi(
        "GSI1",
        f"INBOX#{inbox_id}#DRAFTS",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )
    return success(paginated_response(items, last_key))


def _get_draft(inbox_id: str, draft_id: str) -> dict:
    """Get a single draft."""
    keys = draft_keys(inbox_id, draft_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Draft")
    return success(item)


def _create_draft(org_id: str, inbox_id: str, body: dict) -> dict:
    """Create a new draft."""
    draft_id = generate_ulid()
    now = now_iso()

    to = body.get("to", [])
    if isinstance(to, str):
        to = [to]
    cc = body.get("cc", [])
    if isinstance(cc, str):
        cc = [cc]
    bcc = body.get("bcc", [])
    if isinstance(bcc, str):
        bcc = [bcc]

    item = {
        **draft_keys(inbox_id, draft_id),
        **draft_gsi1(inbox_id, draft_id),
        "id": draft_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": body.get("thread_id", ""),
        "in_reply_to_message_id": body.get("in_reply_to_message_id", ""),
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "subject": body.get("subject", ""),
        "body_text": body.get("body_text", ""),
        "body_html": body.get("body_html", ""),
        "attachments": body.get("attachments", []),
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return created(item)


def _update_draft(inbox_id: str, draft_id: str, body: dict) -> dict:
    """Update a draft."""
    keys = draft_keys(inbox_id, draft_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Draft")

    allowed = {
        "to", "cc", "bcc", "subject", "body_text", "body_html",
        "attachments", "thread_id", "in_reply_to_message_id",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return bad_request("No valid fields to update")

    updates["updated_at"] = now_iso()
    updated = update_item(keys["PK"], keys["SK"], updates)
    return success(updated)


def _delete_draft(inbox_id: str, draft_id: str) -> dict:
    """Hard delete a draft."""
    keys = draft_keys(inbox_id, draft_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Draft")

    delete_item(keys["PK"], keys["SK"])
    return no_content()


def _send_draft(org_id: str, inbox_id: str, draft_id: str) -> dict:
    """Convert a draft to a sent message and delete the draft."""
    keys = draft_keys(inbox_id, draft_id)
    draft = get_item(keys["PK"], keys["SK"])
    if not draft:
        return not_found("Draft")

    # Import messages handler send logic
    from messages.handler import _send_message

    send_body = {
        "to": draft.get("to", []),
        "cc": draft.get("cc", []),
        "bcc": draft.get("bcc", []),
        "subject": draft.get("subject", ""),
        "body_text": draft.get("body_text", ""),
        "body_html": draft.get("body_html", ""),
    }
    thread_id = draft.get("thread_id") or None

    result = _send_message(org_id, inbox_id, send_body, thread_id=thread_id)

    # Delete draft on success
    if result.get("statusCode") == 201:
        delete_item(keys["PK"], keys["SK"])

    return result


def handler(event, context):
    """Route drafts requests."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    params = event.get("pathParameters") or {}
    inbox_id = params.get("id", "")
    draft_id = params.get("did", "")
    org_id = get_org_id(event)
    body = parse_body(event)

    # Sub-route: send draft
    if path.endswith("/send") and method == "POST":
        return _send_draft(org_id, inbox_id, draft_id)

    if method == "GET":
        if draft_id:
            return _get_draft(inbox_id, draft_id)
        return _list_drafts(inbox_id, event)

    if method == "POST":
        return _create_draft(org_id, inbox_id, body)

    if method == "PATCH":
        return _update_draft(inbox_id, draft_id, body)

    if method == "DELETE":
        return _delete_draft(inbox_id, draft_id)

    return bad_request("Unsupported method")
