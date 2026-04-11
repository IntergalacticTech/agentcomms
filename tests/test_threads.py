"""Tests for the Threads Lambda handler."""

import json

from shared.dynamo import put_item
from shared.models import inbox_keys, inbox_gsi2, thread_keys, thread_gsi1, now_iso
from threads.handler import handler


ORG_ID = "org_test123"
INBOX_ID = "inbox_test456"
THREAD_ID = "thread_test789"


def _seed_inbox_and_thread(aws_env):
    """Seed a test inbox and thread."""
    now = now_iso()
    put_item({
        **inbox_keys(ORG_ID, INBOX_ID),
        **inbox_gsi2("test@example.com", INBOX_ID),
        "id": INBOX_ID,
        "org_id": ORG_ID,
        "email": "test@example.com",
        "created_at": now,
    })
    thread_item = {
        **thread_keys(INBOX_ID, THREAD_ID),
        **thread_gsi1(INBOX_ID, THREAD_ID),
        "id": THREAD_ID,
        "inbox_id": INBOX_ID,
        "org_id": ORG_ID,
        "subject": "Test Thread",
        "snippet": "Hello...",
        "message_count": 1,
        "is_read": False,
        "is_starred": False,
        "is_trash": False,
        "labels": [],
        "last_message_at": now,
        "created_at": now,
        "updated_at": now,
    }
    put_item(thread_item)
    return thread_item


def _make_event(method, path="/", path_params=None, body=None, query_params=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {"org_id": ORG_ID},
        },
    }


def test_list_threads(aws_env):
    """Test listing threads."""
    _seed_inbox_and_thread(aws_env)

    event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/threads",
        path_params={"id": INBOX_ID},
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert len(data["data"]) == 1
    assert data["data"][0]["subject"] == "Test Thread"


def test_get_thread(aws_env):
    """Test getting a single thread."""
    _seed_inbox_and_thread(aws_env)

    event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/threads/{THREAD_ID}",
        path_params={"id": INBOX_ID, "tid": THREAD_ID},
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["subject"] == "Test Thread"
    assert "messages" in data


def test_update_thread(aws_env):
    """Test updating thread flags."""
    _seed_inbox_and_thread(aws_env)

    event = _make_event(
        "PATCH",
        path=f"/inboxes/{INBOX_ID}/threads/{THREAD_ID}",
        path_params={"id": INBOX_ID, "tid": THREAD_ID},
        body={"is_read": True, "is_starred": True},
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["is_read"] is True
    assert data["is_starred"] is True


def test_delete_thread(aws_env):
    """Test soft deleting a thread."""
    _seed_inbox_and_thread(aws_env)

    event = _make_event(
        "DELETE",
        path=f"/inboxes/{INBOX_ID}/threads/{THREAD_ID}",
        path_params={"id": INBOX_ID, "tid": THREAD_ID},
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["is_trash"] is True


def test_get_thread_not_found(aws_env):
    """Test getting a nonexistent thread."""
    event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/threads/nonexistent",
        path_params={"id": INBOX_ID, "tid": "nonexistent"},
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 404
