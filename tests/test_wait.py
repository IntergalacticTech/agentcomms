"""Tests for the Wait / Extract-OTP Lambda handler."""

import json

from shared.dynamo import put_item
from shared.models import (
    inbox_keys, inbox_gsi2, message_keys, message_gsi1, message_gsi3, now_iso,
)
from shared.s3 import store_body
from shared.ulid import generate_ulid
from wait.handler import handler


ORG_ID = "org_test123"
INBOX_ID = "inbox_test456"


def _seed_inbox(aws_env):
    """Seed a test inbox into DynamoDB."""
    now = now_iso()
    item = {
        **inbox_keys(ORG_ID, INBOX_ID),
        **inbox_gsi2("test@example.com", INBOX_ID),
        "id": INBOX_ID,
        "org_id": ORG_ID,
        "email": "test@example.com",
        "name": "Test Inbox",
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return item


def _seed_message(aws_env, subject="Hello", from_addr="sender@example.com",
                  body_text="Some body", is_read=False):
    """Seed a message in the inbox with body stored in S3."""
    msg_id = generate_ulid()
    thread_id = generate_ulid()
    now = now_iso()

    body_s3_key = store_body(ORG_ID, INBOX_ID, msg_id, body_text=body_text)

    item = {
        **message_keys(INBOX_ID, msg_id),
        **message_gsi1(thread_id, msg_id),
        **message_gsi3(ORG_ID, msg_id),
        "id": msg_id,
        "thread_id": thread_id,
        "inbox_id": INBOX_ID,
        "org_id": ORG_ID,
        "direction": "inbound",
        "from_addr": from_addr,
        "to": ["test@example.com"],
        "cc": [],
        "subject": subject,
        "snippet": (body_text or "")[:200],
        "body_s3_key": body_s3_key,
        "is_read": is_read,
        "is_starred": False,
        "is_spam": False,
        "is_trash": False,
        "labels": [],
        "category": "inbox",
        "has_attachments": False,
        "attachment_count": 0,
        "received_at": now,
        "created_at": now,
    }
    put_item(item)
    return item


def _make_event(path, body=None, path_params=None):
    return {
        "httpMethod": "POST",
        "path": path,
        "pathParameters": path_params or {"id": INBOX_ID},
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {"org_id": ORG_ID},
        },
    }


# -----------------------------------------------------------------------
# /wait tests
# -----------------------------------------------------------------------

def test_wait_finds_message(aws_env):
    """Seed inbox + message, call wait, verify it returns the message immediately."""
    _seed_inbox(aws_env)
    msg = _seed_message(aws_env, subject="Welcome", from_addr="noreply@example.com")

    event = _make_event(
        path=f"/inboxes/{INBOX_ID}/wait",
        body={
            "timeout": 1,
            "filter": {
                "from": "noreply@example.com",
                "subject_contains": "welcome",
            },
        },
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["id"] == msg["id"]
    assert data["subject"] == "Welcome"
    assert data["body_text"] == "Some body"


def test_wait_timeout(aws_env):
    """Seed inbox with no messages, call wait with timeout=1, verify 408."""
    _seed_inbox(aws_env)

    event = _make_event(
        path=f"/inboxes/{INBOX_ID}/wait",
        body={
            "timeout": 1,
            "filter": {
                "from": "nobody@example.com",
            },
        },
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 408

    data = json.loads(resp["body"])
    assert data["error"]["code"] == "TIMEOUT"


# -----------------------------------------------------------------------
# /extract-otp tests
# -----------------------------------------------------------------------

def test_extract_otp_finds_code(aws_env):
    """Seed message with OTP in body, verify it extracts the code."""
    _seed_inbox(aws_env)
    msg = _seed_message(
        aws_env,
        subject="Your verification code",
        from_addr="noreply@example.com",
        body_text="Your code is 482917. It expires in 10 minutes.",
    )

    event = _make_event(
        path=f"/inboxes/{INBOX_ID}/extract-otp",
        body={
            "timeout": 1,
            "sender": "noreply@example.com",
            "subject_contains": "verification",
        },
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["code"] == "482917"
    assert data["message_id"] == msg["id"]
    assert data["from"] == "noreply@example.com"
    assert data["subject"] == "Your verification code"


def test_extract_otp_no_code(aws_env):
    """Seed message with no code, verify code=null and body_text included."""
    _seed_inbox(aws_env)
    _seed_message(
        aws_env,
        subject="Just a note",
        from_addr="friend@example.com",
        body_text="Hey, how are you doing today?",
    )

    event = _make_event(
        path=f"/inboxes/{INBOX_ID}/extract-otp",
        body={
            "timeout": 1,
            "sender": "friend@example.com",
        },
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["code"] is None
    assert "body_text" in data
    assert "how are you doing" in data["body_text"]
