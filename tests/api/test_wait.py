# tests/api/test_wait.py
"""Tests for POST /v1/agents/{id}/wait handler."""
import json
from datetime import datetime, timedelta, timezone
import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    MessageDirection, MessageStatus, Organization, OrgPlan, Party, UnifiedMessage,
)
from core.data.repo import Repo
import core.api.wait_handler as _wait_mod
from core.api.wait_handler import handler


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Prevent real sleeping in all wait tests."""
    monkeypatch.setitem(_wait_mod._clock, "sleep", lambda s: None)


@pytest.fixture
def fixture(agentcomms_table):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_X", name="Acme", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="bot"))
    repo.put_channel(Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        status=ChannelStatus.ACTIVE,
    ))
    return repo


def _event(agent_id="agt_1", body=None):
    return {
        "httpMethod": "POST",
        "path": f"/v1/agents/{agent_id}/wait",
        "pathParameters": {"agent_id": agent_id},
        "queryStringParameters": {},
        "body": json.dumps(body) if body is not None else "{}",
        "requestContext": {"authorizer": {
            "org_id": "org_X", "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


def _seed_message(repo, *, msg_id="msg_test", received_at=None, channel=ChannelType.EMAIL,
                  from_addr="sender@x.com"):
    if received_at is None:
        received_at = datetime(2000, 1, 1, tzinfo=timezone.utc)  # very old — always in the past
    repo.put_message(UnifiedMessage(
        message_id=msg_id,
        agent_id="agt_1", org_id="org_X", channel_id="chan_em_1",
        channel=channel,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address=from_addr),
        to=[Party(address="bot@agentcomms.dev")],
        body_text="test body",
        is_dm=True,
        received_at=received_at,
    ))


def test_wait_returns_message_seeded_before_start(fixture, monkeypatch):
    """When a message already exists (received before the poll begins), it is returned immediately."""
    # Seed a message far in the past
    _seed_message(fixture, msg_id="msg_pre", received_at=datetime(2000, 1, 1, tzinfo=timezone.utc))

    # Make _clock["now"] return a time AFTER the message, so `since` < message.received_at is false
    # Actually the logic queries since=start, so we need the message's received_at >= since.
    # Easiest approach: make now() return a time before the message timestamp so since is before it.
    fixed_now = datetime(1999, 12, 31, tzinfo=timezone.utc)
    monkeypatch.setitem(_wait_mod._clock, "now", lambda: fixed_now)

    resp = handler(_event(body={"timeout_sec": 1, "poll_interval": 0}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["message_id"] == "msg_pre"


def test_wait_returns_408_when_no_message_arrives(fixture, monkeypatch):
    """With no messages and timeout=0, returns 408 immediately."""
    # Make elapsed immediately exceed timeout
    start_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    call_count = [0]

    def fake_now():
        call_count[0] += 1
        # First call: start time; second call (elapsed check): well past timeout
        if call_count[0] <= 1:
            return start_time
        return start_time.replace(hour=13)  # 1 hour later → timeout exceeded

    monkeypatch.setitem(_wait_mod._clock, "now", fake_now)

    resp = handler(_event(body={"timeout_sec": 1, "poll_interval": 0}), None)
    assert resp["statusCode"] == 408
    body = json.loads(resp["body"])
    assert "timeout" in body["error"].lower()


def test_wait_channel_filter_restricts_correctly(fixture, monkeypatch):
    """filter channel=sms does not return email messages."""
    # Seed an email message
    _seed_message(fixture, msg_id="msg_email", received_at=datetime(2000, 1, 1, tzinfo=timezone.utc))

    # now() returns time before message so since filter passes
    fixed_now = datetime(1999, 12, 31, tzinfo=timezone.utc)
    call_count = [0]

    def fake_now():
        call_count[0] += 1
        if call_count[0] <= 1:
            return fixed_now
        # After first poll fails (email filtered out by channel=sms), timeout
        return fixed_now.replace(year=2100)

    monkeypatch.setitem(_wait_mod._clock, "now", fake_now)

    resp = handler(_event(body={"channel": "sms", "timeout_sec": 1, "poll_interval": 0}), None)
    # Email message should be filtered out → timeout
    assert resp["statusCode"] == 408
