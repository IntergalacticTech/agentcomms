# tests/api/test_core_hardening.py
"""Tests for the non-IDOR core correctness fixes:

  - Agent PUT update route (name / metadata), gated by ownership.
  - API-key revoked / expired enforcement in the authorizer.
  - Message label persistence round-trips in the single canonical location.
  - Inbox / thread pagination surfaces an opaque next_cursor.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from core.data.models import (
    Agent, ApiKey, ApiKeyScope, ChannelType, MessageDirection, MessageStatus,
    Organization, OrgPlan, Party, UnifiedMessage,
)
from core.data.repo import Repo


# ---------------------------------------------------------------------------
# Agent PUT update
# ---------------------------------------------------------------------------

@pytest.fixture
def agent_repo(agentcomms_table):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_1", name="Org1", plan=OrgPlan.FREE))
    repo.put_organization(Organization(org_id="org_2", name="Org2", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_1", name="original",
                         metadata={"k": "v"}))
    repo.put_agent(Agent(agent_id="agt_2", org_id="org_2", name="other"))
    return repo


def _event(method, path, path_params=None, body=None, org_id="org_1"):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {
            "org_id": org_id, "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


def test_agent_put_updates_name_and_metadata(agent_repo, agentcomms_table):
    from core.api.agents_handler import handler
    resp = handler(_event(
        "PUT", "/v1/agents/agt_1", path_params={"agent_id": "agt_1"},
        body={"name": "renamed", "metadata": {"team": "growth"}},
    ), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["name"] == "renamed"
    assert body["metadata"] == {"team": "growth"}
    # Persisted
    reloaded = agent_repo.get_agent(org_id="org_1", agent_id="agt_1")
    assert reloaded.name == "renamed"
    assert reloaded.metadata == {"team": "growth"}


def test_agent_put_partial_update_keeps_other_fields(agent_repo):
    from core.api.agents_handler import handler
    resp = handler(_event(
        "PUT", "/v1/agents/agt_1", path_params={"agent_id": "agt_1"},
        body={"name": "just-name"},
    ), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["name"] == "just-name"
    # metadata untouched
    assert body["metadata"] == {"k": "v"}


def test_agent_put_cross_tenant_denied(agent_repo):
    from core.api.agents_handler import handler
    resp = handler(_event(
        "PUT", "/v1/agents/agt_2", path_params={"agent_id": "agt_2"},
        body={"name": "hijack"}, org_id="org_1",
    ), None)
    assert resp["statusCode"] == 404
    # agent_2 name unchanged
    assert agent_repo.get_agent(org_id="org_2", agent_id="agt_2").name == "other"


def test_agent_put_empty_name_rejected(agent_repo):
    from core.api.agents_handler import handler
    resp = handler(_event(
        "PUT", "/v1/agents/agt_1", path_params={"agent_id": "agt_1"},
        body={"name": ""},
    ), None)
    assert resp["statusCode"] == 400


# ---------------------------------------------------------------------------
# API-key lifecycle enforcement
# ---------------------------------------------------------------------------

def _put_key(repo, raw, *, revoked=False, expires_at=None):
    key_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    repo.put_organization(Organization(org_id="org_K", name="K", plan=OrgPlan.FREE))
    key = ApiKey(
        key_id="key_1", key_hash=key_hash, org_id="org_K",
        scope=ApiKeyScope.ORG, name="test",
        revoked=revoked, expires_at=expires_at,
    )
    repo.table.put_item(Item=key.to_dynamodb_item())
    return key


def test_active_key_authorizes(agentcomms_table):
    from core.api.authorizer import authorize
    repo = Repo(agentcomms_table)
    _put_key(repo, "sk_live_active")
    ctx = authorize(
        repo=repo, raw_api_key="sk_live_active",
        requested_path="/v1/agents", requested_method="GET",
    )
    assert ctx.org_id == "org_K"


def test_revoked_key_denied(agentcomms_table):
    from core.api.authorizer import authorize, DeniedError
    repo = Repo(agentcomms_table)
    _put_key(repo, "sk_live_revoked", revoked=True)
    with pytest.raises(DeniedError):
        authorize(
            repo=repo, raw_api_key="sk_live_revoked",
            requested_path="/v1/agents", requested_method="GET",
        )


def test_expired_key_denied(agentcomms_table):
    from core.api.authorizer import authorize, DeniedError
    repo = Repo(agentcomms_table)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    _put_key(repo, "sk_live_expired", expires_at=past)
    with pytest.raises(DeniedError):
        authorize(
            repo=repo, raw_api_key="sk_live_expired",
            requested_path="/v1/agents", requested_method="GET",
        )


def test_future_expiry_key_authorizes(agentcomms_table):
    from core.api.authorizer import authorize
    repo = Repo(agentcomms_table)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    _put_key(repo, "sk_live_future", expires_at=future)
    ctx = authorize(
        repo=repo, raw_api_key="sk_live_future",
        requested_path="/v1/agents", requested_method="GET",
    )
    assert ctx.org_id == "org_K"


def test_legacy_key_without_lifecycle_fields_is_active(agentcomms_table):
    """A key item stored before the revoked/expires_at fields existed must
    still authorize (backward compatibility)."""
    from core.api.authorizer import authorize
    repo = Repo(agentcomms_table)
    raw = "sk_live_legacy"
    key_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    repo.put_organization(Organization(org_id="org_K", name="K", plan=OrgPlan.FREE))
    # Simulate a pre-migration item: no revoked / expires_at attributes at all.
    repo.table.put_item(Item={
        "PK": "ORG#org_K", "SK": f"APIKEY#{key_hash}", "entity": "api_key",
        "key_id": "key_legacy", "key_hash": key_hash, "org_id": "org_K",
        "scope": "org", "name": "legacy", "agent_id": None, "channel_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(), "last_used_at": None,
        "gsi1_pk": f"APIKEY#{key_hash}", "gsi1_sk": "ORG#org_K",
    })
    ctx = authorize(
        repo=repo, raw_api_key=raw,
        requested_path="/v1/agents", requested_method="GET",
    )
    assert ctx.org_id == "org_K"


# ---------------------------------------------------------------------------
# Label persistence round-trip
# ---------------------------------------------------------------------------

def test_labels_round_trip(agentcomms_table):
    repo = Repo(agentcomms_table)
    msg = UnifiedMessage(
        message_id="msg_lbl", agent_id="agt_1", org_id="org_1",
        channel_id="chan_1", channel=ChannelType.EMAIL,
        direction=MessageDirection.INBOUND, status=MessageStatus.RECEIVED,
        from_=Party(address="a@x.com"), body_text="hi",
        labels=["inbox", "important"], is_dm=True,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repo.put_message(msg)
    ts_ms = int(msg.received_at.timestamp() * 1000)
    reloaded = repo.get_message(
        agent_id="agt_1", received_at_ms=ts_ms, message_id="msg_lbl",
    )
    assert reloaded.labels == ["inbox", "important"]

    # update_message_labels writes the same canonical location the model reads.
    repo.update_message_labels(
        agent_id="agt_1", received_at_ms=ts_ms, message_id="msg_lbl",
        labels=["spam"],
    )
    again = repo.get_message(
        agent_id="agt_1", received_at_ms=ts_ms, message_id="msg_lbl",
    )
    assert again.labels == ["spam"]


# ---------------------------------------------------------------------------
# Pagination cursor
# ---------------------------------------------------------------------------

def test_inbox_returns_next_cursor_field(agentcomms_table, ses_client, s3_buckets):
    from core.api.messages_handler import handler
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_1", name="O", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_1", name="bot"))
    for i in range(3):
        repo.put_message(UnifiedMessage(
            message_id=f"m{i}", agent_id="agt_1", org_id="org_1",
            channel_id="chan_1", channel=ChannelType.EMAIL,
            direction=MessageDirection.INBOUND, status=MessageStatus.RECEIVED,
            from_=Party(address="a@x.com"), body_text=f"b{i}", is_dm=True,
            received_at=datetime(2026, 1, 1, 0, i, tzinfo=timezone.utc),
        ))
    ev = _event("GET", "/v1/agents/agt_1/messages",
                path_params={"agent_id": "agt_1"})
    ev["queryStringParameters"] = {"limit": "2"}
    resp = handler(ev, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "next_cursor" in body
    assert len(body["messages"]) == 2
    # The cursor is opaque but must round-trip through the repo decoder.
    from core.data.repo import decode_cursor
    assert decode_cursor(body["next_cursor"]) is not None


def test_cursor_encode_decode_roundtrip():
    from core.data.repo import encode_cursor, decode_cursor
    key = {"PK": "AGT#agt_1", "SK": "MSG#123#m1", "gsi3_pk": "x", "gsi3_sk": "y"}
    cur = encode_cursor(key)
    assert isinstance(cur, str)
    assert decode_cursor(cur) == key
    assert encode_cursor(None) is None
    assert decode_cursor(None) is None
    assert decode_cursor("not-valid-base64!!") is None
