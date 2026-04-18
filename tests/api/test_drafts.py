# tests/api/test_drafts.py
"""Tests for /v1/agents/{id}/drafts/* handler."""
import json
import pytest

from core.data.models import Agent, Organization, OrgPlan
from core.data.repo import Repo
from core.api.drafts_handler import handler


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


def test_create_draft(fixture):
    """POST /drafts creates a draft with channel discriminator."""
    resp = handler(_event(
        "POST", "/v1/agents/agt_1/drafts",
        path_params={"agent_id": "agt_1"},
        body={
            "channel": "email",
            "to": [{"address": "alice@x.com"}],
            "subject": "Hello",
            "body_text": "Draft body",
        },
    ), None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["channel"] == "email"
    assert body["draft_id"].startswith("drf_")
    assert body["body_text"] == "Draft body"
    assert body["to"] == [{"address": "alice@x.com"}]


def test_update_draft_body_text(fixture):
    """PATCH /drafts/{id} updates body_text."""
    # Create first
    create_resp = handler(_event(
        "POST", "/v1/agents/agt_1/drafts",
        path_params={"agent_id": "agt_1"},
        body={"channel": "email", "body_text": "Original"},
    ), None)
    draft_id = json.loads(create_resp["body"])["draft_id"]

    # Then update
    patch_resp = handler(_event(
        "PATCH", f"/v1/agents/agt_1/drafts/{draft_id}",
        path_params={"agent_id": "agt_1", "draft_id": draft_id},
        body={"body_text": "Updated body"},
    ), None)
    assert patch_resp["statusCode"] == 200
    body = json.loads(patch_resp["body"])
    assert body["body_text"] == "Updated body"


def test_list_drafts_returns_all_for_agent(fixture):
    """GET /drafts returns all drafts for an agent."""
    # Create 3 drafts
    for i in range(3):
        handler(_event(
            "POST", "/v1/agents/agt_1/drafts",
            path_params={"agent_id": "agt_1"},
            body={"channel": "email", "body_text": f"Draft {i}"},
        ), None)

    resp = handler(_event("GET", "/v1/agents/agt_1/drafts",
                          path_params={"agent_id": "agt_1"}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["drafts"]) == 3


def test_delete_draft(fixture):
    """DELETE /drafts/{id} removes the draft."""
    create_resp = handler(_event(
        "POST", "/v1/agents/agt_1/drafts",
        path_params={"agent_id": "agt_1"},
        body={"channel": "sms", "body_text": "SMS draft"},
    ), None)
    draft_id = json.loads(create_resp["body"])["draft_id"]

    del_resp = handler(_event(
        "DELETE", f"/v1/agents/agt_1/drafts/{draft_id}",
        path_params={"agent_id": "agt_1", "draft_id": draft_id},
    ), None)
    assert del_resp["statusCode"] == 204

    # Confirm it's gone
    list_resp = handler(_event("GET", "/v1/agents/agt_1/drafts",
                               path_params={"agent_id": "agt_1"}), None)
    body = json.loads(list_resp["body"])
    assert not any(d["draft_id"] == draft_id for d in body["drafts"])
