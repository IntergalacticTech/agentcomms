"""Tests for the Messages Lambda handler."""

import json

from shared.dynamo import put_item
from shared.models import inbox_keys, inbox_gsi2, now_iso
from messages.handler import handler


ORG_ID = "org_test123"
INBOX_ID = "inbox_test456"


def _seed_inbox(aws_env):
    """Seed a test inbox into DynamoDB."""
    now = now_iso()
    item = {
        **inbox_keys(ORG_ID, INBOX_ID),
        **inbox_gsi2(f"test@example.com", INBOX_ID),
        "id": INBOX_ID,
        "org_id": ORG_ID,
        "email": "test@example.com",
        "name": "Test Inbox",
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return item


def _make_event(method, path="/", path_params=None, body=None, query_params=None):
    event = {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {"org_id": ORG_ID},
        },
    }
    return event


def test_send_message(aws_env):
    """Test sending a new message."""
    _seed_inbox(aws_env)

    event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
        body={
            "to": ["recipient@example.com"],
            "subject": "Hello World",
            "body_text": "This is a test message",
        },
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 201

    data = json.loads(resp["body"])
    assert data["subject"] == "Hello World"
    assert data["direction"] == "outbound"
    assert data["from_addr"] == "test@example.com"
    assert data["to"] == ["recipient@example.com"]
    assert data["status"] == "queued"
    assert "body_s3_key" not in data  # internal field filtered from response


def test_send_message_missing_fields(aws_env):
    """Test sending a message with missing required fields."""
    _seed_inbox(aws_env)

    event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
        body={"to": ["recipient@example.com"]},
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 400


def test_send_message_no_body(aws_env):
    """Test sending a message with no body content."""
    _seed_inbox(aws_env)

    event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
        body={"to": ["recipient@example.com"], "subject": "No Body"},
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 400


def test_list_messages(aws_env):
    """Test listing messages after sending one."""
    _seed_inbox(aws_env)

    # Send a message first
    send_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
        body={
            "to": ["recipient@example.com"],
            "subject": "Test",
            "body_text": "body",
        },
    )
    handler(send_event, None)

    # List messages
    list_event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
    )
    resp = handler(list_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert len(data["data"]) == 1
    assert data["data"][0]["subject"] == "Test"


def test_get_message(aws_env):
    """Test getting a single message with body from S3."""
    _seed_inbox(aws_env)

    send_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
        body={
            "to": ["recipient@example.com"],
            "subject": "Get Me",
            "body_text": "Full body content here",
        },
    )
    send_resp = handler(send_event, None)
    msg = json.loads(send_resp["body"])
    msg_id = msg["id"]

    get_event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/messages/{msg_id}",
        path_params={"id": INBOX_ID, "mid": msg_id},
    )
    resp = handler(get_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["subject"] == "Get Me"
    assert data["body_text"] == "Full body content here"


def test_update_message(aws_env):
    """Test updating message flags."""
    _seed_inbox(aws_env)

    send_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
        body={
            "to": ["recipient@example.com"],
            "subject": "Update Me",
            "body_text": "body",
        },
    )
    send_resp = handler(send_event, None)
    msg = json.loads(send_resp["body"])
    msg_id = msg["id"]

    patch_event = _make_event(
        "PATCH",
        path=f"/inboxes/{INBOX_ID}/messages/{msg_id}",
        path_params={"id": INBOX_ID, "mid": msg_id},
        body={"is_starred": True, "is_read": False},
    )
    resp = handler(patch_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["is_starred"] is True
    assert data["is_read"] is False


def test_reply_message(aws_env):
    """Test replying to a message."""
    _seed_inbox(aws_env)

    send_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
        body={
            "to": ["sender@example.com"],
            "subject": "Original Subject",
            "body_text": "original",
        },
    )
    send_resp = handler(send_event, None)
    msg = json.loads(send_resp["body"])
    msg_id = msg["id"]

    reply_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages/{msg_id}/reply",
        path_params={"id": INBOX_ID, "mid": msg_id},
        body={"body_text": "This is my reply"},
    )
    resp = handler(reply_event, None)
    assert resp["statusCode"] == 201

    data = json.loads(resp["body"])
    assert data["subject"] == "Re: Original Subject"
    assert data["thread_id"] == msg["thread_id"]


def test_forward_message(aws_env):
    """Test forwarding a message."""
    _seed_inbox(aws_env)

    send_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages",
        path_params={"id": INBOX_ID},
        body={
            "to": ["sender@example.com"],
            "subject": "Forward This",
            "body_text": "forward me",
        },
    )
    send_resp = handler(send_event, None)
    msg = json.loads(send_resp["body"])
    msg_id = msg["id"]

    fwd_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/messages/{msg_id}/forward",
        path_params={"id": INBOX_ID, "mid": msg_id},
        body={"to": ["newrecipient@example.com"]},
    )
    resp = handler(fwd_event, None)
    assert resp["statusCode"] == 201

    data = json.loads(resp["body"])
    assert data["subject"] == "Fwd: Forward This"
    assert data["thread_id"] != msg["thread_id"]
