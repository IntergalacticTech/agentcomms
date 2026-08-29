# tests/api/test_threads.py
"""Tests for /v1/agents/{id}/threads/* handler."""
import json
from datetime import datetime, timedelta, timezone
import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    MessageDirection, MessageStatus, Organization, OrgPlan, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.api.threads_handler import handler


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
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    # Thread A: 3 messages
    for i in range(3):
        repo.put_message(UnifiedMessage(
            message_id=f"msg_a{i}",
            agent_id="agt_1", org_id="org_X", channel_id="chan_em_1",
            channel=ChannelType.EMAIL,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            from_=Party(address="alice@x.com"),
            to=[Party(address="bot@agentcomms.dev")],
            body_text=f"thread A message {i}",
            thread_key="thr_aaa",
            is_dm=True,
            received_at=t0 + timedelta(minutes=i),
        ))
    # Thread B: 2 messages
    for i in range(2):
        repo.put_message(UnifiedMessage(
            message_id=f"msg_b{i}",
            agent_id="agt_1", org_id="org_X", channel_id="chan_em_1",
            channel=ChannelType.EMAIL,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            from_=Party(address="bob@x.com"),
            to=[Party(address="bot@agentcomms.dev")],
            body_text=f"thread B message {i}",
            thread_key="thr_bbb",
            is_dm=True,
            received_at=t0 + timedelta(hours=1, minutes=i),
        ))
    # One message with no thread_key (should not appear in threads list)
    repo.put_message(UnifiedMessage(
        message_id="msg_no_thread",
        agent_id="agt_1", org_id="org_X", channel_id="chan_em_1",
        channel=ChannelType.EMAIL,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address="carol@x.com"),
        to=[Party(address="bot@agentcomms.dev")],
        body_text="no thread",
        thread_key=None,
        is_dm=True,
        received_at=t0,
    ))
    return repo


def _event(method, path, path_params=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": {},
        "body": None,
        "requestContext": {"authorizer": {
            "org_id": "org_X", "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


def test_list_threads_returns_distinct_thread_keys(fixture):
    """Listing threads returns 2 distinct thread groups (A and B) — not 5 individual messages."""
    resp = handler(_event("GET", "/v1/agents/agt_1/threads",
                          path_params={"agent_id": "agt_1"}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    thread_keys = {t["thread_key"] for t in body["threads"]}
    assert thread_keys == {"thr_aaa", "thr_bbb"}
    # Thread A has 3 messages
    thr_a = next(t for t in body["threads"] if t["thread_key"] == "thr_aaa")
    assert thr_a["message_count"] == 3
    # Thread B has 2 messages
    thr_b = next(t for t in body["threads"] if t["thread_key"] == "thr_bbb")
    assert thr_b["message_count"] == 2


def test_get_thread_returns_messages_chronologically(fixture):
    """GET /threads/{thread_id} returns all messages in chronological order."""
    resp = handler(_event("GET", "/v1/agents/agt_1/threads/thr_aaa",
                          path_params={"agent_id": "agt_1", "thread_id": "thr_aaa"}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["thread_key"] == "thr_aaa"
    msgs = body["messages"]
    assert len(msgs) == 3
    # Verify chronological order (oldest first — GSI5 ScanIndexForward=True)
    received_ats = [m["received_at"] for m in msgs]
    assert received_ats == sorted(received_ats)
    # Message IDs in order
    assert [m["message_id"] for m in msgs] == ["msg_a0", "msg_a1", "msg_a2"]
