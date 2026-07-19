# tests/api/test_tenant_isolation.py
"""Cross-tenant isolation (IDOR) tests for per-agent API handlers.

Every per-agent route must gate on ``require_agent`` so a caller holding an
org-A key can NEVER read, mutate, or send on an agent that lives in org-B.
The expected response for a foreign agent is 404 (indistinguishable from
"does not exist") — never 200, and never a side effect (no send).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    MessageDirection, MessageStatus, Organization, OrgPlan, Party,
    UnifiedMessage,
)
from core.data.repo import Repo


# ---------------------------------------------------------------------------
# Fixture: two orgs, each with one agent. org_A is the attacker; org_B victim.
# ---------------------------------------------------------------------------

@pytest.fixture
def two_orgs(agentcomms_table, ses_client, s3_buckets):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_A", name="Attacker", plan=OrgPlan.FREE))
    repo.put_organization(Organization(org_id="org_B", name="Victim", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_A", org_id="org_A", name="attacker-bot"))
    repo.put_agent(Agent(agent_id="agt_B", org_id="org_B", name="victim-bot"))
    # Victim agent has an active email channel + a DM message in its inbox.
    repo.put_channel(Channel(
        channel_id="chan_em_B", agent_id="agt_B", org_id="org_B",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "victim@agentcomms.dev"},
        address_index_value="victim@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    ))
    repo.put_message(UnifiedMessage(
        message_id="msg_secret",
        agent_id="agt_B", org_id="org_B", channel_id="chan_em_B",
        channel=ChannelType.EMAIL,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address="alice@x.com"),
        to=[Party(address="victim@agentcomms.dev")],
        body_text="top secret invoice",
        subject="secret",
        thread_key="thr_secret",
        is_dm=True,
        received_at=datetime(2026, 4, 17, 12, tzinfo=timezone.utc),
    ))
    return repo


def _event(method, path, path_params=None, body=None, org_id="org_A", scope="org"):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "headers": {"Authorization": "Bearer test"},
        "requestContext": {"authorizer": {
            "org_id": org_id, "scope": scope,
            "agent_id": None, "channel_id": None, "api_key_id": "k_A",
        }},
    }


# ---------------------------------------------------------------------------
# messages_handler
# ---------------------------------------------------------------------------

def test_messages_get_inbox_cross_tenant_denied(two_orgs):
    from core.api.messages_handler import handler
    resp = handler(_event(
        "GET", "/v1/agents/agt_B/messages", path_params={"agent_id": "agt_B"},
    ), None)
    assert resp["statusCode"] == 404
    # The victim's message must NOT leak in the body.
    assert "secret" not in resp["body"]


def test_messages_post_send_cross_tenant_denied_and_no_send(two_orgs, monkeypatch):
    from core.api.messages_handler import handler
    from adapters.email.adapter import EmailAdapter

    sent: list = []

    def fake_send(self, *, channel, message):  # pragma: no cover - must not run
        sent.append(message)
        from core.adapters.base import SendResult
        return SendResult(channel_native_id="x", status="sent")

    monkeypatch.setattr(EmailAdapter, "send", fake_send)

    resp = handler(_event(
        "POST", "/v1/agents/agt_B/messages",
        path_params={"agent_id": "agt_B"},
        body={"to": "alice@x.com", "body": "impersonation attempt"},
    ), None)
    assert resp["statusCode"] == 404
    # The critical assertion: no message was ever sent as the victim.
    assert sent == []


def test_messages_own_agent_allowed(two_orgs):
    """Positive control: org_B key can read its own agent's inbox."""
    from core.api.messages_handler import handler
    resp = handler(_event(
        "GET", "/v1/agents/agt_B/messages", path_params={"agent_id": "agt_B"},
        org_id="org_B",
    ), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert any(m["message_id"] == "msg_secret" for m in body["messages"])


# ---------------------------------------------------------------------------
# ai_handler
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["categorize", "extract", "summarize", "search"])
def test_ai_cross_tenant_denied(two_orgs, route):
    from core.api.ai_handler import handler
    resp = handler(_event(
        "POST", f"/v1/agents/agt_B/ai/{route}",
        path_params={"agent_id": "agt_B"},
        body={"message_id": "msg_secret", "query": "secret",
              "schema": {"type": "object"}},
    ), None)
    assert resp["statusCode"] == 404


