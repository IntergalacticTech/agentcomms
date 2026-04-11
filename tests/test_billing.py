"""Tests for the billing Lambda handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from shared.dynamo import get_item, put_item
from shared.models import now_iso, org_keys


def _make_event(org_id, method="GET", path="/billing/status", body=None, headers=None):
    event = {
        "httpMethod": method,
        "path": path,
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
                "key_id": "key_001",
                "scope": "org",
                "scope_resource_id": org_id,
            }
        },
    }
    if body is not None:
        event["body"] = json.dumps(body) if isinstance(body, dict) else body
    if headers is not None:
        event["headers"] = headers
    return event


def _make_webhook_event(body, sig="test_sig"):
    return {
        "httpMethod": "POST",
        "path": "/billing/webhook",
        "body": body,
        "headers": {"Stripe-Signature": sig},
        "requestContext": {},
    }


def _seed_org(org_id, tier="free", email="test@example.com", **extra):
    now = now_iso()
    keys = org_keys(org_id)
    item = {
        **keys,
        "id": org_id,
        "name": "Test Org",
        "email": email,
        "tier": tier,
        "status": "active",
        "billing_status": "none",
        "settings": {},
        "quotas": {"max_inboxes": 5},
        "usage": {},
        "created_at": now,
        "updated_at": now,
        **extra,
    }
    put_item(item)
    return item


class TestBillingStatus:
    """Tests for GET /billing/status."""

    def test_billing_status_returns_org_tier(self, aws_env):
        from billing.handler import handler

        org_id = "org_billing_001"
        _seed_org(org_id, tier="free")

        result = handler(_make_event(org_id), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["org_id"] == org_id
        assert body["tier"] == "free"
        assert body["billing_status"] == "none"
        assert body["stripe_customer_id"] is None

    def test_billing_status_pro_tier(self, aws_env):
        from billing.handler import handler

        org_id = "org_billing_002"
        _seed_org(org_id, tier="pro", stripe_customer_id="cus_123", billing_status="active")

        result = handler(_make_event(org_id), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["tier"] == "pro"
        assert body["billing_status"] == "active"
        assert body["stripe_customer_id"] == "cus_123"

    def test_billing_status_no_auth(self, aws_env):
        from billing.handler import handler

        result = handler(_make_event(""), None)

        assert result["statusCode"] == 401


class TestCheckout:
    """Tests for POST /billing/checkout."""

    def test_checkout_requires_auth(self, aws_env):
        from billing.handler import handler

        event = _make_event("", method="POST", path="/billing/checkout")
        result = handler(event, None)

        assert result["statusCode"] == 401

    @patch("billing.handler.stripe")
    def test_checkout_creates_session(self, mock_stripe, aws_env):
        from billing.handler import handler

        org_id = "org_checkout_001"
        _seed_org(org_id)

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test_session"
        mock_stripe.checkout.Session.create.return_value = mock_session

        event = _make_event(org_id, method="POST", path="/billing/checkout")
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["checkout_url"] == "https://checkout.stripe.com/test_session"
        mock_stripe.checkout.Session.create.assert_called_once()

    def test_checkout_org_not_found(self, aws_env):
        from billing.handler import handler

        event = _make_event("org_nonexistent", method="POST", path="/billing/checkout")
        result = handler(event, None)

        assert result["statusCode"] == 404


class TestWebhook:
    """Tests for POST /billing/webhook."""

    @patch("billing.handler.stripe")
    def test_webhook_checkout_completed_upgrades_to_pro(self, mock_stripe, aws_env):
        from billing.handler import PRO_QUOTAS, handler

        org_id = "org_webhook_001"
        _seed_org(org_id)

        # Mock the webhook event construction
        mock_stripe.Webhook.construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_test_123",
                    "metadata": {"org_id": org_id},
                }
            },
        }
        mock_stripe.SignatureVerificationError = Exception

        event = _make_webhook_event('{"test": true}')
        result = handler(event, None)

        assert result["statusCode"] == 200

        # Verify org was upgraded
        keys = org_keys(org_id)
        org = get_item(keys["PK"], keys["SK"])
        assert org["tier"] == "pro"
        assert org["billing_status"] == "active"
        assert org["stripe_customer_id"] == "cus_test_123"
        assert org["billing_channel"] == "stripe"
        assert org["quotas"] == PRO_QUOTAS

    @patch("billing.handler.stripe")
    def test_webhook_subscription_deleted_downgrades(self, mock_stripe, aws_env):
        from billing.handler import FREE_QUOTAS, handler

        org_id = "org_webhook_002"
        _seed_org(org_id, tier="pro", stripe_customer_id="cus_test_456", billing_status="active")

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": "cus_test_456",
                }
            },
        }
        mock_stripe.SignatureVerificationError = Exception

        event = _make_webhook_event('{"test": true}')
        result = handler(event, None)

        assert result["statusCode"] == 200

        keys = org_keys(org_id)
        org = get_item(keys["PK"], keys["SK"])
        assert org["tier"] == "free"
        assert org["billing_status"] == "canceled"
        assert org["quotas"] == FREE_QUOTAS

    @patch("billing.handler.stripe")
    def test_webhook_payment_failed_sets_past_due(self, mock_stripe, aws_env):
        from billing.handler import handler

        org_id = "org_webhook_003"
        _seed_org(org_id, tier="pro", stripe_customer_id="cus_test_789", billing_status="active")

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": "cus_test_789",
                }
            },
        }
        mock_stripe.SignatureVerificationError = Exception

        event = _make_webhook_event('{"test": true}')
        result = handler(event, None)

        assert result["statusCode"] == 200

        keys = org_keys(org_id)
        org = get_item(keys["PK"], keys["SK"])
        assert org["billing_status"] == "past_due"

    @patch("billing.handler.stripe")
    def test_webhook_invalid_signature(self, mock_stripe, aws_env):
        import stripe as stripe_mod

        from billing.handler import handler

        mock_stripe.SignatureVerificationError = stripe_mod.SignatureVerificationError
        mock_stripe.Webhook.construct_event.side_effect = (
            stripe_mod.SignatureVerificationError("bad sig", "sig")
        )

        event = _make_webhook_event('{"test": true}')
        result = handler(event, None)

        assert result["statusCode"] == 401
