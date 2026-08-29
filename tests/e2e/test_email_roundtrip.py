# tests/e2e/test_email_roundtrip.py
"""
End-to-end integration test — round-trip email via moto.

Exercises the full Phase 1 surface (provision → receive → send → list)
entirely against moto-backed AWS (no live calls).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixture: ensure a fresh adapter singleton for each test run.
# The ingest module caches _adapter at import time; we reload to pick up
# the moto-backed DynamoDB table that is created fresh per test.
# ---------------------------------------------------------------------------

FIXTURE_DIR = (
    pathlib.Path(__file__).parent.parent.parent
    / "adapters" / "email" / "tests" / "fixtures"
)
INBOUND_EML = FIXTURE_DIR / "inbound_simple.eml"

# The inbound_simple.eml recipient is bot@agentcomms.dev
AGENT_LOCAL = "bot"
AGENT_DOMAIN = "agentcomms.dev"
AGENT_ADDRESS = f"{AGENT_LOCAL}@{AGENT_DOMAIN}"

SES_MSG_ID = "test-ses-msg-001"


def _apigw_event(
    method: str,
    path: str,
    body: dict | None = None,
    path_params: dict | None = None,
    org_id: str = "org_test",
    qs: dict | None = None,
) -> dict:
    """Build a minimal API Gateway proxy event with a pre-authenticated context."""
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": qs or {},
        "headers": {},
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
                "scope": "org",
                "api_key_id": "key_test",
            }
        },
    }


def _sns_record(ses_message_id: str) -> dict:
    """Synthesize an SNS-wrapped SES inbound notification."""
    ses_notification = {
        "notificationType": "Received",
        "mail": {
            "messageId": ses_message_id,
            "source": "alice@example.com",
            "destination": [AGENT_ADDRESS],
        },
        "receipt": {
            "action": {"type": "SNS", "topicArn": "arn:aws:sns:us-east-1:123:test"},
        },
    }
    return {
        "EventSource": "aws:sns",
        "Sns": {
            "MessageId": "sns-001",
            "Message": json.dumps(ses_notification),
            "TopicArn": "arn:aws:sns:us-east-1:123:test",
        },
    }


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def test_email_roundtrip(agentcomms_table, s3_buckets, ses_client):
    """
    Full Phase 1 round-trip:
    1. Provision agent with email channel.
    2. Simulate inbound SES email.
    3. Verify inbound message appears in unified inbox.
    4. Send outbound reply.
    5. Verify both messages appear in unified inbox.
    """
    import boto3

    # ── Reset module-level singletons that may have been cached by earlier tests ──
    import importlib

    # Reload ingest so its _adapter picks up the live moto table
    import adapters.email.ingest as ingest_mod
    import adapters.email.adapter as adapter_mod
    import core.api.agents_handler as agents_mod
    import core.api.messages_handler as messages_mod

    # Force adapter singleton to re-read env / table on next call
    ingest_mod._adapter = adapter_mod.EmailAdapter()
    ingest_mod._blob_store = None
    ingest_mod._event_publisher = None

    # Also reset handler-level registry caches so they resolve the moto table
    agents_mod._REGISTRY = None
    messages_mod._REGISTRY = None

    # ── 1. Provision Agent + email channel ──────────────────────────────────
    event_create = _apigw_event(
        method="POST",
        path="/v1/agents",
        body={
            "name": "roundtrip-bot",
            "provision": {
                "email": {"local_part": AGENT_LOCAL, "domain": AGENT_DOMAIN}
            },
        },
    )

    # SES verify_domain_dkim works fine under moto; response may return
    # "pending_verification" status. Patch to force "active" so send works.
    with patch.object(adapter_mod.EmailAdapter, "provision", wraps=None) as mock_prov:
        from core.adapters.base import ProvisionResult
        from core.data.ulid_ import new_id

        channel_id = new_id("chan", suffix="em")
        mock_prov.return_value = ProvisionResult(
            status="active",
            channel_id=channel_id,
            details={
                "address": AGENT_ADDRESS,
                "domain": AGENT_DOMAIN,
                "dkim_tokens": [],
                "dkim_verified": False,
            },
        )
        resp_create = agents_mod.handler(event_create, None)

    assert resp_create["statusCode"] == 201, resp_create["body"]
    body_create = json.loads(resp_create["body"])
    agent_id = body_create["agent_id"]
    channels = body_create["channels"]
    assert len(channels) == 1
    assert channels[0]["channel"] == "email"

    # ── 2. Simulate SES inbound: put .eml in S3 + invoke ingest handler ──────
    raw_eml = INBOUND_EML.read_bytes()
    s3 = boto3.client("s3", region_name="us-east-1")
    raw_bucket = s3_buckets["raw_inbound"]
    s3.put_object(Bucket=raw_bucket, Key=f"inbound/{SES_MSG_ID}", Body=raw_eml)

    # Env var must point to the moto bucket (fixture already sets it, but be explicit)
    os.environ["AGENTCOMMS_BUCKET_RAW_INBOUND"] = raw_bucket
    os.environ["AGENTCOMMS_RAW_INBOUND_PREFIX"] = "inbound/"

    sns_event = {"Records": [_sns_record(SES_MSG_ID)]}

    # Patch EmailAdapter.send to avoid real SES on outbound (not needed here,
    # but guard against side effects from adapter warm-up)
    ingest_result = ingest_mod.handler(sns_event, None)
    assert ingest_result["processed"] == 1, f"ingest did not process: {ingest_result}"

    # ── 3. GET /v1/agents/{id}/messages — expect 1 inbound message ───────────
    event_get1 = _apigw_event(
        method="GET",
        path=f"/v1/agents/{agent_id}/messages",
        path_params={"agent_id": agent_id},
    )
    resp_get1 = messages_mod.handler(event_get1, None)
    assert resp_get1["statusCode"] == 200, resp_get1["body"]
    body_get1 = json.loads(resp_get1["body"])
    msgs1 = body_get1["messages"]
    assert len(msgs1) == 1, f"expected 1 message, got {len(msgs1)}: {msgs1}"
    assert msgs1[0]["is_dm"] is True
    assert msgs1[0]["channel"] == "email"
    assert msgs1[0]["direction"] == "inbound"

    # ── 4. POST /v1/agents/{id}/messages — send reply ────────────────────────
    event_send = _apigw_event(
        method="POST",
        path=f"/v1/agents/{agent_id}/messages",
        path_params={"agent_id": agent_id},
        body={"to": "alice@example.com", "body": "reply"},
    )

    # Mock EmailAdapter.send to avoid real SES SendRawEmail (moto doesn't have
    # the domain verified so it would fail)
    from core.adapters.base import SendResult

    with patch.object(adapter_mod.EmailAdapter, "send") as mock_send:
        mock_send.return_value = SendResult(
            channel_native_id="mock-ses-msg-id", status="sent"
        )
        resp_send = messages_mod.handler(event_send, None)

    assert resp_send["statusCode"] == 201, resp_send["body"]
    body_send = json.loads(resp_send["body"])
    assert body_send["status"] == "sent"

    # ── 5. GET /v1/agents/{id}/messages again — expect 2 messages ───────────
    resp_get2 = messages_mod.handler(event_get1, None)
    assert resp_get2["statusCode"] == 200, resp_get2["body"]
    body_get2 = json.loads(resp_get2["body"])
    msgs2 = body_get2["messages"]
    assert len(msgs2) == 2, f"expected 2 messages, got {len(msgs2)}: {msgs2}"
    # Both must be DMs
    assert all(m["is_dm"] for m in msgs2), "all messages should be is_dm=True"
    # Both must be email channel
    assert all(m["channel"] == "email" for m in msgs2)
    # One inbound, one outbound
    directions = {m["direction"] for m in msgs2}
    assert directions == {"inbound", "outbound"}, f"unexpected directions: {directions}"
