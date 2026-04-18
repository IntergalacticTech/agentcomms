# adapters/telegram/tests/test_adapter.py
"""Tests for TelegramAdapter (Task 3b)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import Agent, Channel, ChannelMode, ChannelStatus, ChannelType
from core.adapters.base import IngestPayload, OutboundMessage
from adapters.telegram.adapter import TelegramAdapter, _token_hash

FIXTURES = Path(__file__).parent / "fixtures"

BOT_TOKEN = "555000555:AABBCCDDEEFFaabbccddeeff_testtoken"
BOT_TOKEN_HASH = _token_hash(BOT_TOKEN)
BOT_USERNAME = "testbot"
BOT_ID = 555000555


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def adapter():
    return TelegramAdapter()


@pytest.fixture
def tg_channel():
    return Channel(
        channel_id="chan_tg_TEST01",
        agent_id="agt_1",
        org_id="org_X",
        channel=ChannelType.TELEGRAM,
        mode=ChannelMode.PROVISION,
        config={
            "bot_username": BOT_USERNAME,
            "bot_id": BOT_ID,
            "token_hash": BOT_TOKEN_HASH,
        },
        address_index_value=f"token:{BOT_TOKEN_HASH}",
        status=ChannelStatus.ACTIVE,
    )


# ── Test 1: channel_name and supports_modes ──────────────────────────────────

def test_channel_name_and_modes(adapter):
    assert adapter.channel_name == "telegram"
    assert adapter.supports_modes == ["provision"]


# ── Test 2: provision validates token and registers webhook ─────────────────

def test_provision_registers_webhook(adapter, agentcomms_table):
    agent = Agent(agent_id="agt_1", org_id="org_X", name="TestBot")

    mock_client = MagicMock()
    mock_client.get_me.return_value = {
        "id": BOT_ID,
        "username": BOT_USERNAME,
        "first_name": "TestBot",
        "is_bot": True,
    }
    mock_client.set_webhook.return_value = True

    with patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table), \
         patch("adapters.telegram.adapter.TelegramBotClient", return_value=mock_client), \
         patch("adapters.telegram.adapter.store_bot_token") as mock_store:
        result = adapter.provision(agent=agent, config={"bot_token": BOT_TOKEN})

    assert result.status == "active"
    assert result.details["bot_username"] == BOT_USERNAME
    assert result.details["bot_id"] == BOT_ID
    # token_hash is first 16 hex chars of sha256(BOT_TOKEN)
    assert result.details["token_hash"] == BOT_TOKEN_HASH
    assert len(result.details["token_hash"]) == 16

    # Webhook URL should include token_hash
    webhook_call_args = mock_client.set_webhook.call_args
    webhook_url = webhook_call_args[0][0] if webhook_call_args[0] else webhook_call_args[1].get("url")
    assert BOT_TOKEN_HASH in webhook_url
    assert "/webhooks/telegram/" in webhook_url

    mock_store.assert_called_once()


# ── Test 3: ingest private chat → is_dm=True ────────────────────────────────

def test_ingest_private_chat_is_dm(adapter, agentcomms_table, repo_fixture, tg_channel):
    repo_fixture.put_channel(tg_channel)

    update = load_fixture("update_private.json")
    payload = IngestPayload(
        source="api_gateway",
        headers={"x-telegram-bot-api-secret-token": BOT_TOKEN_HASH},
        body=update,
        path_params={"token_hash": BOT_TOKEN_HASH},
    )

    with patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table):
        msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.is_dm is True
    assert msg.channel.value == "telegram"
    assert msg.body_text == "Hello bot, I need help!"
    assert msg.channel_native["chat_type"] == "private"


# ── Test 4: ingest group @mention → is_dm=True ──────────────────────────────

def test_ingest_group_mention_is_dm(adapter, agentcomms_table, repo_fixture, tg_channel):
    repo_fixture.put_channel(tg_channel)

    update = load_fixture("update_group_mention.json")
    payload = IngestPayload(
        source="api_gateway",
        headers={"x-telegram-bot-api-secret-token": BOT_TOKEN_HASH},
        body=update,
        path_params={"token_hash": BOT_TOKEN_HASH},
    )

    with patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table):
        msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.is_dm is True
    assert msg.channel_native["chat_type"] == "supergroup"


# ── Test 5: ingest group noise → is_dm=False ────────────────────────────────

def test_ingest_group_noise_not_dm(adapter, agentcomms_table, repo_fixture, tg_channel):
    repo_fixture.put_channel(tg_channel)

    update = load_fixture("update_group_noise.json")
    payload = IngestPayload(
        source="api_gateway",
        headers={"x-telegram-bot-api-secret-token": BOT_TOKEN_HASH},
        body=update,
        path_params={"token_hash": BOT_TOKEN_HASH},
    )

    with patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table):
        msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.is_dm is False
    assert msg.body_text == "Hey everyone, how's it going?"


# ── Test 6: ingest reply-to-bot in group → is_dm=True ───────────────────────

def test_ingest_reply_to_bot_is_dm(adapter, agentcomms_table, repo_fixture, tg_channel):
    repo_fixture.put_channel(tg_channel)

    update = load_fixture("update_reply_to_bot.json")
    payload = IngestPayload(
        source="api_gateway",
        headers={"x-telegram-bot-api-secret-token": BOT_TOKEN_HASH},
        body=update,
        path_params={"token_hash": BOT_TOKEN_HASH},
    )

    with patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table):
        msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.is_dm is True
    assert msg.channel_native["reply_to_message_id"] == 999


# ── Test 7: invalid secret_token → ingest returns None ──────────────────────

def test_ingest_invalid_secret_drops(adapter, agentcomms_table, repo_fixture, tg_channel):
    repo_fixture.put_channel(tg_channel)

    update = load_fixture("update_private.json")
    payload = IngestPayload(
        source="api_gateway",
        headers={"x-telegram-bot-api-secret-token": "WRONG_SECRET"},
        body=update,
        path_params={"token_hash": BOT_TOKEN_HASH},
    )

    with patch("adapters.telegram.adapter._get_table", return_value=agentcomms_table):
        msg = adapter.ingest(payload=payload)

    assert msg is None


# ── Test 8: send to private chat ────────────────────────────────────────────

def test_send_to_private_chat(adapter, tg_channel):
    mock_client = MagicMock()
    mock_client.send_message.return_value = {
        "message_id": 42,
        "chat": {"id": 123456789, "type": "private"},
        "text": "Hello from agent",
    }

    message = OutboundMessage(
        to="telegram:chat:123456789",
        body_text="Hello from agent",
    )

    with patch("adapters.telegram.adapter.get_bot_token", return_value=BOT_TOKEN), \
         patch("adapters.telegram.adapter.TelegramBotClient", return_value=mock_client):
        result = adapter.send(channel=tg_channel, message=message)

    assert result.status == "sent"
    assert result.channel_native_id == "42"
    mock_client.send_message.assert_called_once_with(
        chat_id=123456789,
        text="Hello from agent",
        parse_mode=None,
        reply_to_message_id=None,
    )


# ── Test 9: send with HTML parse_mode ───────────────────────────────────────

def test_send_with_html_formatting(adapter, tg_channel):
    mock_client = MagicMock()
    mock_client.send_message.return_value = {"message_id": 99}

    message = OutboundMessage(
        to="telegram:user:123456789",
        body_text="Hello bold",
        body_html="Hello <b>bold</b>",
    )

    with patch("adapters.telegram.adapter.get_bot_token", return_value=BOT_TOKEN), \
         patch("adapters.telegram.adapter.TelegramBotClient", return_value=mock_client):
        result = adapter.send(channel=tg_channel, message=message)

    assert result.status == "sent"
    mock_client.send_message.assert_called_once()
    call_kwargs = mock_client.send_message.call_args[1]
    assert call_kwargs["parse_mode"] == "HTML"


# ── Test 10: teardown deletes webhook and SSM token ─────────────────────────

def test_teardown_deletes_webhook_and_token(adapter, tg_channel):
    mock_client = MagicMock()
    mock_client.delete_webhook.return_value = True

    with patch("adapters.telegram.adapter.get_bot_token", return_value=BOT_TOKEN), \
         patch("adapters.telegram.adapter.TelegramBotClient", return_value=mock_client), \
         patch("adapters.telegram.adapter.delete_bot_token") as mock_delete:
        adapter.teardown(channel=tg_channel)

    mock_client.delete_webhook.assert_called_once()
    mock_delete.assert_called_once_with("chan_tg_TEST01")


# ── Test 11: health_check returns ok=True when getMe succeeds ───────────────

def test_health_check_ok(adapter, tg_channel):
    mock_client = MagicMock()
    mock_client.get_me.return_value = {
        "id": BOT_ID,
        "username": BOT_USERNAME,
        "is_bot": True,
    }

    with patch("adapters.telegram.adapter.get_bot_token", return_value=BOT_TOKEN), \
         patch("adapters.telegram.adapter.TelegramBotClient", return_value=mock_client):
        status = adapter.health_check(channel=tg_channel)

    assert status.ok is True
    assert status.error is None
