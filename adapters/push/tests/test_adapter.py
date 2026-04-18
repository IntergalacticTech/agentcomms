# adapters/push/tests/test_adapter.py
"""Tests for PushAdapter implementing the ChannelAdapter contract."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    MessageDirection, MessageStatus, Party, UnifiedMessage,
)
from core.adapters.base import IngestPayload, OutboundMessage
from core.data.repo import Repo
from adapters.push.adapter import PushAdapter, _build_apns_payload, _build_fcm_payload

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def adapter():
    return PushAdapter()


@pytest.fixture
def push_channel():
    return Channel(
        channel_id="chan_ps_1",
        agent_id="agt_1",
        org_id="org_X",
        channel=ChannelType.PUSH,
        mode=ChannelMode.PROVISION,
        config={
            "platform_application_arns": {
                "apns": "arn:aws:sns:us-east-1:123456789012:app/APNS_SANDBOX/agentcomms-apns-org_X",
                "fcm": "arn:aws:sns:us-east-1:123456789012:app/GCM/agentcomms-fcm-org_X",
            },
        },
        status=ChannelStatus.ACTIVE,
    )


# ── Test 1: channel_name and supports_modes ──────────────────────────────────

def test_channel_name_and_modes(adapter):
    assert adapter.channel_name == "push"
    assert adapter.supports_modes == ["provision"]


# ── Test 2: provision creates or reuses Platform Applications ────────────────

def test_provision_creates_or_reuses_platform_applications(adapter):
    """When no ARNs are in config, provision creates both Platform Applications."""
    apns_arn = "arn:aws:sns:us-east-1:123456789012:app/APNS_SANDBOX/test-apns"
    fcm_arn = "arn:aws:sns:us-east-1:123456789012:app/GCM/test-fcm"
    mock_client = MagicMock()
    mock_client.create_platform_application.side_effect = [
        {"PlatformApplicationArn": apns_arn},
        {"PlatformApplicationArn": fcm_arn},
    ]

    with patch("adapters.push.adapter._sns_client", return_value=mock_client):
        agent = Agent(agent_id="agt_1", org_id="org_X", name="bot")
        result = adapter.provision(
            agent=agent,
            config={
                "apns_platform_credential": "APNS_KEY",
                "apns_platform_principal": "APNS_CERT",
                "fcm_platform_credential": "FCM_KEY",
            },
        )

    assert result.status == "active"
    assert result.channel_id.startswith("chan_ps_")
    assert result.details["platform_application_arns"]["apns"] == apns_arn
    assert result.details["platform_application_arns"]["fcm"] == fcm_arn
    assert mock_client.create_platform_application.call_count == 2


def test_provision_reuses_existing_arns(adapter):
    """When ARNs are already in config, no AWS calls are made."""
    existing_apns = "arn:aws:sns:us-east-1:123456789012:app/APNS_SANDBOX/existing"
    existing_fcm = "arn:aws:sns:us-east-1:123456789012:app/GCM/existing"
    mock_client = MagicMock()

    with patch("adapters.push.adapter._sns_client", return_value=mock_client):
        agent = Agent(agent_id="agt_1", org_id="org_X", name="bot")
        result = adapter.provision(
            agent=agent,
            config={
                "apns_platform_application_arn": existing_apns,
                "fcm_platform_application_arn": existing_fcm,
            },
        )

    assert result.status == "active"
    assert result.details["platform_application_arns"]["apns"] == existing_apns
    assert result.details["platform_application_arns"]["fcm"] == existing_fcm
    mock_client.create_platform_application.assert_not_called()


# ── Test 3: send publishes to endpoint ARN with correct envelope ─────────────

@pytest.mark.parametrize("platform,to_prefix", [
    ("apns", "push:apns:"),
    ("fcm", "push:fcm:"),
])
def test_send_publishes_to_endpoint_arn_with_correct_envelope(
    adapter, push_channel, platform, to_prefix
):
    endpoint_arn = f"arn:aws:sns:us-east-1:123456789012:endpoint/{platform.upper()}/app/device-001"
    mock_client = MagicMock()
    mock_client.publish.return_value = {"MessageId": f"sns-{platform}-001"}

    message = OutboundMessage(
        to=f"{to_prefix}{endpoint_arn}",
        body_text="Hello from agent",
        subject="Test notification",
        channel_native_overrides={"title": "Test Title"},
    )

    with patch("adapters.push.adapter._sns_client", return_value=mock_client):
        result = adapter.send(channel=push_channel, message=message)

    assert result.status == "sent"
    assert result.channel_native_id == f"sns-{platform}-001"

    # Verify the call was made with correct TargetArn and MessageStructure
    call_kwargs = mock_client.publish.call_args[1]
    assert call_kwargs["TargetArn"] == endpoint_arn
    assert call_kwargs["MessageStructure"] == "json"

    # Verify the payload envelope is platform-correct
    payload = json.loads(call_kwargs["Message"])
    assert "default" in payload
    if platform == "apns":
        assert "APNS" in payload
        assert "APNS_SANDBOX" in payload
        apns_body = json.loads(payload["APNS"])
        assert "aps" in apns_body
        assert apns_body["aps"]["alert"]["title"] == "Test Title"
    else:
        assert "GCM" in payload
        gcm_body = json.loads(payload["GCM"])
        assert "notification" in gcm_body


# ── Test 4: ingest updates existing message status ───────────────────────────

def test_ingest_updates_existing_message_status(
    adapter, agentcomms_table, repo_fixture, push_channel
):
    """Delivery receipt with SUCCESSFUL status updates UnifiedMessage to delivered."""
    repo = repo_fixture

    # Store a sent push message with external_id = SNS MessageId
    from core.data.ulid_ import new_id
    msg = UnifiedMessage(
        message_id=new_id("msg"),
        agent_id="agt_1",
        org_id="org_X",
        channel_id="chan_ps_1",
        channel=ChannelType.PUSH,
        direction=MessageDirection.OUTBOUND,
        status=MessageStatus.SENT,
        **{"from": Party(address="push:apns:arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/app/dev")},
        to=[Party(address="push:apns:arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/app/dev")],
        subject="Test",
        body_text="Hello",
        is_dm=True,
        received_at=datetime.now(timezone.utc),
        external_id="sns-msg-id-apns-001",
    )
    repo.put_message(msg)

    receipt = json.loads((FIXTURES / "delivery_receipt_apns.json").read_text())
    payload = IngestPayload(source="sns", headers={}, body=receipt, path_params={})

    with patch("adapters.push.adapter._get_table", return_value=agentcomms_table):
        updated = adapter.ingest(payload=payload)

    assert updated is not None
    assert updated.status == MessageStatus.DELIVERED


def test_ingest_returns_none_for_unknown_message(adapter, agentcomms_table):
    """Delivery receipt with unknown messageId returns None."""
    receipt = {
        "notification": {"messageId": "nonexistent-sns-id"},
        "status": "SUCCESSFUL",
    }
    payload = IngestPayload(source="sns", headers={}, body=receipt, path_params={})

    with patch("adapters.push.adapter._get_table", return_value=agentcomms_table):
        result = adapter.ingest(payload=payload)

    assert result is None


# ── Test 5: teardown cleans up endpoints ─────────────────────────────────────

def test_teardown_cleans_up_endpoints(adapter, push_channel):
    """teardown deletes endpoints whose CustomUserData matches the channel_id."""
    apns_arn = push_channel.config["platform_application_arns"]["apns"]
    fcm_arn = push_channel.config["platform_application_arns"]["fcm"]
    endpoint_arn_1 = "arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/app/dev1"
    endpoint_arn_2 = "arn:aws:sns:us-east-1:123456789012:endpoint/GCM/app/dev2"

    mock_client = MagicMock()

    # Mock paginator for both platform apps
    def make_paginator(pages):
        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = iter(pages)
        return paginator_mock

    apns_pages = [{"Endpoints": [
        {"EndpointArn": endpoint_arn_1, "Attributes": {"CustomUserData": "chan_ps_1"}},
    ]}]
    fcm_pages = [{"Endpoints": [
        {"EndpointArn": endpoint_arn_2, "Attributes": {"CustomUserData": "chan_ps_1"}},
    ]}]

    def get_paginator(method):
        return make_paginator(
            apns_pages if method == "list_endpoints_by_platform_application" else []
        )

    # We need separate paginators per call — use side_effect list
    apns_paginator = make_paginator(apns_pages)
    fcm_paginator = make_paginator(fcm_pages)
    mock_client.get_paginator.side_effect = [apns_paginator, fcm_paginator]

    with patch("adapters.push.adapter._sns_client", return_value=mock_client):
        adapter.teardown(channel=push_channel)

    assert mock_client.delete_endpoint.call_count == 2
    mock_client.delete_endpoint.assert_any_call(EndpointArn=endpoint_arn_1)
    mock_client.delete_endpoint.assert_any_call(EndpointArn=endpoint_arn_2)


# ── Test 6: health_check returns ok when both apps respond ───────────────────

def test_health_check_ok(adapter, push_channel):
    mock_client = MagicMock()
    mock_client.get_platform_application_attributes.return_value = {
        "Attributes": {"Enabled": "true"}
    }

    with patch("adapters.push.adapter._sns_client", return_value=mock_client):
        status = adapter.health_check(channel=push_channel)

    assert status.ok is True
    assert status.error is None
    assert mock_client.get_platform_application_attributes.call_count == 2


# ── Payload builder unit tests ───────────────────────────────────────────────

def test_build_apns_payload_structure():
    payload = _build_apns_payload("My Title", "My body", badge=3)
    assert "default" in payload
    assert "APNS" in payload
    assert "APNS_SANDBOX" in payload
    apns = json.loads(payload["APNS"])
    assert apns["aps"]["alert"]["title"] == "My Title"
    assert apns["aps"]["alert"]["body"] == "My body"
    assert apns["aps"]["badge"] == 3


def test_build_fcm_payload_structure():
    payload = _build_fcm_payload("FCM Title", "FCM body")
    assert "default" in payload
    assert "GCM" in payload
    gcm = json.loads(payload["GCM"])
    assert gcm["notification"]["title"] == "FCM Title"
    assert gcm["notification"]["body"] == "FCM body"