def test_ai_categorize_does_not_write_foreign_labels(two_orgs):
    """The IDOR write path (_handle_categorize) must not touch a foreign msg."""
    from core.api.ai_handler import handler
    with patch("core.ai.categorize.invoke_model") as mock_invoke:
        resp = handler(_event(
            "POST", "/v1/agents/agt_B/ai/categorize",
            path_params={"agent_id": "agt_B"},
            body={"message_id": "msg_secret", "labels": ["spam"]},
        ), None)
    assert resp["statusCode"] == 404
    # The model must never even be invoked on the victim's message.
    mock_invoke.assert_not_called()


def test_ai_summarize_foreign_thread_via_own_agent_denied(two_orgs):
    """Attacker passes their OWN agent_id but the victim's thread_key."""
    from core.api.ai_handler import handler
    resp = handler(_event(
        "POST", "/v1/agents/agt_A/ai/summarize",
        path_params={"agent_id": "agt_A"},
        body={"thread_key": "thr_secret"},
    ), None)
    # Gate passes (agt_A is owned) but the thread is scoped to agt_A → empty → 404.
    assert resp["statusCode"] == 404


# ---------------------------------------------------------------------------
# threads_handler
# ---------------------------------------------------------------------------

def test_threads_list_cross_tenant_denied(two_orgs):
    from core.api.threads_handler import handler
    resp = handler(_event(
        "GET", "/v1/agents/agt_B/threads", path_params={"agent_id": "agt_B"},
    ), None)
    assert resp["statusCode"] == 404


def test_threads_get_cross_tenant_denied(two_orgs):
    from core.api.threads_handler import handler
    resp = handler(_event(
        "GET", "/v1/agents/agt_B/threads/thr_secret",
        path_params={"agent_id": "agt_B", "thread_id": "thr_secret"},
    ), None)
    assert resp["statusCode"] == 404
    assert "secret" not in resp["body"]


def test_threads_foreign_thread_via_own_agent_denied(two_orgs):
    """Attacker uses their own agent_id + the victim's thread_key (GSI5 leak)."""
    from core.api.threads_handler import handler
    resp = handler(_event(
        "GET", "/v1/agents/agt_A/threads/thr_secret",
        path_params={"agent_id": "agt_A", "thread_id": "thr_secret"},
    ), None)
    assert resp["statusCode"] == 404
    assert "top secret" not in resp["body"]


# ---------------------------------------------------------------------------
# slack_native_handler
# ---------------------------------------------------------------------------

def test_slack_native_cross_tenant_denied_no_client(two_orgs, agentcomms_table):
    from core.api.slack_native_handler import handler
    # Give the victim a real Slack channel so the only thing standing between
    # the attacker and the stored OAuth token is the tenant gate.
    two_orgs.put_channel(Channel(
        channel_id="chan_sl_B", agent_id="agt_B", org_id="org_B",
        channel=ChannelType.SLACK, mode=ChannelMode.BRIDGE,
        config={"team_id": "T_VICTIM", "bot_user_id": "U_V"},
        status=ChannelStatus.ACTIVE,
    ))
    event = _event(
        "POST",
        "/v1/agents/agt_B/slack/workspaces/T_VICTIM/channels/C1/messages",
        {"agent_id": "agt_B", "team_id": "T_VICTIM", "channel_id": "C1"},
        body={"text": "impersonation"},
    )
    with patch("core.api.slack_native_handler._get_table", return_value=agentcomms_table), \
         patch("core.api.slack_native_handler._slack_client_for_channel") as mock_client:
        resp = handler(event, None)
    assert resp["statusCode"] == 404
    # The stored token / client must never be reached.
    mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# telegram_native_handler
# ---------------------------------------------------------------------------

def test_telegram_native_cross_tenant_denied_no_send(two_orgs, agentcomms_table):
    from core.api.telegram_native_handler import handler
    two_orgs.put_channel(Channel(
        channel_id="chan_tg_B", agent_id="agt_B", org_id="org_B",
        channel=ChannelType.TELEGRAM, mode=ChannelMode.PROVISION,
        config={"bot_username": "victimbot", "bot_id": 1, "token_hash": "h"},
        status=ChannelStatus.ACTIVE,
    ))
    event = _event(
        "POST",
        "/v1/agents/agt_B/telegram/chats/111/messages",
        {"agent_id": "agt_B", "chat_id": "111"},
        body={"text": "impersonation"},
    )
    with patch("core.api.telegram_native_handler._get_table", return_value=agentcomms_table), \
         patch("adapters.telegram.adapter.TelegramAdapter") as mock_adapter:
        resp = handler(event, None)
    assert resp["statusCode"] == 404
    # The adapter (and thus send) must never be constructed/reached.
    mock_adapter.assert_not_called()
