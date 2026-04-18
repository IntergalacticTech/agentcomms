# adapters/slack/tests/test_oauth.py
"""Tests for Slack OAuth bridge flow (Task 1b)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import Agent, Channel, ChannelMode, ChannelStatus, ChannelType

FIXTURES = Path(__file__).parent / "fixtures"


# ── Test 1: bridge_start returns oauth_url with correct params ───────────────

def test_bridge_start_returns_oauth_url(agentcomms_table):
    from adapters.slack.adapter import SlackAdapter

    adapter = SlackAdapter()
    agent = Agent(agent_id="agt_1", org_id="org_X", name="TestBot")

    with patch("adapters.slack.oauth.get_client_id", return_value="FAKE_CLIENT_ID"), \
         patch("adapters.slack.adapter._get_table", return_value=agentcomms_table):
        result = adapter.bridge_start(
            agent=agent,
            config={"return_url": "https://myapp.com/callback"},
        )

    assert result.oauth_url.startswith("https://slack.com/oauth/v2/authorize")
    assert "client_id=FAKE_CLIENT_ID" in result.oauth_url
    assert "state=" in result.oauth_url
    assert len(result.state) == 32  # 16 hex bytes
    assert result.instructions  # non-empty


# ── Test 2: bridge_start stores state in DynamoDB ───────────────────────────

def test_bridge_start_stores_state_in_dynamodb(agentcomms_table):
    from adapters.slack.adapter import SlackAdapter
    import boto3

    adapter = SlackAdapter()
    agent = Agent(agent_id="agt_2", org_id="org_X", name="TestBot2")

    with patch("adapters.slack.oauth.get_client_id", return_value="CLI"), \
         patch("adapters.slack.adapter._get_table", return_value=agentcomms_table), \
         patch("adapters.slack.oauth._get_table", return_value=agentcomms_table):
        result = adapter.bridge_start(
            agent=agent,
            config={"return_url": "https://myapp.com/callback"},
        )

    # State should be in DynamoDB
    resp = agentcomms_table.get_item(
        Key={"PK": f"OAUTH#{result.state}", "SK": "STATE"}
    )
    item = resp.get("Item")
    assert item is not None
    assert item["agent_id"] == "agt_2"
    assert item["return_url"] == "https://myapp.com/callback"
    assert "ttl" in item
    assert int(item["ttl"]) > int(time.time())  # TTL is in the future


# ── Test 3: bridge_complete updates channel to active ───────────────────────

def test_bridge_complete_sets_channel_active(agentcomms_table):
    from adapters.slack.adapter import SlackAdapter
    from core.data.repo import Repo

    adapter = SlackAdapter()

    # Create a pending_oauth slack channel
    channel = Channel(
        channel_id="chan_sl_1",
        agent_id="agt_1",
        org_id="org_X",
        channel=ChannelType.SLACK,
        mode=ChannelMode.BRIDGE,
        status=ChannelStatus.PENDING_OAUTH,
        config={},
    )
    repo = Repo(agentcomms_table)
    repo.put_channel(channel)

    with patch("adapters.slack.adapter.store_workspace_token") as mock_store, \
         patch("adapters.slack.adapter._get_table", return_value=agentcomms_table):
        result = adapter.bridge_complete(
            channel=channel,
            callback_params={
                "team_id": "T012AB3C4",
                "bot_token": "xoxb-fake-token",
                "bot_user_id": "U0123456789",
                "app_id": "A012AB3C4",
            },
        )

    assert result.status == "active"
    assert result.channel_id == "chan_sl_1"
    assert result.details["team_id"] == "T012AB3C4"
    mock_store.assert_called_once_with("T012AB3C4", "xoxb-fake-token")

    # Channel should be updated in DynamoDB
    updated = repo.get_channel(
        agent_id="agt_1", channel="slack", channel_id="chan_sl_1"
    )
    assert updated is not None
    assert updated.status == ChannelStatus.ACTIVE
    assert updated.config["team_id"] == "T012AB3C4"


# ── Test 4: oauth_callback_handler validates state ──────────────────────────

def test_oauth_callback_handler_invalid_state():
    from adapters.slack.oauth import oauth_callback_handler

    event = {
        "queryStringParameters": {
            "code": "fake_code",
            "state": "nonexistent_state",
        },
        "headers": {"Host": "api.agentcomms.dev"},
        "requestContext": {"stage": "prod"},
    }

    with patch("adapters.slack.oauth.get_and_consume_oauth_state", return_value=None):
        resp = oauth_callback_handler(event, None)

    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "invalid or expired state" in body["error"]


# ── Test 5: bridge_start requires return_url ────────────────────────────────

def test_bridge_start_requires_return_url(agentcomms_table):
    from adapters.slack.adapter import SlackAdapter

    adapter = SlackAdapter()
    agent = Agent(agent_id="agt_1", org_id="org_X", name="TestBot")

    with patch("adapters.slack.oauth.get_client_id", return_value="CLI"), \
         patch("adapters.slack.adapter._get_table", return_value=agentcomms_table):
        with pytest.raises(ValueError, match="return_url"):
            adapter.bridge_start(agent=agent, config={})
