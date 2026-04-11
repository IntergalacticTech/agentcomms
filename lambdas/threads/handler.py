"""Threads Lambda handler."""

from shared.auth import get_org_id
from shared.dynamo import get_item, update_item, query_gsi
from shared.models import thread_keys, now_iso
from shared.pagination import get_pagination_params, decode_page_token, paginated_response
from shared.response import success, bad_request, not_found
from shared.validation import parse_body


def _list_threads(inbox_id: str, event: dict) -> dict:
    """List threads in an inbox."""
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)

    items, last_key = query_gsi(
        "GSI1",
        f"INBOX#{inbox_id}#THREADS",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )
    return success(paginated_response(items, last_key))


def _get_thread(inbox_id: str, thread_id: str) -> dict:
    """Get a single thread and its messages."""
    keys = thread_keys(inbox_id, thread_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Thread")

    # Fetch messages in this thread
    messages, _ = query_gsi("GSI1", f"THREAD#{thread_id}")
    item["messages"] = messages
    return success(item)


def _update_thread(inbox_id: str, thread_id: str, body: dict) -> dict:
    """Update thread fields."""
    keys = thread_keys(inbox_id, thread_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Thread")

    allowed = {"is_read", "is_starred", "is_trash", "labels"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return bad_request("No valid fields to update")

    updates["updated_at"] = now_iso()
    updated = update_item(keys["PK"], keys["SK"], updates)
    return success(updated)


def _delete_thread(inbox_id: str, thread_id: str) -> dict:
    """Soft delete a thread (set is_trash=True)."""
    keys = thread_keys(inbox_id, thread_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Thread")

    updates = {"is_trash": True, "updated_at": now_iso()}
    updated = update_item(keys["PK"], keys["SK"], updates)
    return success(updated)


def handler(event, context):
    """Route threads requests."""
    method = event.get("httpMethod", "")
    params = event.get("pathParameters") or {}
    inbox_id = params.get("id", "")
    thread_id = params.get("tid", "")
    body = parse_body(event)

    if method == "GET":
        if thread_id:
            return _get_thread(inbox_id, thread_id)
        return _list_threads(inbox_id, event)

    if method == "PATCH":
        return _update_thread(inbox_id, thread_id, body)

    if method == "DELETE":
        return _delete_thread(inbox_id, thread_id)

    return bad_request("Unsupported method")
