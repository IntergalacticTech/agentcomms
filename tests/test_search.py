"""Tests for search Lambda handler."""

import json

from shared.dynamo import put_item
from shared.models import message_keys, message_gsi1, message_gsi3, now_iso


def _seed_message(org_id, inbox_id, message_id, thread_id, subject, snippet="", created_at=None):
    """Seed a message in DynamoDB for search testing."""
    ts = created_at or now_iso()
    item = {
        **message_keys(inbox_id, message_id),
        **message_gsi1(thread_id, message_id),
        **message_gsi3(org_id, message_id),
        "entity_type": "message",
        "message_id": message_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": thread_id,
        "direction": "inbound",
        "status": "received",
        "subject": subject,
        "snippet": snippet,
        "created_at": ts,
        "updated_at": ts,
    }
    put_item(item)
    return item


def _make_event(org_id, body):
    """Create a mock API Gateway event for the search handler."""
    return {
        "httpMethod": "POST",
        "path": "/search",
        "body": json.dumps(body),
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
            }
        },
    }


def test_search_by_query(aws_env):
    """Test searching messages by query text."""
    org_id = "org_search_01"
    inbox_id = "inbox_s01"

    _seed_message(org_id, inbox_id, "msg_s01", "thread_s01", "Pricing Discussion", snippet="Let's talk about pricing plans")
    _seed_message(org_id, inbox_id, "msg_s02", "thread_s02", "Meeting Notes", snippet="Notes from Monday standup")
    _seed_message(org_id, inbox_id, "msg_s03", "thread_s03", "Invoice for Pricing", snippet="Please find attached invoice")

    from search.handler import handler

    # Search for "pricing" - should match msg_s01 and msg_s03
    event = _make_event(org_id, {"query": "pricing"})
    resp = handler(event, None)
    body = json.loads(resp["body"])

    assert resp["statusCode"] == 200
    assert body["total"] == 2
    subjects = {item["subject"] for item in body["data"]}
    assert "Pricing Discussion" in subjects
    assert "Invoice for Pricing" in subjects

    # Search for "standup" - should match only msg_s02
    event = _make_event(org_id, {"query": "standup"})
    resp = handler(event, None)
    body = json.loads(resp["body"])

    assert body["total"] == 1
    assert body["data"][0]["subject"] == "Meeting Notes"


def test_search_by_inbox(aws_env):
    """Test searching messages filtered by inbox_id."""
    org_id = "org_search_02"
    inbox_a = "inbox_sa"
    inbox_b = "inbox_sb"

    _seed_message(org_id, inbox_a, "msg_sa1", "thread_sa1", "Hello from A", snippet="hello world")
    _seed_message(org_id, inbox_b, "msg_sb1", "thread_sb1", "Hello from B", snippet="hello world")
    _seed_message(org_id, inbox_a, "msg_sa2", "thread_sa2", "Goodbye from A", snippet="goodbye world")

    from search.handler import handler

    # Search for "hello" filtered to inbox_a
    event = _make_event(org_id, {"query": "hello", "inbox_id": inbox_a})
    resp = handler(event, None)
    body = json.loads(resp["body"])

    assert resp["statusCode"] == 200
    assert body["total"] == 1
    assert body["data"][0]["subject"] == "Hello from A"

    # Search all inboxes for "hello"
    event = _make_event(org_id, {"query": "hello"})
    resp = handler(event, None)
    body = json.loads(resp["body"])

    assert body["total"] == 2


def test_search_by_date_range(aws_env):
    """Test searching messages filtered by date range."""
    org_id = "org_search_03"
    inbox_id = "inbox_s03"

    _seed_message(org_id, inbox_id, "msg_old", "t1", "Old Message", created_at="2026-04-01T10:00:00+00:00")
    _seed_message(org_id, inbox_id, "msg_mid", "t2", "Mid Message", created_at="2026-04-05T10:00:00+00:00")
    _seed_message(org_id, inbox_id, "msg_new", "t3", "New Message", created_at="2026-04-09T10:00:00+00:00")

    from search.handler import handler

    # Search with after filter
    event = _make_event(org_id, {"after": "2026-04-04T00:00:00+00:00"})
    resp = handler(event, None)
    body = json.loads(resp["body"])

    assert body["total"] == 2
    subjects = {item["subject"] for item in body["data"]}
    assert "Mid Message" in subjects
    assert "New Message" in subjects

    # Search with before filter
    event = _make_event(org_id, {"before": "2026-04-06T00:00:00+00:00"})
    resp = handler(event, None)
    body = json.loads(resp["body"])

    assert body["total"] == 2
    subjects = {item["subject"] for item in body["data"]}
    assert "Old Message" in subjects
    assert "Mid Message" in subjects


def test_search_respects_limit(aws_env):
    """Test that search respects the limit parameter."""
    org_id = "org_search_04"
    inbox_id = "inbox_s04"

    for i in range(10):
        _seed_message(org_id, inbox_id, f"msg_lim_{i}", f"t_lim_{i}", f"Message {i}", snippet="common text")

    from search.handler import handler

    event = _make_event(org_id, {"query": "common", "limit": 3})
    resp = handler(event, None)
    body = json.loads(resp["body"])

    assert body["total"] == 3
    assert len(body["data"]) == 3
