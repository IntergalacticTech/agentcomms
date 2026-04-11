"""Messages Lambda handler."""

import json
import os

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, query, query_gsi
from shared.models import (
    message_keys, message_gsi1, message_gsi3, now_iso,
    inbox_keys, thread_keys, thread_gsi1,
)
from shared.pagination import get_pagination_params, decode_page_token, paginated_response
from shared.response import success, created, bad_request, not_found
from shared.s3 import store_body, get_body
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields
from shared.webhook_publisher import publish_event

SEND_QUEUE_URL = os.environ.get("SEND_QUEUE_URL", "")

# Fields to include in list/summary responses
MESSAGE_LIST_FIELDS = [
    "id", "thread_id", "inbox_id", "direction", "from_addr", "to", "cc",
    "subject", "snippet", "is_read", "is_starred", "is_spam", "is_trash",
    "labels", "category", "has_attachments", "attachment_count",
    "received_at", "created_at",
]

# Additional fields for detail responses (get, send, reply, forward)
MESSAGE_DETAIL_FIELDS = MESSAGE_LIST_FIELDS + [
    "bcc", "reply_to", "body_text", "body_html", "headers",
    "ses_message_id", "status",
]


def _filter_message(item: dict, detail: bool = False) -> dict:
    fields = MESSAGE_DETAIL_FIELDS if detail else MESSAGE_LIST_FIELDS
    return {k: item[k] for k in fields if k in item}


def _enqueue_send(message_id: str, inbox_id: str):
    """Enqueue message to SQS for sending if SEND_QUEUE_URL is configured."""
    if not SEND_QUEUE_URL:
        return
    try:
        import boto3
        sqs = boto3.client("sqs")
        kwargs = {
            "QueueUrl": SEND_QUEUE_URL,
            "MessageBody": json.dumps({"message_id": message_id, "inbox_id": inbox_id}),
        }
        # FIFO queues require MessageGroupId (and MessageDeduplicationId
        # unless content-based deduplication is enabled on the queue).
        if SEND_QUEUE_URL.endswith(".fifo"):
            kwargs["MessageGroupId"] = inbox_id
            kwargs["MessageDeduplicationId"] = message_id
        sqs.send_message(**kwargs)
    except Exception:
        # Don't let SQS failures crash the API response; the message is
        # already persisted in DynamoDB and can be retried later.
        pass


def _get_inbox(org_id: str, inbox_id: str) -> dict | None:
    """Fetch an inbox item from DynamoDB."""
    keys = inbox_keys(org_id, inbox_id)
    return get_item(keys["PK"], keys["SK"])


def _send_message(org_id: str, inbox_id: str, body: dict, thread_id: str | None = None) -> dict:
    """Create and store a new outbound message."""
    inbox = _get_inbox(org_id, inbox_id)
    if not inbox:
        return not_found("Inbox")

    msg_id = generate_ulid()
    now = now_iso()
    tid = thread_id or generate_ulid()

    body_text = body.get("body_text")
    body_html = body.get("body_html")
    body_s3_key = store_body(org_id, inbox_id, msg_id, body_text=body_text, body_html=body_html)

    snippet = ""
    if body_text:
        snippet = body_text[:200]

    to_addrs = body.get("to", [])
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    cc = body.get("cc", [])
    if isinstance(cc, str):
        cc = [cc]

    bcc = body.get("bcc", [])
    if isinstance(bcc, str):
        bcc = [bcc]

    from_addr = inbox.get("email", inbox.get("address", ""))

    msg_item = {
        **message_keys(inbox_id, msg_id),
        **message_gsi1(tid, msg_id),
        **message_gsi3(org_id, msg_id),
        "id": msg_id,
        "thread_id": tid,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "direction": "outbound",
        "from_addr": from_addr,
        "to": to_addrs,
        "cc": cc,
        "bcc": bcc,
        "reply_to": body.get("reply_to", ""),
        "subject": body.get("subject", ""),
        "snippet": snippet,
        "body_s3_key": body_s3_key,
        "is_read": True,
        "is_starred": False,
        "is_spam": False,
        "is_trash": False,
        "labels": body.get("labels", []),
        "category": body.get("category", "sent"),
        "headers": body.get("headers", {}),
        "ses_message_id": "",
        "attachment_count": 0,
        "has_attachments": False,
        "status": "queued",
        "received_at": now,
        "created_at": now,
    }
    put_item(msg_item)

    # Create or update thread
    thread_item = {
        **thread_keys(inbox_id, tid),
        **thread_gsi1(inbox_id, tid),
        "id": tid,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "subject": body.get("subject", ""),
        "snippet": snippet,
        "message_count": 1,
        "is_read": True,
        "is_starred": False,
        "is_trash": False,
        "labels": body.get("labels", []),
        "last_message_at": now,
        "created_at": now,
        "updated_at": now,
    }
    put_item(thread_item)

    _enqueue_send(msg_id, inbox_id)

    # Publish webhook event
    try:
        publish_event("message.sent", org_id, {
            "message_id": msg_id,
            "inbox_id": inbox_id,
            "from": from_addr,
            "to": to_addrs,
            "subject": body.get("subject", ""),
            "sent_at": now,
        })
    except Exception:
        pass  # Don't let webhook publishing break the API response

    return created(_filter_message(msg_item, detail=True))


