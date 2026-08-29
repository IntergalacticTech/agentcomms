# adapters/sms/tests/test_adapter.py
"""Tests for SmsAdapter implementing the ChannelAdapter contract."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import Agent, Channel, ChannelMode, ChannelStatus, ChannelType
from core.adapters.base import IngestPayload, OutboundMessage
from adapters.sms.adapter import SmsAdapter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def adapter():
    return SmsAdapter()


@pytest.fixture
def sms_channel():
    return Channel(
        channel_id="chan_sm_1",
        agent_id="agt_1",
        org_id="org_X",
        channel=ChannelType.SMS,
        mode=ChannelMode.PROVISION,
        config={
            "phone_e164": "+18005550000",
            "phone_number_id": "phone-id-001",
            "phone_number_arn": "arn:aws:sms-voice:us-east-1:123456789012:phone-number/phone-id-001",
        },
        address_index_value="+18005550000",
        status=ChannelStatus.ACTIVE,
    )


# ── Test 1: channel_name and supports_modes ──────────────────────────────────

def test_channel_name_and_modes(adapter):
    assert adapter.channel_name == "sms"
    assert adapter.supports_modes == ["provision"]


# ── Test 2: provision calls request_phone_number ─────────────────────────────

def test_provision_request_phone_number(adapter):
    mock_resp = {
        "PhoneNumberId": "phone-id-001",
        "PhoneNumberArn": "arn:aws:sms-voice:us-east-1:123456789012:phone-number/phone-id-001",
        "PhoneNumber": "+18005550000",
        "Status": "PENDING",
        "IsoCountryCode": "US",
    }
    mock_client = MagicMock()
    mock_client.request_phone_number.return_value = mock_resp

    with patch("adapters.sms.adapter._sms_client", return_value=mock_client):
        agent = Agent(agent_id="agt_1", org_id="org_X", name="bot")
        result = adapter.provision(agent=agent, config={"country": "US"})

    assert result.status == "provisioning"
    assert result.channel_id.startswith("chan_sm_")
    assert result.details["phone_e164"] == "+18005550000"
    assert result.details["phone_number_id"] == "phone-id-001"
    assert result.details["ten_dlc_status"] == "pending_brand_registration"
    assert result.details["country"] == "US"
    mock_client.request_phone_number.assert_called_once_with(
        IsoCountryCode="US",
        MessageType="TRANSACTIONAL",
        NumberCapabilities=["SMS"],
        NumberType="LONG_CODE",
    )


# ── Test 3: ingest routes by destination phone ───────────────────────────────

def test_ingest_routes_by_destination_phone(adapter, agentcomms_table, repo_fixture, sms_channel):
    # Seed the channel in the repo so GSI2 lookup finds it
    repo_fixture.put_channel(sms_channel)

    sns_payload = {
        "originationNumber": "+14155551234",
        "destinationNumber": "+18005550000",
        "messageBody": "Your code is 482917",
        "messageId": "abc123",
        "inboundMessageId": "def456",
        "messageSegmentCount": 1,
        "originationCountryIso": "US",
        "carrierCode": "310410",
    }
    payload = IngestPayload(source="sns", headers={}, body=sns_payload, path_params={})
    msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.channel.value == "sms"
    assert msg.direction.value == "inbound"
    assert msg.status.value == "received"
    assert msg.is_dm is True
    assert msg.agent_id == "agt_1"
    assert msg.channel_id == "chan_sm_1"
    assert msg.from_.address == "+14155551234"
    assert msg.to[0].address == "+18005550000"
    assert msg.body_text == "Your code is 482917"
    assert msg.external_id == "def456"
    assert msg.channel_native["message_segments"] == 1
    assert msg.channel_native["carrier_id"] == "310410"
    assert msg.channel_native["country"] == "US"


# ── Test 4: ingest returns None for unknown number ───────────────────────────

def test_ingest_returns_none_for_unknown_number(adapter, agentcomms_table, repo_fixture):
    # No channel seeded — lookup should return None → adapter returns None
    sns_payload = {
        "originationNumber": "+14155551234",
        "destinationNumber": "+19995550001",  # unknown
        "messageBody": "Hello",
        "messageId": "unknown-msg",
        "inboundMessageId": "unknown-inb",
    }
    payload = IngestPayload(source="sns", headers={}, body=sns_payload, path_params={})
    msg = adapter.ingest(payload=payload)
    assert msg is None


# ── Test 5: send calls send_text_message ─────────────────────────────────────

def test_send_calls_end_user_messaging(adapter, sms_channel):
    mock_resp = {"MessageId": "sms-out-001"}
    mock_client = MagicMock()
    mock_client.send_text_message.return_value = mock_resp

    message = OutboundMessage(
        to="+14155551234",
        body_text="Hello from your agent",
    )

    with patch("adapters.sms.adapter._sms_client", return_value=mock_client):
        result = adapter.send(channel=sms_channel, message=message)

    assert result.status == "sent"
    assert result.channel_native_id == "sms-out-001"
    mock_client.send_text_message.assert_called_once_with(
        OriginationIdentity=sms_channel.config["phone_number_arn"],
        DestinationPhoneNumber="+14155551234",
        MessageBody="Hello from your agent",
        MessageType="TRANSACTIONAL",
    )


# ── Test 6: teardown calls release_phone_number ──────────────────────────────

def test_teardown_calls_release_phone_number(adapter, sms_channel):
    mock_client = MagicMock()

    with patch("adapters.sms.adapter._sms_client", return_value=mock_client):
        adapter.teardown(channel=sms_channel)

    mock_client.release_phone_number.assert_called_once_with(
        PhoneNumberId="phone-id-001"
    )


# ── Test 7: health_check verifies ACTIVE status ──────────────────────────────

def test_health_check_active(adapter, sms_channel):
    mock_client = MagicMock()
    mock_client.describe_phone_numbers.return_value = {
        "PhoneNumbers": [{"PhoneNumberId": "phone-id-001", "Status": "ACTIVE"}]
    }

    with patch("adapters.sms.adapter._sms_client", return_value=mock_client):
        status = adapter.health_check(channel=sms_channel)

    assert status.ok is True
    assert status.error is None


def test_health_check_non_active_status(adapter, sms_channel):
    mock_client = MagicMock()
    mock_client.describe_phone_numbers.return_value = {
        "PhoneNumbers": [{"PhoneNumberId": "phone-id-001", "Status": "DELETED"}]
    }

    with patch("adapters.sms.adapter._sms_client", return_value=mock_client):
        status = adapter.health_check(channel=sms_channel)

    assert status.ok is False
    assert "DELETED" in (status.error or "")
