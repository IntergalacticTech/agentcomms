# adapters/telegram/tests/test_bot_client.py
"""Tests for TelegramBotClient (Task 3a)."""
from __future__ import annotations

import json
import urllib.request
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from adapters.telegram.bot_client import TelegramBotClient, TelegramAPIError


FAKE_TOKEN = "123456789:AABBCCDDEEFFaabbccddeeff"


def _make_response(data: dict, status: int = 200):
    """Create a mock urllib response."""
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(data).encode("utf-8")
    mock_resp.status = status
    return mock_resp


# ── Test 1: get_me returns bot info ──────────────────────────────────────────

def test_get_me_success():
    client = TelegramBotClient(FAKE_TOKEN)
    bot_info = {
        "id": 555000555,
        "is_bot": True,
        "first_name": "TestBot",
        "username": "testbot",
    }
    response_data = {"ok": True, "result": bot_info}

    with patch("urllib.request.urlopen", return_value=_make_response(response_data)):
        result = client.get_me()

    assert result["username"] == "testbot"
    assert result["id"] == 555000555
    assert result["is_bot"] is True


# ── Test 2: set_webhook with secret_token ────────────────────────────────────

def test_set_webhook_passes_secret_token():
    client = TelegramBotClient(FAKE_TOKEN)
    response_data = {"ok": True, "result": True}

    captured_request = {}

    def fake_urlopen(req, timeout=None):
        captured_request["url"] = req.full_url
        captured_request["body"] = json.loads(req.data)
        return _make_response(response_data)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = client.set_webhook(
            url="https://api.agentcomms.dev/webhooks/telegram/abc123",
            secret_token="abc123",
        )

    assert "setWebhook" in captured_request["url"]
    assert captured_request["body"]["url"] == "https://api.agentcomms.dev/webhooks/telegram/abc123"
    assert captured_request["body"]["secret_token"] == "abc123"


# ── Test 3: send_message with parse_mode and reply ──────────────────────────

def test_send_message_with_html_and_reply():
    client = TelegramBotClient(FAKE_TOKEN)
    sent_msg = {
        "message_id": 42,
        "chat": {"id": 123456789, "type": "private"},
        "text": "<b>Hello</b>",
    }
    response_data = {"ok": True, "result": sent_msg}

    captured_body = {}

    def fake_urlopen(req, timeout=None):
        captured_body.update(json.loads(req.data))
        return _make_response(response_data)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = client.send_message(
            chat_id=123456789,
            text="<b>Hello</b>",
            parse_mode="HTML",
            reply_to_message_id=99,
        )

    assert result["message_id"] == 42
    assert captured_body["chat_id"] == 123456789
    assert captured_body["parse_mode"] == "HTML"
    assert captured_body["reply_to_message_id"] == 99


# ── Test 4: delete_webhook succeeds ─────────────────────────────────────────

def test_delete_webhook():
    client = TelegramBotClient(FAKE_TOKEN)
    response_data = {"ok": True, "result": True}

    with patch("urllib.request.urlopen", return_value=_make_response(response_data)):
        result = client.delete_webhook()

    assert result is True


# ── Test 5: API error raises TelegramAPIError ────────────────────────────────

def test_api_error_raises():
    client = TelegramBotClient("bad_token")
    response_data = {
        "ok": False,
        "error_code": 401,
        "description": "Unauthorized",
    }

    with patch("urllib.request.urlopen", return_value=_make_response(response_data)):
        with pytest.raises(TelegramAPIError, match="Unauthorized"):
            client.get_me()


# ── Test 6: get_chat returns chat info ──────────────────────────────────────

def test_get_chat():
    client = TelegramBotClient(FAKE_TOKEN)
    chat_info = {
        "id": -1001234567890,
        "title": "Test Group",
        "type": "supergroup",
    }
    response_data = {"ok": True, "result": chat_info}

    with patch("urllib.request.urlopen", return_value=_make_response(response_data)):
        result = client.get_chat(-1001234567890)

    assert result["id"] == -1001234567890
    assert result["type"] == "supergroup"
