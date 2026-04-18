# tests/api/test_messages.py
import json
from datetime import datetime, timedelta, timezone
import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType, MessageDirection,
    MessageStatus, Organization, OrgPlan, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.api.messages_handler import handler


@pytest.fixture
def fixture(agentcomms_table, ses_client, s3_buckets):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_X", name="Acme", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="bot"))
    repo.put_channel(Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    ))
    # Seed 3 inbound messages: 2 DMs, 1 non-DM
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    for i, is_dm in enumerate([True, True, False]):
        repo.put_message(UnifiedMessage(
            message_id=f"msg_{i}",
            agent_id="agt_1", org_id="org_X", channel_id="chan_em_1",
            channel=ChannelType.EMAIL,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            from_=Party(address="alice@x.com"),
            to=[Party(address="bot@agentcomms.dev")],
            body_text=f"hi {i}",
            is_dm=is_dm,
            received_at=t0 + timedelta(minutes=i),
        ))
    return repo


def _event(method, path, path_params=None, body=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
        "requestContext": {"authorizer": {
            "org_id": "org_X", "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


def test_get_unified_inbox_returns_dms_only(fixture):
    resp = handler(_event(
        "GET", "/v1/agents/agt_1/messages", path_params={"agent_id": "agt_1"},
    ), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["messages"]) == 2          # is_dm=True only
    assert body["messages"][0]["message_id"] == "msg_1"  # newest first


def test_get_unified_inbox_since_filter(fixture):
    ev = _event(
        "GET", "/v1/agents/agt_1/messages", path_params={"agent_id": "agt_1"},
    )
    ev["queryStringParameters"] = {"since": "2026-04-17T12:00:30Z"}
    resp = handler(ev, None)
    body = json.loads(resp["body"])
    # msg_1 is at 12:01; msg_0 is at 12:00 → only msg_1 qualifies
    assert [m["message_id"] for m in body["messages"]] == ["msg_1"]


def test_send_message_with_address_inference(fixture, monkeypatch):
    # Mock the EmailAdapter.send to avoid real SES
    sent = {}
    from adapters.email.adapter import EmailAdapter
    from core.adapters.base import SendResult
    def fake_send(self, *, channel, message):
        sent["to"] = message.to
        sent["body"] = message.body_text
        return SendResult(channel_native_id="ses-id-123", status="sent")
    monkeypatch.setattr(EmailAdapter, "send", fake_send)

    resp = handler(_event(
        "POST", "/v1/agents/agt_1/messages",
        path_params={"agent_id": "agt_1"},
        body={"to": "alice@example.com", "body": "hello from hub"},
    ), None)
    assert resp["statusCode"] == 201
    assert sent["to"] == "alice@example.com"
    assert sent["body"] == "hello from hub"


def test_send_message_explicit_channel_override(fixture, monkeypatch):
    from adapters.email.adapter import EmailAdapter
    from core.adapters.base import SendResult
    monkeypatch.setattr(
        EmailAdapter, "send",
        lambda self, *, channel, message: SendResult(channel_native_id="x", status="sent"),
    )
    resp = handler(_event(
        "POST", "/v1/agents/agt_1/messages",
        path_params={"agent_id": "agt_1"},
        body={"channel": "email", "to": {"address": "alice@x.com"},
              "body_text": "hi", "subject": "hi"},
    ), None)
    assert resp["statusCode"] == 201


def test_send_fails_when_no_channel_configured(fixture):
    # Try to send SMS when no SMS channel exists
    resp = handler(_event(
        "POST", "/v1/agents/agt_1/messages",
        path_params={"agent_id": "agt_1"},
        body={"to": "+15551234567", "body": "hi"},
    ), None)
    assert resp["statusCode"] == 409
    body = json.loads(resp["body"])
    assert "no sms channel" in body["error"].lower()


def test_get_single_message(fixture):
    ev = _event(
        "GET", "/v1/agents/agt_1/messages/msg_0",
        path_params={"agent_id": "agt_1", "message_id": "msg_0"},
    )
    ev["queryStringParameters"] = {"received_at_ms": str(int(
        datetime(2026, 4, 17, 12, tzinfo=timezone.utc).timestamp() * 1000
    ))}
    resp = handler(ev, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["message_id"] == "msg_0"
