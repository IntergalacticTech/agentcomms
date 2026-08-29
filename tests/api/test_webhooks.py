# tests/api/test_webhooks.py
"""Tests for /v1/agents/{id}/webhooks/* handler."""
import json
import pytest

from core.data.models import Agent, Organization, OrgPlan
from core.data.repo import Repo
from core.api.webhooks_handler import handler


@pytest.fixture
def fixture(agentcomms_table):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_X", name="Acme", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="bot"))
    return repo


def _event(method, path, path_params=None, body=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {
            "org_id": "org_X", "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


def test_create_webhook_generates_secret(fixture):
    """POST /webhooks creates a webhook and auto-generates a 64-char hex secret."""
    resp = handler(_event(
        "POST", "/v1/agents/agt_1/webhooks",
        path_params={"agent_id": "agt_1"},
        body={
            "url": "https://example.com/hook",
            "events": ["message.received", "message.sent"],
        },
    ), None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["url"] == "https://example.com/hook"
    assert body["events"] == ["message.received", "message.sent"]
    # Secret: 32 bytes = 64 hex chars
    assert "secret" in body
    assert len(body["secret"]) == 64
    assert body["webhook_id"].startswith("whk_")


def test_create_webhook_rejects_http_url(fixture):
    """POST /webhooks with http:// URL returns 400."""
    resp = handler(_event(
        "POST", "/v1/agents/agt_1/webhooks",
        path_params={"agent_id": "agt_1"},
        body={
            "url": "http://insecure.example.com/hook",
            "events": ["message.received"],
        },
    ), None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "https" in body["error"].lower()


def test_create_webhook_rejects_unknown_events(fixture):
    """POST /webhooks with invalid event names returns 400."""
    resp = handler(_event(
        "POST", "/v1/agents/agt_1/webhooks",
        path_params={"agent_id": "agt_1"},
        body={
            "url": "https://example.com/hook",
            "events": ["message.received", "not_a_real_event"],
        },
    ), None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "unknown" in body["error"].lower()
    assert "not_a_real_event" in body["error"]
