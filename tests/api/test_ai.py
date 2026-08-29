# tests/api/test_ai.py
"""Tests for /v1/agents/{id}/ai/* routes.

Coverage:
  1. Categorize valid label → 200, {label, confidence}.
  2. Categorize updates message labels in DynamoDB.
  3. Categorize invalid label first attempt → retry → fallback to "uncategorized".
  4. Extract with simple schema → 200, validated dict returned.
  5. Summarize message short → 200, non-empty summary string.
  6. Search keyword → returns messages containing the keyword.
  7. Channel-scoped caller → 403.
  8. Categorize missing message_id → 400.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch, call

import pytest

from core.data.models import (
    Agent, ChannelType, MessageDirection, MessageStatus, Organization,
    OrgPlan, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.api.ai_handler import handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(agentcomms_table):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_AI", name="AIOrg", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_AI1", org_id="org_AI", name="TestAIAgent"))
    return repo, agentcomms_table


@pytest.fixture
def message_in_db(seeded):
    """Seed a single message with body_text containing 'invoice' and return its message_id."""
    repo, table = seeded
    msg = UnifiedMessage(
        message_id="msg_test1",
        agent_id="agt_AI1",
        org_id="org_AI",
        channel_id="chan_1",
        channel=ChannelType.EMAIL,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.DELIVERED,
        from_=Party(address="sender@example.com"),
        subject="Invoice #1234",
        body_text="Please find attached invoice #1234 for $500. Due date is next Friday.",
        is_dm=True,
        received_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    repo.put_message(msg)
    return msg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(
    path: str,
    body: dict,
    path_params: dict | None = None,
    scope: str = "org",
    agent_id_param: str = "agt_AI1",
):
    return {
        "httpMethod": "POST",
        "path": path,
        "pathParameters": {**(path_params or {}), "agent_id": agent_id_param},
        "queryStringParameters": {},
        "body": json.dumps(body),
        "requestContext": {
            "authorizer": {
                "org_id": "org_AI",
                "scope": scope,
                "agent_id": agent_id_param if scope == "agent" else None,
                "channel_id": None,
                "api_key_id": "k_test",
            }
        },
    }


def _fake_categorize_invoke(model_id, prompt, *, max_tokens=1024, temperature=0.2, system=None, tools=None):
    """Returns a valid tool_use block for the 'classify' tool."""
    return {
        "content": [
            {
                "type": "tool_use",
                "name": "classify",
                "input": {"label": "invoice", "confidence": 0.95},
            }
        ],
        "model": model_id,
    }


def _fake_extract_invoke(model_id, prompt, *, max_tokens=1024, temperature=0.2, system=None, tools=None):
    """Returns a tool_use block with {total: 500.0}."""
    return {
        "content": [
            {
                "type": "tool_use",
                "name": "extract",
                "input": {"total": 500.0},
            }
        ],
        "model": model_id,
    }


def _fake_summarize_invoke(model_id, prompt, *, max_tokens=1024, temperature=0.2, system=None, tools=None):
    """Returns a text block with a short summary."""
    return {
        "content": [
            {
                "type": "text",
                "text": "Invoice #1234 for $500 due next Friday.",
            }
        ],
        "model": model_id,
    }


def _fake_invalid_label_invoke(call_count):
    """Returns tool_use with invalid label on first call, valid on second."""
    _state = {"n": 0}

    def _invoke(model_id, prompt, *, max_tokens=1024, temperature=0.2, system=None, tools=None):
        _state["n"] += 1
        if _state["n"] == 1:
            # First call: invalid label
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "classify",
                        "input": {"label": "DEFINITELY_NOT_VALID", "confidence": 0.5},
                    }
                ],
                "model": model_id,
            }
        else:
            # Second call: still invalid → forces fallback to "uncategorized"
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "classify",
                        "input": {"label": "ALSO_INVALID", "confidence": 0.3},
                    }
                ],
                "model": model_id,
            }

    return _invoke


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# Test 1: Categorize → valid label returned
def test_categorize_valid_label(message_in_db, seeded):
    with patch("core.ai.categorize.invoke_model", side_effect=_fake_categorize_invoke):
        resp = handler(_event(
            "/v1/agents/agt_AI1/ai/categorize",
            body={
                "message_id": "msg_test1",
                "labels": ["invoice", "spam", "notification"],
            },
        ), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["label"] == "invoice"
    assert body["confidence"] == pytest.approx(0.95)


# Test 2: Categorize updates message labels in DynamoDB
def test_categorize_updates_labels_in_dynamo(message_in_db, seeded, agentcomms_table):
    repo, _ = seeded
    with patch("core.ai.categorize.invoke_model", side_effect=_fake_categorize_invoke):
        resp = handler(_event(
            "/v1/agents/agt_AI1/ai/categorize",
            body={
                "message_id": "msg_test1",
                "labels": ["invoice", "spam"],
            },
        ), None)

    assert resp["statusCode"] == 200
    # Verify the DynamoDB item was updated with the label
    ts_ms = int(datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    dynamo_resp = agentcomms_table.get_item(
        Key={"PK": "AGT#agt_AI1", "SK": f"MSG#{ts_ms}#msg_test1"}
    )
    item = dynamo_resp.get("Item", {})
    # Labels should have been set
    assert "labels" in item
    assert "invoice" in item["labels"]


# Test 3: Categorize with always-invalid label → fallback to "uncategorized"
def test_categorize_invalid_label_fallback(message_in_db, seeded):
    fake = _fake_invalid_label_invoke(2)
    with patch("core.ai.categorize.invoke_model", side_effect=fake):
        resp = handler(_event(
            "/v1/agents/agt_AI1/ai/categorize",
            body={
                "message_id": "msg_test1",
                "labels": ["invoice", "spam"],
            },
        ), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["label"] == "uncategorized"
    assert body["confidence"] == 0.0


# Test 4: Extract with simple schema → validated dict returned
def test_extract_returns_validated_data(message_in_db, seeded):
    schema = {
        "type": "object",
        "properties": {
            "total": {"type": "number"},
        },
    }
    with patch("core.ai.extract.invoke_model", side_effect=_fake_extract_invoke):
        resp = handler(_event(
            "/v1/agents/agt_AI1/ai/extract",
            body={
                "message_id": "msg_test1",
                "schema": schema,
            },
        ), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "data" in body
    assert body["data"]["total"] == pytest.approx(500.0)


# Test 5: Summarize message short → returns non-empty string
def test_summarize_message_short(message_in_db, seeded):
    with patch("core.ai.summarize.invoke_model", side_effect=_fake_summarize_invoke):
        resp = handler(_event(
            "/v1/agents/agt_AI1/ai/summarize",
            body={"message_id": "msg_test1", "length": "short"},
        ), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "summary" in body
    assert len(body["summary"]) > 0
    assert "Invoice" in body["summary"] or "invoice" in body["summary"].lower()


def test_summarize_raw_text(seeded):
    with patch("core.ai.summarize.invoke_model", side_effect=_fake_summarize_invoke):
        resp = handler(_event(
            "/v1/agents/agt_AI1/ai/summarize",
            body={"text": "Invoice INV-1001 for $500 is due tomorrow.", "length": "short"},
        ), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "summary" in body
    assert "invoice" in body["summary"].lower()


# Test 6: Search keyword returns matching messages
def test_search_keyword_returns_messages(seeded, agentcomms_table):
    repo, _ = seeded
    # Seed additional messages
    for i, text in enumerate([
        "Please pay this invoice #999 for $200.",
        "Hello, how are you today?",
        "Another invoice #888 arrived.",
    ]):
        msg = UnifiedMessage(
            message_id=f"msg_srch{i}",
            agent_id="agt_AI1",
            org_id="org_AI",
            channel_id="chan_1",
            channel=ChannelType.EMAIL,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.DELIVERED,
            from_=Party(address=f"sender{i}@example.com"),
            body_text=text,
            is_dm=True,
            received_at=datetime(2024, 1, 16, i, 0, 0, tzinfo=timezone.utc),
        )
        repo.put_message(msg)

    resp = handler(_event(
        "/v1/agents/agt_AI1/ai/search",
        body={"query": "invoice", "limit": 10},
    ), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "results" in body
    # Should match "msg_srch0" and "msg_srch2" (not "msg_srch1" which has no "invoice")
    message_ids = [r["message_id"] for r in body["results"]]
    assert "msg_srch0" in message_ids
    assert "msg_srch2" in message_ids
    assert "msg_srch1" not in message_ids


# Test 7: Channel-scoped caller → 403
def test_channel_scoped_caller_is_forbidden(seeded):
    resp = handler(_event(
        "/v1/agents/agt_AI1/ai/search",
        body={"query": "test"},
        scope="channel",
    ), None)
    assert resp["statusCode"] == 403


# Test 8: Categorize missing message_id → 400
def test_categorize_missing_message_id_returns_400(seeded):
    resp = handler(_event(
        "/v1/agents/agt_AI1/ai/categorize",
        body={"labels": ["spam"]},  # no message_id
    ), None)
    assert resp["statusCode"] == 400
    assert "message_id" in json.loads(resp["body"])["error"].lower()
