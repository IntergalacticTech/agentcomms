# SPDX-License-Identifier: Apache-2.0
"""Unit tests for TelegramAdapter: UTF-16 mention detection, independent
webhook secret verification, and HTML send-body selection."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.adapters.base import OutboundMessage
from core.data.models import (
    Channel, ChannelMode, ChannelStatus, ChannelType,
)
from adapters.telegram.adapter import TelegramAdapter
from core.adapters.base import IngestPayload


def _tg_channel() -> Channel:
    return Channel(
        channel_id="chan_tg_1",
        agent_id="agt_1",
        org_id="org_1",
        channel=ChannelType.TELEGRAM,
        mode=ChannelMode.PROVISION,
        status=ChannelStatus.ACTIVE,
        config={"bot_username": "testbot", "bot_id": 999, "token_hash": "abcd" * 4},
        address_index_value="token:" + "abcd" * 4,
    )


def _group_update(text: str, entities: list[dict]) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 42,
            "chat": {"id": -100, "type": "supergroup"},
            "from": {"id": 555, "username": "alice"},
            "text": text,
            "entities": entities,
        },
    }


def _run_ingest(update: dict, *, secret: str, header_secret: str):
    channel = _tg_channel()
    fake_repo = MagicMock()
    fake_repo.lookup_channel_by_address.return_value = channel
    fake_repo.lookup_message_by_external_id.return_value = None

    adapter = TelegramAdapter()
    payload = IngestPayload(
        source="api_gateway",
        headers={"X-Telegram-Bot-Api-Secret-Token": header_secret},
        body=update,
        path_params={"token_hash": "abcd" * 4},
    )
    with patch("adapters.telegram.adapter.Repo", return_value=fake_repo), \
         patch("adapters.telegram.adapter._get_table", return_value=None), \
         patch("adapters.telegram.adapter.get_webhook_secret", return_value=secret):
        return adapter.ingest(payload=payload)


def test_mention_detection_survives_emoji_utf16_offsets():
    # "😀 @testbot hi" — the emoji is a surrogate pair (2 UTF-16 code units),
    # so Telegram reports the @mention at utf-16 offset 3, length 8. Slicing as
    # Python code points would read the wrong substring and miss the mention.
    text = "\U0001F600 @testbot hi"
    entities = [{"type": "mention", "offset": 3, "length": 8}]
    msg = _run_ingest(_group_update(text, entities), secret="s3cret", header_secret="s3cret")
    assert msg is not None
    assert msg.is_dm is True


def test_group_without_mention_is_not_dm():
    text = "just chatting"
    msg = _run_ingest(_group_update(text, []), secret="s3cret", header_secret="s3cret")
    assert msg is not None
    assert msg.is_dm is False


def test_ingest_rejects_wrong_secret_token():
    text = "\U0001F600 @testbot hi"
    entities = [{"type": "mention", "offset": 3, "length": 8}]
    msg = _run_ingest(
        _group_update(text, entities), secret="right", header_secret="wrong"
    )
    assert msg is None


def test_send_uses_html_body_when_parse_mode_html():
    captured = {}

    class FakeClient:
        def __init__(self, token):
            pass

        def send_message(self, **kwargs):
            captured.update(kwargs)
            return {"message_id": 7}

    adapter = TelegramAdapter()
    channel = _tg_channel()
    out = OutboundMessage(
        to="telegram:chat:123",
        body_text="plain text",
        body_html="<b>rich</b>",
    )
    with patch("adapters.telegram.adapter.get_bot_token", return_value="tok"), \
         patch("adapters.telegram.adapter.TelegramBotClient", FakeClient):
        result = adapter.send(channel=channel, message=out)

    assert result.status == "sent"
    assert captured["parse_mode"] == "HTML"
    # The HTML body must be sent, not the plain-text body.
    assert captured["text"] == "<b>rich</b>"


def test_send_uses_text_body_when_no_html():
    captured = {}

    class FakeClient:
        def __init__(self, token):
            pass

        def send_message(self, **kwargs):
            captured.update(kwargs)
            return {"message_id": 8}

    adapter = TelegramAdapter()
    channel = _tg_channel()
    out = OutboundMessage(to="telegram:chat:123", body_text="plain only")
    with patch("adapters.telegram.adapter.get_bot_token", return_value="tok"), \
         patch("adapters.telegram.adapter.TelegramBotClient", FakeClient):
        adapter.send(channel=channel, message=out)

    assert captured["parse_mode"] is None
    assert captured["text"] == "plain only"
