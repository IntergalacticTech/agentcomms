# adapters/slack/tests/test_adapter.py
"""Tests for SlackAdapter implementing the ChannelAdapter contract (Task 1c)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from core.data.models import Agent, Channel, ChannelMode, ChannelStatus, ChannelType
from core.adapters.base import IngestPayload, OutboundMessage
from adapters.slack.adapter import SlackAdapter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def adapter():
    return SlackAdapter()


@pytest.fixture
def slack_channel():
    return Channel(
        channel_id="chan_sl_1",
        agent_id="agt_1",
        org_id="org_X",
        channel=ChannelType.SLACK,
        mode=ChannelMode.BRIDGE,
        config={
            "team_id": "T012AB3C4",
            "bot_user_id": "U0123456789",
            "app_id": "A012AB3C4",
        },
        address_index_value="T012AB3C4:U0123456789",
        status=ChannelStatus.ACTIVE,
    )


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ── Test 1: provision raises NotImplementedError ─────────────────────────────

def test_provision_raises_not_implemented(adapter):
    agent = Agent(agent_id="agt_1", org_id="org_X", name="TestBot")
    with pytest.raises(NotImplementedError, match="bridge mode"):
        adapter.provision(agent=agent, config={})


# ── Test 2: channel_name and supports_modes ──────────────────────────────────

def test_channel_name_and_modes(adapter):
    assert adapter.channel_name == "slack"
    assert adapter.supports_modes == ["bridge"]


# ── Test 3: send DM → conversations.open + chat.postMessage ─────────────────

def test_send_dm_opens_conversation_then_posts(adapter, slack_channel):
    mock_client = MagicMock()
    mock_client.conversations_open.return_value = {
        "channel": {"id": "D099876543"}
    }
    mock_client.chat_postMessage.return_value = {
        "ok": True,
        "ts": "1512085950.999999",
    }

    message = OutboundMessage(
        to="slack:T012AB3C4:U099876543",
        body_text="Hello from your agent",
    )

    with patch("adapters.slack.adapter.get_workspace_token", return_value="xoxb-fake"), \
         patch("adapters.slack.adapter._slack_client", return_value=mock_client):
        result = adapter.send(channel=slack_channel, message=message)

    assert result.status == "sent"
    mock_client.conversations_open.assert_called_once_with(users=["U099876543"])
    mock_client.chat_postMessage.assert_called_once_with(
        channel="D099876543",
        text="Hello from your agent",
    )


# ── Test 4: send to channel → only chat.postMessage (no conversations.open) ──

def test_send_to_channel_id_no_conversation_open(adapter, slack_channel):
    mock_client = MagicMock()
    mock_client.chat_postMessage.return_value = {
        "ok": True,
        "ts": "1512085951.000000",
    }

    message = OutboundMessage(
        to="C012AB3C4",
        body_text="Posting to channel",
    )

    with patch("adapters.slack.adapter.get_workspace_token", return_value="xoxb-fake"), \
         patch("adapters.slack.adapter._slack_client", return_value=mock_client):
        result = adapter.send(channel=slack_channel, message=message)

    assert result.status == "sent"
    mock_client.conversations_open.assert_not_called()
    mock_client.chat_postMessage.assert_called_once_with(
        channel="C012AB3C4",
        text="Posting to channel",
    )


# ── Test 5: teardown revokes token + deletes SSM ─────────────────────────────

def test_teardown_revokes_token_and_deletes_ssm(adapter, slack_channel):
    mock_client = MagicMock()
    mock_client.auth_revoke.return_value = {"ok": True}

    with patch("adapters.slack.adapter.get_workspace_token", return_value="xoxb-fake"), \
         patch("adapters.slack.adapter._slack_client", return_value=mock_client), \
         patch("adapters.slack.adapter.delete_workspace_token") as mock_delete:
        adapter.teardown(channel=slack_channel)

    mock_client.auth_revoke.assert_called_once()
    mock_delete.assert_called_once_with("T012AB3C4")


# ── Test 6: health_check uses auth.test ─────────────────────────────────────

def test_health_check_calls_auth_test(adapter, slack_channel):
    mock_client = MagicMock()
    mock_client.auth_test.return_value = {
        "ok": True,
        "team": "My Workspace",
        "user": "agentcomms-bot",
    }

    with patch("adapters.slack.adapter.get_workspace_token", return_value="xoxb-fake"), \
         patch("adapters.slack.adapter._slack_client", return_value=mock_client):
        status = adapter.health_check(channel=slack_channel)

    assert status.ok is True
    assert status.error is None
    mock_client.auth_test.assert_called_once()


# ── Test 7: health_check returns ok=False when auth.test fails ───────────────

def test_health_check_returns_false_on_auth_failure(adapter, slack_channel):
    mock_client = MagicMock()
    mock_client.auth_test.side_effect = Exception("token_revoked")

    with patch("adapters.slack.adapter.get_workspace_token", return_value="xoxb-fake"), \
         patch("adapters.slack.adapter._slack_client", return_value=mock_client):
        status = adapter.health_check(channel=slack_channel)

    assert status.ok is False
    assert "token_revoked" in (status.error or "")


# ── Test 8: ingest DM event → is_dm=True message ────────────────────────────

def test_ingest_dm_event(adapter, agentcomms_table, repo_fixture, slack_channel):
    # Seed the channel in repo
    repo_fixture.put_channel(slack_channel)

    body = json.loads(load_fixture("event_dm.json"))
    # Adjust authorizations to match the channel's bot_user_id
    body["authorizations"] = [{"user_id": "U0123456789", "team_id": "T012AB3C4"}]

    payload = IngestPayload(
        source="api_gateway",
        headers={},
        body=json.dumps(body).encode("utf-8"),
        path_params={},
    )

    with patch("adapters.slack.adapter._get_table", return_value=agentcomms_table):
        msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.is_dm is True
    assert msg.channel.value == "slack"
    assert msg.agent_id == "agt_1"


# ── Test 9: ingest channel noise → is_dm=False ──────────────────────────────

def test_ingest_channel_noise_not_dm(adapter, agentcomms_table, repo_fixture, slack_channel):
    repo_fixture.put_channel(slack_channel)

    body = json.loads(load_fixture("event_channel_noise.json"))
    body["authorizations"] = [{"user_id": "U0123456789", "team_id": "T012AB3C4"}]

    payload = IngestPayload(
        source="api_gateway",
        headers={},
        body=json.dumps(body).encode("utf-8"),
        path_params={},
    )

    with patch("adapters.slack.adapter._get_table", return_value=agentcomms_table):
        msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.is_dm is False
