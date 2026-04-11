"""Wait-for-email and OTP extraction Lambda handler."""

import re
import time

from shared.auth import get_org_id
from shared.dynamo import query
from shared.models import message_keys
from shared.response import success, bad_request, error
from shared.s3 import get_body
from shared.validation import parse_body


# Maximum wait to stay safely under Lambda 30s timeout
MAX_TIMEOUT = 25
POLL_INTERVAL = 2


def _matches_filter(item: dict, filters: dict) -> bool:
    """Check whether a message item matches all provided filter criteria."""
    if "from" in filters:
        from_addr = item.get("from_addr", "")
        # from_addr can be a dict with 'address' key or a plain string
        if isinstance(from_addr, dict):
            from_addr = from_addr.get("address", "")
        if filters["from"].lower() not in from_addr.lower():
            return False

    if "subject_contains" in filters:
        subject = item.get("subject", "")
        if filters["subject_contains"].lower() not in subject.lower():
            return False

    if "after" in filters:
        created_at = item.get("created_at", "")
        if created_at <= filters["after"]:
            return False

    if "is_read" in filters:
        if item.get("is_read") != filters["is_read"]:
            return False

    return True


def _find_matching_message(inbox_id: str, filters: dict) -> dict | None:
    """Query messages in the inbox and return the first matching one."""
    items, _ = query(
        pk=f"INBOX#{inbox_id}",
        sk_prefix="MSG#",
        limit=100,
        ascending=False,  # newest first
    )
    for item in items:
        if _matches_filter(item, filters):
            return item
    return None


def _enrich_with_body(item: dict) -> dict:
    """Fetch body from S3 and merge into the message item."""
    if item.get("body_s3_key"):
        try:
            body_data = get_body(item["body_s3_key"])
            item.update(body_data)
        except Exception:
            pass
    return item


def _wait_for_message(inbox_id: str, filters: dict, timeout: int) -> dict | None:
    """Poll for a matching message up to timeout seconds."""
    deadline = time.time() + timeout
    while True:
        msg = _find_matching_message(inbox_id, filters)
        if msg is not None:
            return msg
        remaining = deadline - time.time()
        if remaining <= 0:
            return None
        time.sleep(min(POLL_INTERVAL, remaining))


def _extract_otp(text: str) -> str | None:
    """Extract an OTP / verification code from message text."""
    if not text:
        return None

    # Codes with dashes (e.g. 123-456)
    m = re.search(r'\b(\d{3}-\d{3})\b', text)
    if m:
        return m.group(1)

    # 4-8 digit numeric codes
    m = re.search(r'\b(\d{4,8})\b', text)
    if m:
        return m.group(1)

    # Alphanumeric codes (only if no numeric match)
    m = re.search(r'\b([A-Z0-9]{6,10})\b', text)
    if m:
        return m.group(1)

    return None


def handle_wait(event: dict) -> dict:
    """Handle POST /inboxes/{id}/wait."""
    params = event.get("pathParameters") or {}
    inbox_id = params.get("id", "")
    if not inbox_id:
        return bad_request("Missing inbox id")

    body = parse_body(event)
    timeout = min(int(body.get("timeout", MAX_TIMEOUT)), MAX_TIMEOUT)
    filters = body.get("filter", {})

    msg = _wait_for_message(inbox_id, filters, timeout)
    if msg is None:
        return error(
            "TIMEOUT",
            "No matching message received within timeout period.",
            408,
        )

    msg = _enrich_with_body(msg)
    return success(msg)


def handle_extract_otp(event: dict) -> dict:
    """Handle POST /inboxes/{id}/extract-otp."""
    params = event.get("pathParameters") or {}
    inbox_id = params.get("id", "")
    if not inbox_id:
        return bad_request("Missing inbox id")

    body = parse_body(event)
    timeout = min(int(body.get("timeout", MAX_TIMEOUT)), MAX_TIMEOUT)

    # Build filters from the convenience fields
    filters = {}
    if body.get("sender"):
        filters["from"] = body["sender"]
    if body.get("subject_contains"):
        filters["subject_contains"] = body["subject_contains"]
    if body.get("after"):
        filters["after"] = body["after"]

    msg = _wait_for_message(inbox_id, filters, timeout)
    if msg is None:
        return error(
            "TIMEOUT",
            "No matching message received within timeout period.",
            408,
        )

    msg = _enrich_with_body(msg)

    body_text = msg.get("body_text", "") or ""
    body_html = msg.get("body_html", "") or ""
    code = _extract_otp(body_text) or _extract_otp(body_html)

    from_addr = msg.get("from_addr", "")
    if isinstance(from_addr, dict):
        from_addr = from_addr.get("address", "")

    result = {
        "code": code,
        "message_id": msg.get("id", ""),
        "from": from_addr,
        "subject": msg.get("subject", ""),
    }

    if code is None:
        result["body_text"] = body_text

    return success(result)


def handler(event, context):
    """Route wait / extract-otp requests."""
    path = event.get("path", "")
    if path.endswith("/wait"):
        return handle_wait(event)
    elif path.endswith("/extract-otp"):
        return handle_extract_otp(event)
    return bad_request("Unsupported")
