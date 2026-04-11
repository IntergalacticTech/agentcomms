"""Tests for the AI Lambda handler."""

import io
import json
from unittest.mock import patch, MagicMock

from shared.dynamo import put_item
from shared.models import org_keys, message_keys, now_iso
from shared.s3 import store_body
from ai.handler import handler

ORG_ID = "org_test123"
INBOX_ID = "inbox_test456"
MESSAGE_ID = "msg_test789"


def _seed_org(tier="pro"):
    """Seed a test organization."""
    keys = org_keys(ORG_ID)
    put_item({
        **keys,
        "id": ORG_ID,
        "name": "Test Org",
        "tier": tier,
        "created_at": now_iso(),
    })


def _seed_message():
    """Seed a test message and body in S3."""
    now = now_iso()
    s3_key = store_body(ORG_ID, INBOX_ID, MESSAGE_ID,
                        body_text="Hello, I want to place an order for Widget A and Widget B. Order ID: ORD-12345. Total: $99.99. Thanks, Jane Doe.",
                        body_html=None)
    keys = message_keys(INBOX_ID, MESSAGE_ID)
    put_item({
        **keys,
        "id": MESSAGE_ID,
        "inbox_id": INBOX_ID,
        "org_id": ORG_ID,
        "subject": "New Order Request",
        "body_s3_key": s3_key,
        "direction": "inbound",
        "from_addr": "jane@example.com",
        "to": ["sales@example.com"],
        "created_at": now,
    })


def _make_event(path, body):
    return {
        "httpMethod": "POST",
        "path": path,
        "pathParameters": {},
        "body": json.dumps(body),
        "requestContext": {
            "authorizer": {"org_id": ORG_ID},
        },
    }


def _mock_bedrock_response(text):
    """Create a mock Bedrock invoke_model response."""
    body_bytes = json.dumps({
        "content": [{"text": text}],
        "stop_reason": "end_turn",
    }).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_bytes
    return {"body": mock_body}


def test_categorize_requires_pro(aws_env):
    """Verify that free-tier orgs get a 403 for categorize."""
    _seed_org(tier="free")
    _seed_message()

    event = _make_event("/ai/categorize", {
        "message_id": MESSAGE_ID,
        "inbox_id": INBOX_ID,
        "categories": ["sales", "support", "billing"],
    })
    resp = handler(event, None)
    assert resp["statusCode"] == 403
    data = json.loads(resp["body"])
    assert "Pro" in data["error"]["message"]


def test_categorize_works_for_pro(aws_env):
    """Verify categorize works for pro-tier orgs with mocked Bedrock."""
    _seed_org(tier="pro")
    _seed_message()

    event = _make_event("/ai/categorize", {
        "message_id": MESSAGE_ID,
        "inbox_id": INBOX_ID,
        "categories": ["sales", "support", "billing", "other"],
    })

    mock_client = MagicMock()
    mock_client.invoke_model.return_value = _mock_bedrock_response("sales")

    with patch("ai.handler._bedrock", mock_client):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["message_id"] == MESSAGE_ID
    assert data["category"] == "sales"

    # Verify the invoke_model call
    mock_client.invoke_model.assert_called_once()
    call_kwargs = mock_client.invoke_model.call_args[1]
    assert call_kwargs["modelId"] == "anthropic.claude-3-haiku-20240307-v1:0"


def test_extract_works_for_pro(aws_env):
    """Verify extract works for pro-tier orgs with mocked Bedrock."""
    _seed_org(tier="pro")
    _seed_message()

    schema = {
        "order_id": "string",
        "customer_name": "string",
        "total": "number",
        "items": ["string"],
    }

    event = _make_event("/ai/extract", {
        "message_id": MESSAGE_ID,
        "inbox_id": INBOX_ID,
        "schema": schema,
    })

    extracted = {
        "order_id": "ORD-12345",
        "customer_name": "Jane Doe",
        "total": 99.99,
        "items": ["Widget A", "Widget B"],
    }
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = _mock_bedrock_response(json.dumps(extracted))

    with patch("ai.handler._bedrock", mock_client):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["message_id"] == MESSAGE_ID
    assert data["extracted"]["order_id"] == "ORD-12345"
    assert data["extracted"]["customer_name"] == "Jane Doe"
    assert data["extracted"]["total"] == 99.99
    assert data["extracted"]["items"] == ["Widget A", "Widget B"]


def test_summarize_works_for_pro(aws_env):
    """Verify summarize works for pro-tier orgs with mocked Bedrock."""
    _seed_org(tier="pro")
    _seed_message()

    event = _make_event("/ai/summarize", {
        "message_id": MESSAGE_ID,
        "inbox_id": INBOX_ID,
    })

    summary_text = "Jane Doe is requesting to place an order for Widget A and Widget B with order ID ORD-12345 totaling $99.99."
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = _mock_bedrock_response(summary_text)

    with patch("ai.handler._bedrock", mock_client):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["message_id"] == MESSAGE_ID
    assert "Jane Doe" in data["summary"]
    assert "ORD-12345" in data["summary"]
