"""Tests for the webhook delivery worker."""

import hashlib
import hmac
import json
from unittest.mock import patch, MagicMock

import pytest

from shared.dynamo import put_item
from shared.models import webhook_keys, webhook_gsi1, now_iso
from webhook_worker.handler import handler, deliver


@pytest.fixture
def seed_webhook(aws_env):
    """Seed an active webhook in DynamoDB."""
    def _seed(
        org_id="org_test",
        webhook_id="wh_001",
        url="https://example.com/hook",
        events=None,
        secret="whsec_testsecret",
        status="active",
        wh_filter=None,
    ):
        if events is None:
            events = ["message.received", "message.sent"]
        item = {
            **webhook_keys(org_id, webhook_id),
            **webhook_gsi1(org_id, webhook_id),
            "id": webhook_id,
            "org_id": org_id,
            "url": url,
            "events": events,
            "secret": secret,
            "status": status,
            "filter": wh_filter or {},
            "delivery_stats": {
                "total": 0,
                "success": 0,
                "failed": 0,
                "last_delivered_at": None,
                "last_failed_at": None,
            },
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        put_item(item)
        return item
    return _seed


def _sqs_event(event_type, org_id, data):
    """Build a minimal SQS event for the handler."""
    return {
        "Records": [
            {
                "body": json.dumps({
                    "event_type": event_type,
                    "org_id": org_id,
                    "data": data,
                })
            }
        ]
    }


class TestWebhookDelivery:
    """test_webhook_delivery - verify the worker processes an event and POSTs to the URL."""

    @patch("webhook_worker.handler.urllib.request.urlopen")
    def test_webhook_delivery(self, mock_urlopen, seed_webhook):
        seed_webhook(
            org_id="org_test",
            webhook_id="wh_001",
            url="https://example.com/hook",
            events=["message.received"],
            secret="whsec_testsecret",
        )

        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        sqs_event = _sqs_event("message.received", "org_test", {
            "message_id": "msg_001",
            "inbox_id": "inbox_001",
            "from": "sender@example.com",
            "subject": "Hello",
            "received_at": "2026-04-11T00:00:00Z",
        })

        handler(sqs_event, None)

        # Verify urlopen was called
        assert mock_urlopen.call_count == 1
        call_args = mock_urlopen.call_args
        req = call_args[0][0]

        assert req.full_url == "https://example.com/hook"
        assert req.get_header("Content-type") == "application/json"
        assert req.get_header("X-freemail-event") == "message.received"
        assert req.get_header("X-freemail-signature").startswith("sha256=")

        # Verify payload structure
        sent_payload = json.loads(req.data.decode())
        assert sent_payload["event"] == "message.received"
        assert sent_payload["data"]["message_id"] == "msg_001"
        assert "timestamp" in sent_payload


class TestWebhookFilters:
    """test_webhook_filters_events - verify events are filtered correctly."""

    @patch("webhook_worker.handler.urllib.request.urlopen")
    def test_webhook_filters_events(self, mock_urlopen, seed_webhook):
        # Webhook only subscribes to message.sent
        seed_webhook(
            org_id="org_test",
            webhook_id="wh_002",
            events=["message.sent"],
        )

        sqs_event = _sqs_event("message.received", "org_test", {
            "message_id": "msg_001",
            "inbox_id": "inbox_001",
        })

        handler(sqs_event, None)

        # Should NOT have called urlopen since the event type doesn't match
        assert mock_urlopen.call_count == 0

    @patch("webhook_worker.handler.urllib.request.urlopen")
    def test_webhook_filters_inactive(self, mock_urlopen, seed_webhook):
        seed_webhook(
            org_id="org_test",
            webhook_id="wh_003",
            events=["message.received"],
            status="inactive",
        )

        sqs_event = _sqs_event("message.received", "org_test", {
            "message_id": "msg_001",
        })

        handler(sqs_event, None)
        assert mock_urlopen.call_count == 0

    @patch("webhook_worker.handler.urllib.request.urlopen")
    def test_webhook_filters_inbox_ids(self, mock_urlopen, seed_webhook):
        seed_webhook(
            org_id="org_test",
            webhook_id="wh_004",
            events=["message.received"],
            wh_filter={"inbox_ids": ["inbox_999"]},
        )

        sqs_event = _sqs_event("message.received", "org_test", {
            "message_id": "msg_001",
            "inbox_id": "inbox_001",
        })

        handler(sqs_event, None)
        assert mock_urlopen.call_count == 0


class TestWebhookSignature:
    """test_webhook_signature - verify HMAC signature computation."""

    def test_webhook_signature(self, aws_env):
        secret = "whsec_testsecret123"
        event_type = "message.received"
        data = {"message_id": "msg_001", "inbox_id": "inbox_001"}

        # We'll call deliver directly and capture the request
        webhook = {
            "id": "wh_sig",
            "org_id": "org_test",
            "url": "https://example.com/hook",
            "secret": secret,
            "status": "active",
            "events": [event_type],
            "filter": {},
            "delivery_stats": {
                "total": 0, "success": 0, "failed": 0,
                "last_delivered_at": None, "last_failed_at": None,
            },
        }
        # Seed the webhook so _update_stats works
        put_item({
            **webhook_keys("org_test", "wh_sig"),
            **webhook_gsi1("org_test", "wh_sig"),
            **webhook,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })

        with patch("webhook_worker.handler.urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            deliver(webhook, event_type, data)

            req = mock_urlopen.call_args[0][0]
            payload_bytes = req.data
            payload_json = payload_bytes.decode()

            # Compute expected signature
            expected_sig = hmac.new(
                secret.encode(), payload_json.encode(), hashlib.sha256
            ).hexdigest()

            actual_sig = req.get_header("X-freemail-signature")
            assert actual_sig == f"sha256={expected_sig}"

            # Verify the payload is valid JSON with expected fields
            payload = json.loads(payload_json)
            assert payload["event"] == event_type
            assert payload["data"] == data
