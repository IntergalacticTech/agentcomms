# adapters/slack/tests/test_normalize.py
"""Tests for Slack payload → UnifiedMessage normalization (Task 1c)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.slack.normalize import parse_slack_event

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


CHANNEL_ID = "chan_sl_1"
AGENT_ID = "agt_1"
ORG_ID = "org_X"
BOT_USER_ID = "U0123456789"


# ── Test 1: DM event → is_dm=True ───────────────────────────────────────────

def test_event_dm_produces_dm_message():
    payload = load_fixture("event_dm.json")
    msg = parse_slack_event(
        payload,
        channel_id=CHANNEL_ID,
        agent_id=AGENT_ID,
        org_id=ORG_ID,
        bot_user_id=BOT_USER_ID,
    )
    assert msg is not None
    assert msg.is_dm is True
    assert msg.channel.value == "slack"
    assert msg.direction.value == "inbound"
    assert msg.channel_native["channel_id"] == "D012AB3C4"
    assert msg.channel_native["event_type"] == "message"
    assert msg.channel_native["is_mention"] is False
    assert msg.body_text == "Hello, I need help with my order"
    # external_id = {team_id}:{ts}
    assert msg.external_id == "T012AB3C4:1512085950.000216"
    # from_ should reference the sender
    assert "U012AB3C4" in msg.from_.address


# ── Test 2: app_mention → is_dm=True ────────────────────────────────────────

def test_event_channel_mention_produces_dm():
    payload = load_fixture("event_channel_mention.json")
    msg = parse_slack_event(
        payload,
        channel_id=CHANNEL_ID,
        agent_id=AGENT_ID,
        org_id=ORG_ID,
        bot_user_id=BOT_USER_ID,
    )
    assert msg is not None
    assert msg.is_dm is True
    assert msg.channel_native["is_mention"] is True
    assert msg.channel_native["event_type"] == "app_mention"
    # Channel C... not D... but still DM because of app_mention type
    assert msg.channel_native["channel_id"] == "C012AB3C4"


# ── Test 3: channel noise → is_dm=False ─────────────────────────────────────

def test_event_channel_noise_not_dm():
    payload = load_fixture("event_channel_noise.json")
    msg = parse_slack_event(
        payload,
        channel_id=CHANNEL_ID,
        agent_id=AGENT_ID,
        org_id=ORG_ID,
        bot_user_id=BOT_USER_ID,
    )
    assert msg is not None
    assert msg.is_dm is False
    assert msg.channel_native["channel_id"] == "C012AB3C4"
    assert msg.body_text == "Hey everyone, just a general announcement!"


# ── Test 4: bot message → None (ignored) ────────────────────────────────────

def test_bot_message_is_ignored():
    payload = {
        "type": "event_callback",
        "team_id": "T012AB3C4",
        "event": {
            "type": "message",
            "channel": "C012AB3C4",
            "bot_id": "B012AB3C4",
            "text": "I am a bot response",
            "ts": "1512085950.000219",
        },
        "authorizations": [{"user_id": BOT_USER_ID}],
    }
    msg = parse_slack_event(
        payload,
        channel_id=CHANNEL_ID,
        agent_id=AGENT_ID,
        org_id=ORG_ID,
        bot_user_id=BOT_USER_ID,
    )
    assert msg is None


# ── Test 5: channel_native fields populated correctly ───────────────────────

def test_channel_native_fields():
    payload = load_fixture("event_dm.json")
    msg = parse_slack_event(
        payload,
        channel_id=CHANNEL_ID,
        agent_id=AGENT_ID,
        org_id=ORG_ID,
        bot_user_id=BOT_USER_ID,
    )
    native = msg.channel_native
    assert "team_id" in native
    assert "channel_id" in native
    assert "ts" in native
    assert "blocks" in native
    assert native["team_id"] == "T012AB3C4"