def _list_messages(inbox_id: str, event: dict) -> dict:
    """List messages in an inbox."""
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)

    items, last_key = query(
        pk=f"INBOX#{inbox_id}",
        sk_prefix="MSG#",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )
    filtered = [_filter_message(i) for i in items]
    return success(paginated_response(filtered, last_key))


def _get_message(inbox_id: str, message_id: str) -> dict:
    """Get a single message with body from S3."""
    keys = message_keys(inbox_id, message_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Message")

    # Fetch body from S3
    if item.get("body_s3_key"):
        try:
            body_data = get_body(item["body_s3_key"])
            item.update(body_data)
        except Exception:
            pass

    return success(_filter_message(item, detail=True))


def _update_message(inbox_id: str, message_id: str, body: dict) -> dict:
    """Update message fields."""
    keys = message_keys(inbox_id, message_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Message")

    allowed = {"is_read", "is_starred", "is_trash", "labels"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return bad_request("No valid fields to update")

    updates["updated_at"] = now_iso()
    updated = update_item(keys["PK"], keys["SK"], updates)
    return success(_filter_message(updated, detail=True))


def _reply(org_id: str, inbox_id: str, message_id: str, body: dict) -> dict:
    """Reply to a message."""
    keys = message_keys(inbox_id, message_id)
    original = get_item(keys["PK"], keys["SK"])
    if not original:
        return not_found("Message")

    subject = original.get("subject", "")
    if not subject.startswith("Re:"):
        subject = f"Re: {subject}"

    reply_body = {
        **body,
        "to": body.get("to", [original.get("from_addr", "")]),
        "subject": subject,
    }
    return _send_message(org_id, inbox_id, reply_body, thread_id=original.get("thread_id"))


def _reply_all(org_id: str, inbox_id: str, message_id: str, body: dict) -> dict:
    """Reply-all to a message."""
    keys = message_keys(inbox_id, message_id)
    original = get_item(keys["PK"], keys["SK"])
    if not original:
        return not_found("Message")

    subject = original.get("subject", "")
    if not subject.startswith("Re:"):
        subject = f"Re: {subject}"

    # Combine original from + to + cc, minus our own address
    inbox = _get_inbox(org_id, inbox_id)
    our_email = inbox.get("email", "") if inbox else ""
    all_recipients = set()
    all_recipients.add(original.get("from_addr", ""))
    for addr in original.get("to", []):
        all_recipients.add(addr)
    for addr in original.get("cc", []):
        all_recipients.add(addr)
    all_recipients.discard(our_email)

    reply_body = {
        **body,
        "to": body.get("to", list(all_recipients)),
        "subject": subject,
    }
    return _send_message(org_id, inbox_id, reply_body, thread_id=original.get("thread_id"))


def _forward(org_id: str, inbox_id: str, message_id: str, body: dict) -> dict:
    """Forward a message."""
    keys = message_keys(inbox_id, message_id)
    original = get_item(keys["PK"], keys["SK"])
    if not original:
        return not_found("Message")

    err = require_fields(body, ["to"])
    if err:
        return bad_request(err)

    subject = original.get("subject", "")
    if not subject.startswith("Fwd:"):
        subject = f"Fwd: {subject}"

    # Get original body from S3 if not provided
    if not body.get("body_text") and not body.get("body_html"):
        if original.get("body_s3_key"):
            try:
                original_body = get_body(original["body_s3_key"])
                body["body_text"] = original_body.get("body_text")
                body["body_html"] = original_body.get("body_html")
            except Exception:
                pass

    fwd_body = {
        **body,
        "subject": subject,
    }
    # New thread for forwards
    return _send_message(org_id, inbox_id, fwd_body)


def handler(event, context):
    """Route messages requests."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    params = event.get("pathParameters") or {}
    inbox_id = params.get("id", "")
    message_id = params.get("mid", "")
    org_id = get_org_id(event)
    body = parse_body(event)

    # Sub-routes for reply/reply-all/forward
    if path.endswith("/reply"):
        return _reply(org_id, inbox_id, message_id, body)
    if path.endswith("/reply-all"):
        return _reply_all(org_id, inbox_id, message_id, body)
    if path.endswith("/forward"):
        return _forward(org_id, inbox_id, message_id, body)

    if method == "GET":
        if message_id:
            return _get_message(inbox_id, message_id)
        return _list_messages(inbox_id, event)

    if method == "POST":
        err = require_fields(body, ["to", "subject"])
        if err:
            return bad_request(err)
        if not body.get("body_text") and not body.get("body_html"):
            return bad_request("At least one of body_text or body_html is required")
        return _send_message(org_id, inbox_id, body)

    if method == "PATCH":
        return _update_message(inbox_id, message_id, body)

    return bad_request("Unsupported method")
