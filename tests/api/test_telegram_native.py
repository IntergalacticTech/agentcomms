# tests/api/test_telegram_native.py
"""Tests for Telegram native sub-surface API routes (Task 3c)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    MessageDirection, MessageStatus, Party, UnifiedMessage,
)
from core.data.repo import Repo


@pytest.fixture
def tg_channel_fixture(agentcomms_table, repo_fixture):
    """Create and seed a Telegram channel in DynamoDB."""
    repo_fixture.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="bot"))
    from adapters.telegram.adapter import _token_hash
    BOT_TOKEN = "555000555:AABBCCDDEEFFaabbccddeeff_test"
    tok_hash = _token_hash(BOT_TOKEN)

    channel = Channel(
        channel_id="chan_tg_TEST01",
        agent_id="agt_1",
        org_id="org_X",
        channel=ChannelType.TELEGRAM,
        mode=ChannelMode.PROVISION,
        config={
            "bot_username": "testbot",
            "bot_id": 555000555,
            "token_hash": tok_hash,
        },
        address_index_value=f"token:{tok_hash}",
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


def _seed_message(repo_fixture, channel_fixture, chat_id: int, msg_id: str = "msg_001"):
    """Helper to seed a test message in DynamoDB."""
    msg = UnifiedMessage(
        message_id=msg_id,
        agent_id="agt_1",
        org_id="org_X",
        channel_id=channel_fixture.channel_id,
        channel=ChannelType.TELEGRAM,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        **{"from": Party(address=f"telegram:user:alice_user")},
        body_text="Hello!",
        is_dm=True,
        received_at=datetime.now(timezone.utc),
        channel_native={
            "chat_id": chat_id,
            "chat_type": "private",
            "update_id": 100000001,
            "entities": [],
            "reply_to_message_id": None,
        },
        external_id=f"{chat_id}:1001",
    )
    repo_fixture.put_message(msg)
    return msg


# ── Test 1: list chats returns empty when no messages ───────────────────────

def test_list_chats_empty(agentcomms_table, tg_channel_fixture):
    from core.api.telegram_native_handler import handler

    event = _make_event(
        "GET",
        "/v1/agents/agt_1/telegram/chats",
        {"agent_id": "agt_1"},
    )

    with patch("core.api.telegram_native_handler._get_table", return_value=agentcomms_table), \
         patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "chats" in body
    assert body["chats"] == []


# ── Test 2: list chats returns unique chats from messages ────────────────────

def test_list_chats_with_messages(agentcomms_table, tg_channel_fixture, repo_fixture):
    from core.api.telegram_native_handler import handler

    # Seed two messages in different chats
    _seed_message(repo_fixture, tg_channel_fixture, chat_id=111111, msg_id="msg_001")
    _seed_message(repo_fixture, tg_channel_fixture, chat_id=222222, msg_id="msg_002")

    event = _make_event(
        "GET",
        "/v1/agents/agt_1/telegram/chats",
        {"agent_id": "agt_1"},
    )

    with patch("core.api.telegram_native_handler._get_table", return_value=agentcomms_table), \
         patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "chats" in body
    chat_ids = {c["chat_id"] for c in body["chats"]}
    assert "111111" in chat_ids
    assert "222222" in chat_ids


# ── Test 3: list messages for a specific chat ─────────────────────────────────

def test_list_chat_messages(agentcomms_table, tg_channel_fixture, repo_fixture):
    from core.api.telegram_native_handler import handler

    _seed_message(repo_fixture, tg_channel_fixture, chat_id=111111, msg_id="msg_001")
    _seed_message(repo_fixture, tg_channel_fixture, chat_id=222222, msg_id="msg_002")

    event = _make_event(
        "GET",
        "/v1/agents/agt_1/telegram/chats/111111/messages",
        {"agent_id": "agt_1", "chat_id": "111111"},
    )

    with patch("core.api.telegram_native_handler._get_table", return_value=agentcomms_table), \
         patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "messages" in body
    # Only messages from chat 111111
    assert len(body["messages"]) == 1
    assert int(body["messages"][0]["channel_native"]["chat_id"]) == 111111


# ── Test 4: post message to chat ─────────────────────────────────────────────

def test_post_to_chat(agentcomms_table, tg_channel_fixture):
    from core.api.telegram_native_handler import handler

    mock_client = MagicMock()
    mock_client.send_message.return_value = {"message_id": 42}

    event = _make_event(
        "POST",
        "/v1/agents/agt_1/telegram/chats/111111/messages",
        {"agent_id": "agt_1", "chat_id": "111111"},
        body={"text": "Hello from agent!"},
    )

    with patch("core.api.telegram_native_handler._get_table", return_value=agentcomms_table), \
         patch("adapters.telegram.adapter.get_bot_token", return_value="fake_token"), \
         patch("adapters.telegram.adapter.TelegramBotClient", return_value=mock_client):
        resp = handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ok"] is True
    assert body["message_id"] == "42"
    mock_client.send_message.assert_called_once()


# ── Test 5: channel not found returns 404 ────────────────────────────────────

def test_channel_not_found(agentcomms_table, repo_fixture):
    # Seed an owned agent (org_X) that has NO telegram channel, so the request
    # passes the tenant gate and then hits the channel-not-found branch.
    from core.data.models import Agent
    repo_fixture.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="bot"))
    from core.api.telegram_native_handler import handler

    event = _make_event(
        "GET",
        "/v1/agents/agt_1/telegram/chats/111111/messages",
        {"agent_id": "agt_1", "chat_id": "111111"},
    )

    with patch("core.api.telegram_native_handler._get_table", return_value=agentcomms_table):
        resp = handler(event, None)

    assert resp["statusCode"] == 404


# ── Test 6: post without text returns 400 ────────────────────────────────────

def test_post_requires_text(agentcomms_table, tg_channel_fixture):
    from core.api.telegram_native_handler import handler

    event = _make_event(
        "POST",
        "/v1/agents/agt_1/telegram/chats/111111/messages",
        {"agent_id": "agt_1", "chat_id": "111111"},
        body={},
    )

    with patch("core.api.telegram_native_handler._get_table", return_value=agentcomms_table):
        resp = handler(event, None)

    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "text" in body["error"]
