"""Tests for the Webhooks Lambda handler."""

import json

from webhooks.handler import handler


ORG_ID = "org_test123"


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


def test_create_webhook(aws_env):
    """Test creating a new webhook."""
    event = _make_event(
        "POST",
        path="/webhooks",
        body={
            "url": "https://example.com/webhook",
            "events": ["message.received", "message.sent"],
        },
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 201

    data = json.loads(resp["body"])
    assert data["url"] == "https://example.com/webhook"
    assert data["events"] == ["message.received", "message.sent"]
    assert data["secret"].startswith("whsec_")
    assert len(data["secret"]) == 6 + 64  # "whsec_" + 64 hex chars
    assert data["status"] == "active"
    assert data["delivery_stats"]["total"] == 0


def test_create_webhook_invalid_event(aws_env):
    """Test creating a webhook with invalid event type."""
    event = _make_event(
        "POST",
        path="/webhooks",
        body={
            "url": "https://example.com/webhook",
            "events": ["message.received", "invalid.event"],
        },
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 400

    data = json.loads(resp["body"])
    assert "invalid.event" in data["error"]["message"]


def test_create_webhook_missing_fields(aws_env):
    """Test creating a webhook with missing required fields."""
    event = _make_event("POST", path="/webhooks", body={"url": "https://example.com"})
    resp = handler(event, None)
    assert resp["statusCode"] == 400


def test_list_webhooks(aws_env):
    """Test listing webhooks."""
    # Create two
    for url in ["https://a.com/hook", "https://b.com/hook"]:
        handler(
            _make_event(
                "POST", path="/webhooks",
                body={"url": url, "events": ["message.received"]},
            ),
            None,
        )

    resp = handler(_make_event("GET", path="/webhooks"), None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert len(data["data"]) == 2


def test_get_webhook(aws_env):
    """Test getting a single webhook."""
    create_resp = handler(
        _make_event(
            "POST", path="/webhooks",
            body={"url": "https://get.com/hook", "events": ["message.sent"]},
        ),
        None,
    )
    webhook = json.loads(create_resp["body"])
    webhook_id = webhook["id"]

    get_event = _make_event(
        "GET",
        path=f"/webhooks/{webhook_id}",
        path_params={"id": webhook_id},
    )
    resp = handler(get_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["url"] == "https://get.com/hook"


def test_update_webhook(aws_env):
    """Test updating a webhook."""
    create_resp = handler(
        _make_event(
            "POST", path="/webhooks",
            body={"url": "https://old.com/hook", "events": ["message.received"]},
        ),
        None,
    )
    webhook = json.loads(create_resp["body"])
    webhook_id = webhook["id"]

    patch_event = _make_event(
        "PATCH",
        path=f"/webhooks/{webhook_id}",
        path_params={"id": webhook_id},
        body={"url": "https://new.com/hook", "status": "paused"},
    )
    resp = handler(patch_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["url"] == "https://new.com/hook"
    assert data["status"] == "paused"


def test_delete_webhook(aws_env):
    """Test hard deleting a webhook."""
    create_resp = handler(
        _make_event(
            "POST", path="/webhooks",
            body={"url": "https://del.com/hook", "events": ["message.received"]},
        ),
        None,
    )
    webhook = json.loads(create_resp["body"])
    webhook_id = webhook["id"]

    delete_event = _make_event(
        "DELETE",
        path=f"/webhooks/{webhook_id}",
        path_params={"id": webhook_id},
    )
    resp = handler(delete_event, None)
    assert resp["statusCode"] == 204

    # Verify gone
    get_event = _make_event("GET", path=f"/webhooks/{webhook_id}", path_params={"id": webhook_id})
    resp = handler(get_event, None)
    assert resp["statusCode"] == 404


def test_update_webhook_invalid_events(aws_env):
    """Test updating a webhook with invalid events."""
    create_resp = handler(
        _make_event(
            "POST", path="/webhooks",
            body={"url": "https://x.com/hook", "events": ["message.received"]},
        ),
        None,
    )
    webhook = json.loads(create_resp["body"])
    webhook_id = webhook["id"]

    patch_event = _make_event(
        "PATCH",
        path=f"/webhooks/{webhook_id}",
        path_params={"id": webhook_id},
        body={"events": ["bad.event"]},
    )
    resp = handler(patch_event, None)
    assert resp["statusCode"] == 400
