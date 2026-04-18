# tests/e2e/test_phase2_roundtrip.py
"""
End-to-end Phase 2 integration test.

Exercises the full Phase 2 surface in one test function against moto +
patched adapter/AI clients.

Steps:
  1. Provision agent with email + sms + push.
  2. Inbound SMS → unified inbox.
  3. Unified inbox query.
  4. Create persona + associate with agent.
  5. Create TOTP vault entry; fetch current code.
  6. Register custom domain (patched SES v2).
  7. AI categorize via patched Bedrock.
  8. Register push device + send push notification.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helper: build minimal API Gateway proxy event with pre-authorised context.
# ---------------------------------------------------------------------------

def _apigw_event(
    method: str,
    path: str,
    body: dict | None = None,
    path_params: dict | None = None,
    org_id: str = "org_test",
    qs: dict | None = None,
) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": qs or {},
        "headers": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
                "scope": "org",
                "api_key_id": "key_test",
            }
        },
    }


# ---------------------------------------------------------------------------
# Main E2E test
# ---------------------------------------------------------------------------

def test_phase2_roundtrip(agentcomms_table, s3_buckets, ses_client, kms_key):
    """Full Phase 2 round-trip: 9 steps, ≥18 assertions."""

    # ── Reset module-level singletons ───────────────────────────────────────
    import core.api.agents_handler as agents_mod
    import core.api.messages_handler as messages_mod
    import core.api.personas_handler as personas_mod
    import core.api.vault_handler as vault_mod
    import core.api.domains_handler as domains_mod
    import core.api.ai_handler as ai_mod
    import core.api.push_native_handler as push_native_mod

    import adapters.sms.adapter as sms_adapter_mod
    import adapters.sms.ingest as sms_ingest_mod
    import adapters.email.adapter as email_adapter_mod
    import adapters.push.adapter as push_adapter_mod

    # Reset registry caches so they see the live moto table.
    agents_mod._REGISTRY = None
    messages_mod._REGISTRY = None

    # Reset SMS ingest singleton so it picks up the live table.
    sms_ingest_mod._adapter = sms_adapter_mod.SmsAdapter()

    # Reset domains SESv2 singleton so moto handles calls.
    domains_mod._sesv2 = None

    # Reset bedrock singleton to avoid stale clients from other tests.
    import core.ai.bedrock_client as bedrock_mod
    bedrock_mod._bedrock = None

    # ── Canned ProvisionResults ─────────────────────────────────────────────
    from core.adapters.base import ProvisionResult, SendResult
    from core.data.ulid_ import new_id

    sms_phone = "+18005550042"

    email_channel_id = new_id("chan", suffix="em")
    sms_channel_id = new_id("chan", suffix="sm")
    push_channel_id = new_id("chan", suffix="pu")

    email_prov_result = ProvisionResult(
        status="active",
        channel_id=email_channel_id,
        details={
            "address": "multibot@agentcomms.dev",
            "domain": "agentcomms.dev",
            "dkim_tokens": [],
            "dkim_verified": False,
        },
    )
    sms_prov_result = ProvisionResult(
        status="provisioning",
        channel_id=sms_channel_id,
        details={
            "phone_e164": sms_phone,
            "phone_number_id": "pn-001",
            "phone_number_arn": "arn:aws:sms-voice:us-east-1:123:phone-number/pn-001",
            "ten_dlc_status": "pending_brand_registration",
            "ten_dlc_brand_id": "",
            "ten_dlc_campaign_id": "",
            "aws_status": "PENDING",
            "country": "US",
        },
    )
    push_prov_result = ProvisionResult(
        status="active",
        channel_id=push_channel_id,
        details={
            "platform_application_arns": {
                "apns": "arn:aws:sns:us-east-1:123:app/APNS/test-apns",
                "fcm": "arn:aws:sns:us-east-1:123:app/GCM/test-fcm",
            }
        },
    )

    # ── Step 1: Provision agent with email + sms + push ──────────────────────
    with (
        patch.object(email_adapter_mod.EmailAdapter, "provision", return_value=email_prov_result),
        patch.object(sms_adapter_mod.SmsAdapter, "provision", return_value=sms_prov_result),
        patch.object(push_adapter_mod.PushAdapter, "provision", return_value=push_prov_result),
    ):
        resp_create = agents_mod.handler(
            _apigw_event(
                "POST",
                "/v1/agents",
                body={
                    "name": "multibot",
                    "provision": {
                        "email": {"local_part": "multibot", "domain": "agentcomms.dev"},
                        "sms": {"country": "US"},
                        "push": True,
                    },
                },
            ),
            None,
        )

    assert resp_create["statusCode"] == 201, f"Step1 create failed: {resp_create['body']}"
    body_create = json.loads(resp_create["body"])
    agent_id = body_create["agent_id"]
    channels = body_create["channels"]
    # 3 channels must be present
    assert len(channels) == 3, f"Expected 3 channels, got {len(channels)}: {channels}"
    channel_types = {c["channel"] for c in channels}
    assert channel_types == {"email", "sms", "push"}, f"Unexpected channel types: {channel_types}"
    # Email is active; SMS is provisioning; push is active
    ch_by_type = {c["channel"]: c for c in channels}
    assert ch_by_type["email"]["status"] == "active"
    assert ch_by_type["sms"]["status"] == "provisioning"
    assert ch_by_type["push"]["status"] == "active"

    # ── Step 2: Inbound SMS via synthesised SNS event ────────────────────────
    # We need a channel with a GSI2 address index so ingest can route the SMS.
    # The agents_handler wrote the sms channel via repo.put_channel which sets
    # gsi2_pk only if address_index_value is set.  The mocked provision result
    # doesn't set an email-style address_index_value for SMS.  We must patch
    # the channel directly into DynamoDB with the address index so the SMS
    # ingest lookup works.
    import boto3
    from core.data.models import Channel, ChannelType, ChannelMode, ChannelStatus
    from core.data.repo import Repo
    from datetime import datetime, timezone

    repo = Repo(agentcomms_table)

    # Overwrite SMS channel record with address_index_value set.
    sms_channel = Channel(
        channel_id=sms_channel_id,
        agent_id=agent_id,
        org_id="org_test",
        channel=ChannelType.SMS,
        mode=ChannelMode.PROVISION,
        config={
            "phone_e164": sms_phone,
            "phone_number_id": "pn-001",
            "phone_number_arn": "arn:aws:sms-voice:us-east-1:123:phone-number/pn-001",
        },
        status=ChannelStatus.PROVISIONING,
        address_index_value=sms_phone,
    )
    repo.put_channel(sms_channel)

    # Build SNS inbound SMS event with the destination phone matching the channel.
    import json as _json

    inner_sms = {
        "originationNumber": "+14155551234",
        "destinationNumber": sms_phone,
        "messageBody": "Hello from test",
        "messageId": "inbound-msg-001",
        "inboundMessageId": "inbound-def-001",
        "previousPublishedMessageId": None,
        "messageKeyword": "KEYWORD",
        "messageSegmentCount": 1,
        "originationCountryIso": "US",
        "carrierCode": "310410",
        "timestamp": "2026-04-17T12:00:00.000Z",
    }
    sns_event = {
        "Records": [
            {
                "EventSource": "aws:sns",
                "EventVersion": "1.0",
                "EventSubscriptionArn": "arn:aws:sns:us-east-1:123:agentcomms-sms-inbound:abc",
                "Sns": {
                    "Type": "Notification",
                    "MessageId": "sns-msg-test-001",
                    "TopicArn": "arn:aws:sns:us-east-1:123:agentcomms-sms-inbound",
                    "Subject": None,
                    "Message": _json.dumps(inner_sms),
                    "Timestamp": "2026-04-17T12:00:00.000Z",
                    "SignatureVersion": "1",
                    "Signature": "FAKE",
                    "SigningCertUrl": "https://sns.us-east-1.amazonaws.com/cert.pem",
                    "UnsubscribeUrl": "https://sns.us-east-1.amazonaws.com/?Action=Unsubscribe",
                    "MessageAttributes": {},
                },
            }
        ]
    }

    ingest_result = sms_ingest_mod.handler(sns_event, None)
    assert ingest_result["processed"] == 1, f"SMS ingest failed: {ingest_result}"

    # ── Step 3: Unified inbox query after inbound SMS ─────────────────────────
    resp_inbox = messages_mod.handler(
        _apigw_event(
            "GET",
            f"/v1/agents/{agent_id}/messages",
            path_params={"agent_id": agent_id},
        ),
        None,
    )
    assert resp_inbox["statusCode"] == 200, f"Step3 inbox failed: {resp_inbox['body']}"
    inbox_body = json.loads(resp_inbox["body"])
    msgs = inbox_body["messages"]
    assert len(msgs) == 1, f"Expected 1 message in inbox, got {len(msgs)}"
    assert msgs[0]["is_dm"] is True
    assert msgs[0]["channel"] == "sms"
    assert msgs[0]["direction"] == "inbound"
    sms_message_id = msgs[0]["message_id"]

    # ── Step 4: Create persona + associate with agent ─────────────────────────
    resp_persona_create = personas_mod.handler(
        _apigw_event(
            "POST",
            "/v1/personas",
            body={"name": "Alice Test", "email": "alice@example.com", "metadata": {}},
        ),
        None,
    )
    assert resp_persona_create["statusCode"] == 201, (
        f"Step4 persona create failed: {resp_persona_create['body']}"
    )
    persona_body = json.loads(resp_persona_create["body"])
    persona_id = persona_body["persona_id"]
    assert persona_body["name"] == "Alice Test"
    assert persona_body["email"] == "alice@example.com"

    # Associate persona with agent
    resp_assoc = personas_mod.handler(
        _apigw_event(
            "POST",
            f"/v1/agents/{agent_id}/personas",
            path_params={"agent_id": agent_id},
            body={"persona_id": persona_id},
        ),
        None,
    )
    assert resp_assoc["statusCode"] == 200, f"Step4 associate failed: {resp_assoc['body']}"
    assoc_body = json.loads(resp_assoc["body"])
    assert assoc_body["metadata"]["persona_id"] == persona_id

    # ── Step 5: TOTP vault entry ──────────────────────────────────────────────
    totp_seed = "JBSWY3DPEHPK3PXP"
    resp_vault_create = vault_mod.handler(
        _apigw_event(
            "POST",
            "/v1/vault",
            body={
                "type": "totp",
                "label": "github-alice",
                "seed": totp_seed,
                "tags": {"persona_id": persona_id},
            },
        ),
        None,
    )
    assert resp_vault_create["statusCode"] == 201, (
        f"Step5 vault create failed: {resp_vault_create['body']}"
    )
    vault_body = json.loads(resp_vault_create["body"])
    vault_id = vault_body["vault_id"]
    assert vault_body["type"] == "totp"
    assert vault_body["label"] == "github-alice"

    # Fetch current TOTP code
    resp_totp = vault_mod.handler(
        _apigw_event(
            "GET",
            f"/v1/vault/{vault_id}/totp",
            path_params={"id": vault_id},
        ),
        None,
    )
    assert resp_totp["statusCode"] == 200, f"Step5 totp fetch failed: {resp_totp['body']}"
    totp_resp_body = json.loads(resp_totp["body"])
    code = totp_resp_body["code"]
    assert len(code) == 6 and code.isdigit(), f"Expected 6-digit code, got {code!r}"

    # Verify code matches pyotp reference
    import pyotp
    expected_code = pyotp.TOTP(totp_seed).now()
    assert code == expected_code, (
        f"TOTP code mismatch: got {code!r}, expected {expected_code!r}"
    )

    # ── Step 6: Register a custom domain ─────────────────────────────────────
    # Patch the SESv2 singleton in domains_handler to return DKIM tokens.
    mock_sesv2 = MagicMock()
    mock_sesv2.create_email_identity.return_value = {
        "DkimAttributes": {
            "Tokens": ["token1abc", "token2def", "token3ghi"],
            "SigningAttributesOrigin": "AWS_SES",
        },
        "VerifiedForSendingStatus": False,
    }
    # Need exceptions.AlreadyExistsException to exist for the error handling path
    mock_sesv2.exceptions = MagicMock()
    mock_sesv2.exceptions.AlreadyExistsException = Exception

    domains_mod._sesv2 = mock_sesv2

    resp_domain = domains_mod.handler(
        _apigw_event(
            "POST",
            "/v1/domains",
            body={"domain_name": "testco.example"},
        ),
        None,
    )
    assert resp_domain["statusCode"] == 201, f"Step6 domain create failed: {resp_domain['body']}"
    domain_body = json.loads(resp_domain["body"])
    domain_id = domain_body["domain_id"]
    assert domain_body["domain_name"] == "testco.example"
    assert domain_body["status"] == "pending_dns"
    assert len(domain_body["dkim_tokens"]) == 3, (
        f"Expected 3 DKIM tokens, got: {domain_body['dkim_tokens']}"
    )

    # Reset sesv2 singleton so subsequent calls don't use the mock.
    domains_mod._sesv2 = None

    # ── Step 7: AI categorize via patched Bedrock ─────────────────────────────
    bedrock_response = {
        "content": [
            {
                "type": "tool_use",
                "name": "classify",
                "input": {"label": "urgent", "confidence": 0.95},
            }
        ]
    }

    with patch("core.ai.categorize.invoke_model", return_value=bedrock_response):
        resp_categorize = ai_mod.handler(
            _apigw_event(
                "POST",
                f"/v1/agents/{agent_id}/ai/categorize",
                path_params={"agent_id": agent_id},
                body={
                    "message_id": sms_message_id,
                    "labels": ["urgent", "normal", "spam"],
                },
            ),
            None,
        )

    assert resp_categorize["statusCode"] == 200, (
        f"Step7 AI categorize failed: {resp_categorize['body']}"
    )
    ai_body = json.loads(resp_categorize["body"])
    assert ai_body["label"] == "urgent"
    assert ai_body["confidence"] == 0.95

    # ── Step 8: Push — register device + send notification ───────────────────
    fake_endpoint_arn = "arn:aws:sns:us-east-1:123:endpoint/APNS/test-apns/device-abc123"

    with patch("adapters.push.devices._sns_client") as mock_sns_fn:
        mock_sns_client = MagicMock()
        mock_sns_fn.return_value = mock_sns_client
        mock_sns_client.create_platform_endpoint.return_value = {
            "EndpointArn": fake_endpoint_arn
        }

        resp_device = push_native_mod.handler(
            _apigw_event(
                "POST",
                f"/v1/agents/{agent_id}/push/devices",
                path_params={"agent_id": agent_id},
                body={"platform": "apns", "token": "abc123"},
            ),
            None,
        )

    assert resp_device["statusCode"] == 201, (
        f"Step8 device register failed: {resp_device['body']}"
    )
    device_body = json.loads(resp_device["body"])
    device_id = device_body["device_id"]
    assert device_body["endpoint_arn"] == fake_endpoint_arn
    assert device_body["platform"] == "apns"

    # Send push notification
    with (
        patch("adapters.push.adapter._sns_client") as mock_push_sns_fn,
    ):
        mock_push_sns = MagicMock()
        mock_push_sns_fn.return_value = mock_push_sns
        mock_push_sns.publish.return_value = {"MessageId": "push-msg-001"}

        resp_push_send = push_native_mod.handler(
            _apigw_event(
                "POST",
                f"/v1/agents/{agent_id}/push/send",
                path_params={"agent_id": agent_id},
                body={"device_id": device_id, "body_text": "hello"},
            ),
            None,
        )

    assert resp_push_send["statusCode"] == 200, (
        f"Step8 push send failed: {resp_push_send['body']}"
    )
    push_send_body = json.loads(resp_push_send["body"])
    assert push_send_body["status"] in ("sent", "delivered")
    assert push_send_body["channel_native_id"] == "push-msg-001"
