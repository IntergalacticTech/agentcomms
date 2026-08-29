# tests/api/test_push_native.py
"""Tests for /v1/agents/{agent_id}/push/* native routes."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    Organization, OrgPlan,
)
from core.data.repo import Repo
from core.api.push_native_handler import handler


@pytest.fixture
def seeded(agentcomms_table, ses_client, s3_buckets):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_X", name="Acme", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="PushBot"))
    # Seed a push channel
    repo.put_channel(Channel(
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
    ))
    return repo


def _event(method, path, path_params=None, body=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {
            "org_id": "org_X", "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


# ── Test 1: register device returns 201 with device_id + endpoint_arn ────────

def test_register_device_returns_201(seeded):
    endpoint_arn = "arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/test-apns/dev-001"
    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.return_value = {"EndpointArn": endpoint_arn}

    with patch("adapters.push.devices._sns_client", return_value=mock_sns):
        resp = handler(_event(
            "POST",
            "/v1/agents/agt_1/push/devices",
            path_params={"agent_id": "agt_1"},
            body={"platform": "apns", "token": "device-token-abc"},
        ), None)

    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["endpoint_arn"] == endpoint_arn
    assert body["platform"] == "apns"
    assert "device_id" in body
    assert "created_at" in body


# ── Test 2: list devices returns 200 with devices array ──────────────────────

def test_list_devices_returns_200(seeded):
    endpoint_arn = "arn:aws:sns:us-east-1:123456789012:endpoint/GCM/test-fcm/dev-002"
    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.return_value = {"EndpointArn": endpoint_arn}

    with patch("adapters.push.devices._sns_client", return_value=mock_sns):
        # Register one device first
        handler(_event(
            "POST",
            "/v1/agents/agt_1/push/devices",
            path_params={"agent_id": "agt_1"},
            body={"platform": "fcm", "token": "fcm-token-001"},
        ), None)

        resp = handler(_event(
            "GET",
            "/v1/agents/agt_1/push/devices",
            path_params={"agent_id": "agt_1"},
        ), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["devices"]) == 1
    assert body["devices"][0]["platform"] == "fcm"


# ── Test 3: delete device returns 204 ────────────────────────────────────────

def test_delete_device_returns_204(seeded):
    endpoint_arn = "arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/test-apns/dev-003"
    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.return_value = {"EndpointArn": endpoint_arn}

    with patch("adapters.push.devices._sns_client", return_value=mock_sns):
        # Register
        create_resp = handler(_event(
            "POST",
            "/v1/agents/agt_1/push/devices",
            path_params={"agent_id": "agt_1"},
            body={"platform": "apns", "token": "token-to-delete"},
        ), None)
        device_id = json.loads(create_resp["body"])["device_id"]

        # Delete
        resp = handler(_event(
            "DELETE",
            f"/v1/agents/agt_1/push/devices/{device_id}",
            path_params={"agent_id": "agt_1", "device_id": device_id},
        ), None)

    assert resp["statusCode"] == 204

    # Verify gone
    with patch("adapters.push.devices._sns_client", return_value=mock_sns):
        list_resp = handler(_event(
            "GET",
            "/v1/agents/agt_1/push/devices",
            path_params={"agent_id": "agt_1"},
        ), None)
    assert json.loads(list_resp["body"])["devices"] == []


# ── Test 4: send returns 200 with channel_native_id ──────────────────────────

def test_send_push_notification_returns_200(seeded):
    endpoint_arn = "arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/test-apns/dev-004"
    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.return_value = {"EndpointArn": endpoint_arn}
    mock_sns.publish.return_value = {"MessageId": "sns-pub-001"}

    with patch("adapters.push.devices._sns_client", return_value=mock_sns):
        create_resp = handler(_event(
            "POST",
            "/v1/agents/agt_1/push/devices",
            path_params={"agent_id": "agt_1"},
            body={"platform": "apns", "token": "token-send-test"},
        ), None)
        device_id = json.loads(create_resp["body"])["device_id"]

    with patch("adapters.push.adapter._sns_client", return_value=mock_sns):
        resp = handler(_event(
            "POST",
            "/v1/agents/agt_1/push/send",
            path_params={"agent_id": "agt_1"},
            body={
                "device_id": device_id,
                "body_text": "Your job finished!",
                "title": "Build Complete",
                "badge": 1,
            },
        ), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["channel_native_id"] == "sns-pub-001"
    assert body["status"] == "sent"


# ── Test 5: register with invalid platform returns 400 ───────────────────────

def test_register_device_invalid_platform_returns_400(seeded):
    resp = handler(_event(
        "POST",
        "/v1/agents/agt_1/push/devices",
        path_params={"agent_id": "agt_1"},
        body={"platform": "windows_phone", "token": "abc"},
    ), None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "platform" in body["error"]


# ── Test 6: delete non-existent device returns 404 ───────────────────────────

def test_delete_nonexistent_device_returns_404(seeded):
    resp = handler(_event(
        "DELETE",
        "/v1/agents/agt_1/push/devices/nonexistent",
        path_params={"agent_id": "agt_1", "device_id": "nonexistent"},
    ), None)
    assert resp["statusCode"] == 404
