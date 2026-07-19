# tests/api/test_slack_native.py
"""Tests for Slack native sub-surface API routes (Task 1d2)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
)
from core.data.repo import Repo


@pytest.fixture
def slack_channel_fixture(agentcomms_table, repo_fixture):
    """Create and seed a Slack channel in DynamoDB."""
    repo_fixture.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="bot"))
    channel = Channel(
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
    repo_fixture.put_channel(channel)
    return channel


def _make_event(
    method: str, path: str, path_params: dict, body: dict | None = None,
    org_id: str = "org_X",
) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params,
        "body": json.dumps(body) if body else None,
        "headers": {"Authorization": "Bearer test"},
        "requestContext": {"authorizer": {
            "org_id": org_id, "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


# ── Test 1: list workspaces ──────────────────────────────────────────────────

def test_list_workspaces(agentcomms_table, slack_channel_fixture):
    from core.api.slack_native_handler import handler

    event = _make_event(
        "GET",
        "/v1/agents/agt_1/slack/workspaces",
        {"agent_id": "agt_1"},
    )

    with patch("core.api.slack_native_handler._get_table", return_value=agentcomms_table):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "workspaces" in body
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["team_id"] == "T012AB3C4"


# ── Test 2: list channels in workspace ──────────────────────────────────────

def test_list_channels_in_workspace(agentcomms_table, slack_channel_fixture):
    from core.api.slack_native_handler import handler

    mock_client = MagicMock()
    mock_client.conversations_list.return_value = {
        "channels": [
            {"id": "C001", "name": "general", "is_member": True, "is_private": False, "num_members": 10},
            {"id": "C002", "name": "random", "is_member": True, "is_private": False, "num_members": 5},
            {"id": "C003", "name": "not-a-member", "is_member": False, "is_private": False, "num_members": 2},
        ]
    }

    event = _make_event(
        "GET",
        "/v1/agents/agt_1/slack/workspaces/T012AB3C4/channels",
        {"agent_id": "agt_1", "team_id": "T012AB3C4"},
    )

    with patch("core.api.slack_native_handler._get_table", return_value=agentcomms_table), \
         patch("core.api.slack_native_handler._slack_client_for_channel", return_value=mock_client):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "channels" in body
    # Only is_member=True channels returned
    assert len(body["channels"]) == 2
    channel_names = {c["name"] for c in body["channels"]}
    assert "general" in channel_names
    assert "not-a-member" not in channel_names


# ── Test 3: post message to channel ─────────────────────────────────────────

def test_post_to_channel(agentcomms_table, slack_channel_fixture):
    from core.api.slack_native_handler import handler

    mock_client = MagicMock()
    mock_client.chat_postMessage.return_value = {
        "ok": True,
        "ts": "1512085950.123456",
        "channel": "C001",
    }

    event = _make_event(
        "POST",
        "/v1/agents/agt_1/slack/workspaces/T012AB3C4/channels/C001/messages",
        {"agent_id": "agt_1", "team_id": "T012AB3C4", "channel_id": "C001"},
        body={"text": "Hello channel!"},
    )

    with patch("core.api.slack_native_handler._get_table", return_value=agentcomms_table), \
         patch("core.api.slack_native_handler._slack_client_for_channel", return_value=mock_client):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ok"] is True
    mock_client.chat_postMessage.assert_called_once_with(channel="C001", text="Hello channel!")


# ── Test 4: send DM to user ──────────────────────────────────────────────────

def test_send_dm_to_user(agentcomms_table, slack_channel_fixture):
    from core.api.slack_native_handler import handler

    mock_client = MagicMock()
    mock_client.conversations_open.return_value = {"channel": {"id": "D099876543"}}
    mock_client.chat_postMessage.return_value = {
        "ok": True,
        "ts": "1512085950.999999",
        "channel": "D099876543",
    }

    event = _make_event(
        "POST",
        "/v1/agents/agt_1/slack/workspaces/T012AB3C4/users/U099876543/messages",
        {"agent_id": "agt_1", "team_id": "T012AB3C4", "user_id": "U099876543"},
        body={"text": "Hello from agent!"},
    )

    with patch("core.api.slack_native_handler._get_table", return_value=agentcomms_table), \
         patch("core.api.slack_native_handler._slack_client_for_channel", return_value=mock_client):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ok"] is True
    assert body["channel"] == "D099876543"
    mock_client.conversations_open.assert_called_once_with(users=["U099876543"])
    mock_client.chat_postMessage.assert_called_once_with(
        channel="D099876543", text="Hello from agent!"
    )


# ── Test 5: workspace not found returns 404 ──────────────────────────────────

def test_channels_list_workspace_not_found(agentcomms_table, slack_channel_fixture):
    # slack_channel_fixture seeds agt_1 (owned by org_X) + a channel for
    # T012AB3C4. Requesting an *unknown* team exercises the workspace-not-found
    # branch AFTER the tenant gate passes (agent exists in the caller's org).
    from core.api.slack_native_handler import handler

    event = _make_event(
        "GET",
        "/v1/agents/agt_1/slack/workspaces/T_UNKNOWN/channels",
        {"agent_id": "agt_1", "team_id": "T_UNKNOWN"},
    )

    with patch("core.api.slack_native_handler._get_table", return_value=agentcomms_table):
        resp = handler(event, None)

    assert resp["statusCode"] == 404


# ── Test 6: list messages returns db messages ────────────────────────────────

def test_list_channel_messages(agentcomms_table, slack_channel_fixture, repo_fixture):
    from core.api.slack_native_handler import handler
    from core.data.models import (
        UnifiedMessage, MessageDirection, MessageStatus, Party, ChannelType,
    )
    from datetime import datetime, timezone

    # Seed a message in DB
    msg = UnifiedMessage(
        message_id="msg_001",
        agent_id="agt_1",
        org_id="org_X",
        channel_id="chan_sl_1",
        channel=ChannelType.SLACK,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        **{"from": Party(address="slack:T012AB3C4:U099876543")},
        body_text="Hello!",
        is_dm=False,
        received_at=datetime.now(timezone.utc),
        channel_native={"channel_id": "C001", "team_id": "T012AB3C4", "ts": "123"},
    )
    repo_fixture.put_message(msg)

    mock_client = MagicMock()
    mock_client.conversations_history.return_value = {"messages": []}

    event = _make_event(
        "GET",
        "/v1/agents/agt_1/slack/workspaces/T012AB3C4/channels/C001/messages",
        {"agent_id": "agt_1", "team_id": "T012AB3C4", "channel_id": "C001"},
    )

    with patch("core.api.slack_native_handler._get_table", return_value=agentcomms_table), \
         patch("core.api.slack_native_handler._slack_client_for_channel", return_value=mock_client):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "messages" in body
    # The message we seeded should appear
    assert len(body["messages"]) == 1
