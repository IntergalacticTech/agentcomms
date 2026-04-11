"""Tests for the Metrics Lambda handler."""

import json

from shared.dynamo import put_item
from shared.models import org_keys, inbox_keys, message_keys, message_gsi3, now_iso
from metrics.handler import handler


ORG_ID = "org_test_metrics"
INBOX_ID = "inbox_m1"


def _make_event(method, path="/", body=None, query_params=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": {},
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {"org_id": ORG_ID},
        },
    }


def _seed_org(aws_env):
    """Seed an org record with usage data."""
    item = {
        **org_keys(ORG_ID),
        "id": ORG_ID,
        "name": "Test Org",
        "tier": "free",
        "status": "active",
        "usage": {
            "inboxes": 5,
            "messages_today": 142,
            "api_keys": 2,
            "pods": 1,
            "domains": 1,
            "webhooks": 2,
        },
        "quotas": {
            "max_inboxes": 10,
            "max_messages_per_day": 500,
        },
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    put_item(item)
    return item


def _seed_messages(aws_env):
    """Seed some messages for metrics queries."""
    messages = [
        {
            **message_keys(INBOX_ID, "msg_001"),
            **message_gsi3(ORG_ID, "msg_001"),
            "id": "msg_001",
            "inbox_id": INBOX_ID,
            "org_id": ORG_ID,
            "direction": "outbound",
            "subject": "Hello 1",
            "created_at": "2026-04-01T10:00:00.000Z",
        },
        {
            **message_keys(INBOX_ID, "msg_002"),
            **message_gsi3(ORG_ID, "msg_002"),
            "id": "msg_002",
            "inbox_id": INBOX_ID,
            "org_id": ORG_ID,
            "direction": "outbound",
            "subject": "Hello 2",
            "created_at": "2026-04-01T14:00:00.000Z",
        },
        {
            **message_keys(INBOX_ID, "msg_003"),
            **message_gsi3(ORG_ID, "msg_003"),
            "id": "msg_003",
            "inbox_id": INBOX_ID,
            "org_id": ORG_ID,
            "direction": "inbound",
            "subject": "Reply 1",
            "created_at": "2026-04-02T09:00:00.000Z",
        },
        {
            **message_keys(INBOX_ID, "msg_004"),
            **message_gsi3(ORG_ID, "msg_004"),
            "id": "msg_004",
            "inbox_id": INBOX_ID,
            "org_id": ORG_ID,
            "direction": "outbound",
            "subject": "Hello 3",
            "created_at": "2026-04-02T15:00:00.000Z",
        },
    ]
    for msg in messages:
        put_item(msg)
    return messages


def test_usage_summary(aws_env):
    """Test GET /metrics/usage returns org usage data."""
    _seed_org(aws_env)

    event = _make_event("GET", "/metrics/usage")
    resp = handler(event, None)

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["inboxes"] == 5
    assert data["messages_today"] == 142
    assert data["api_keys"] == 2
    assert data["pods"] == 1
    assert data["domains"] == 1
    assert data["webhooks"] == 2
    assert data["tier"] == "free"
    assert data["quotas"]["max_inboxes"] == 10


def test_usage_summary_no_org(aws_env):
    """Test GET /metrics/usage returns defaults when org not found."""
    event = _make_event("GET", "/metrics/usage")
    resp = handler(event, None)

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["inboxes"] == 0
    assert data["tier"] == "free"


def test_metrics_query(aws_env):
    """Test POST /metrics/query returns time-series data grouped by day."""
    _seed_messages(aws_env)

    event = _make_event("POST", "/metrics/query", body={
        "metric": "messages_sent",
        "period": "day",
        "start": "2026-04-01T00:00:00.000Z",
        "end": "2026-04-10T23:59:59.000Z",
    })
    resp = handler(event, None)

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["metric"] == "messages_sent"
    assert data["period"] == "day"

    # Should have 2 days with outbound messages: April 1 (2 msgs) and April 2 (1 msg)
    points = data["data"]
    assert len(points) == 2
    assert points[0]["timestamp"] == "2026-04-01T00:00:00.000Z"
    assert points[0]["value"] == 2
    assert points[1]["timestamp"] == "2026-04-02T00:00:00.000Z"
    assert points[1]["value"] == 1


def test_metrics_query_received(aws_env):
    """Test querying messages_received metric."""
    _seed_messages(aws_env)

    event = _make_event("POST", "/metrics/query", body={
        "metric": "messages_received",
        "period": "day",
        "start": "2026-04-01T00:00:00.000Z",
        "end": "2026-04-10T23:59:59.000Z",
    })
    resp = handler(event, None)

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    points = data["data"]
    assert len(points) == 1
    assert points[0]["timestamp"] == "2026-04-02T00:00:00.000Z"
    assert points[0]["value"] == 1


def test_metrics_query_group_by(aws_env):
    """Test querying with group_by returns grouped data."""
    _seed_messages(aws_env)

    event = _make_event("POST", "/metrics/query", body={
        "metric": "messages_sent",
        "period": "day",
        "start": "2026-04-01T00:00:00.000Z",
        "end": "2026-04-10T23:59:59.000Z",
        "group_by": "inbox_id",
    })
    resp = handler(event, None)

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    grouped = data["data"]
    assert INBOX_ID in grouped
    assert len(grouped[INBOX_ID]) == 2  # 2 days with outbound messages


def test_metrics_query_invalid_metric(aws_env):
    """Test invalid metric returns 400."""
    event = _make_event("POST", "/metrics/query", body={
        "metric": "invalid_metric",
        "period": "day",
    })
    resp = handler(event, None)
    assert resp["statusCode"] == 400


def test_metrics_query_invalid_period(aws_env):
    """Test invalid period returns 400."""
    event = _make_event("POST", "/metrics/query", body={
        "metric": "messages_sent",
        "period": "invalid_period",
    })
    resp = handler(event, None)
    assert resp["statusCode"] == 400
