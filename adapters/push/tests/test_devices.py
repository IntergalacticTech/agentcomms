# adapters/push/tests/test_devices.py
"""Tests for push device registration helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.data.models import Channel, ChannelMode, ChannelStatus, ChannelType
from core.data.repo import Repo
from adapters.push.devices import Device, delete_device, list_devices, register_device


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
                "apns": "arn:aws:sns:us-east-1:123456789012:app/APNS_SANDBOX/test-apns",
                "fcm": "arn:aws:sns:us-east-1:123456789012:app/GCM/test-fcm",
            },
        },
        status=ChannelStatus.ACTIVE,
    )


# ── Test 1: register_device creates endpoint and stores Device ───────────────

def test_register_device_creates_endpoint_and_stores_item(
    agentcomms_table, repo_fixture, push_channel
):
    repo = repo_fixture
    endpoint_arn = "arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/test/device-001"
    mock_client = MagicMock()
    mock_client.create_platform_endpoint.return_value = {"EndpointArn": endpoint_arn}

    with patch("adapters.push.devices._sns_client", return_value=mock_client):
        device = register_device(repo, push_channel, "apns", "token-abc-123")

    assert isinstance(device, Device)
    assert device.endpoint_arn == endpoint_arn
    assert device.platform == "apns"
    assert device.token == "token-abc-123"
    assert device.channel_id == "chan_ps_1"
    assert device.device_id.startswith("dev_")

    # Verify it was stored in DynamoDB
    devices = list_devices(repo, push_channel)
    assert len(devices) == 1
    assert devices[0].endpoint_arn == endpoint_arn


def test_register_device_idempotent_same_token(
    agentcomms_table, repo_fixture, push_channel
):
    """Re-registering the same token returns the existing device (idempotent)."""
    repo = repo_fixture
    endpoint_arn = "arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/test/device-002"
    mock_client = MagicMock()
    mock_client.create_platform_endpoint.return_value = {"EndpointArn": endpoint_arn}

    with patch("adapters.push.devices._sns_client", return_value=mock_client):
        device1 = register_device(repo, push_channel, "apns", "token-xyz")
        device2 = register_device(repo, push_channel, "apns", "token-xyz")

    # Should still only be one device in DynamoDB
    devices = list_devices(repo, push_channel)
    assert len(devices) == 1
    assert device1.device_id == device2.device_id


# ── Test 2: list_devices returns all devices for a channel ───────────────────

def test_list_devices_returns_all_devices(
    agentcomms_table, repo_fixture, push_channel
):
    repo = repo_fixture
    mock_client = MagicMock()
    mock_client.create_platform_endpoint.side_effect = [
        {"EndpointArn": "arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/test/dev-1"},
        {"EndpointArn": "arn:aws:sns:us-east-1:123456789012:endpoint/GCM/test/dev-2"},
    ]

    with patch("adapters.push.devices._sns_client", return_value=mock_client):
        register_device(repo, push_channel, "apns", "token-apns")
        register_device(repo, push_channel, "fcm", "token-fcm")

    devices = list_devices(repo, push_channel)
    assert len(devices) == 2
    platforms = {d.platform for d in devices}
    assert platforms == {"apns", "fcm"}


# ── Test 3: delete_device removes endpoint and DynamoDB item ─────────────────

def test_delete_device_removes_endpoint_and_item(
    agentcomms_table, repo_fixture, push_channel
):
    repo = repo_fixture
    endpoint_arn = "arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/test/dev-3"
    mock_client = MagicMock()
    mock_client.create_platform_endpoint.return_value = {"EndpointArn": endpoint_arn}

    with patch("adapters.push.devices._sns_client", return_value=mock_client):
        device = register_device(repo, push_channel, "apns", "token-del")
        delete_device(repo, push_channel, device.device_id)

    # SNS delete_endpoint should have been called
    mock_client.delete_endpoint.assert_called_once_with(EndpointArn=endpoint_arn)

    # DynamoDB item should be gone
    devices = list_devices(repo, push_channel)
    assert len(devices) == 0


def test_delete_device_raises_key_error_if_not_found(
    agentcomms_table, repo_fixture, push_channel
):
    repo = repo_fixture
    with pytest.raises(KeyError, match="nonexistent-device"):
        delete_device(repo, push_channel, "nonexistent-device")


# ── Test 4: register_device raises for invalid platform ─────────────────────

def test_register_device_invalid_platform(repo_fixture, push_channel):
    repo = repo_fixture
    with pytest.raises(ValueError, match="platform must be"):
        register_device(repo, push_channel, "whatsapp", "some-token")
