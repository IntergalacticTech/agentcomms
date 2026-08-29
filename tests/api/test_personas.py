# tests/api/test_personas.py
"""Tests for /v1/personas/* and POST /v1/agents/{id}/personas routes.

Coverage:
  1. Create persona with explicit fields → 201, GET returns same data.
  2. List personas returns all created personas.
  3. Patch persona updates subset of fields only.
  4. Delete persona → 204; subsequent GET → 404.
  5. Associate persona with agent → 200; agent.metadata has persona_id.
  6. Generate=true with no bedrock_client → 501.
  7. Agent-scoped caller → 403.
  8. Create persona missing 'name' → 400.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core.data.models import Agent, Organization, OrgPlan
from core.data.repo import Repo
from core.api.personas_handler import handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(agentcomms_table):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_P", name="PersonaOrg", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_P1", org_id="org_P", name="TestAgent"))
    return repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(
    method: str,
    path: str,
    path_params: dict | None = None,
    body=None,
    qs: dict | None = None,
    scope: str = "org",
    agent_id: str | None = None,
):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {
                "org_id": "org_P",
                "scope": scope,
                "agent_id": agent_id,
                "channel_id": None,
                "api_key_id": "k_test",
            }
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# Test 1: Create persona with explicit fields → 201, GET returns same data
def test_create_and_get_persona(seeded):
    resp = handler(_event(
        "POST", "/v1/personas",
        body={
            "name": "Alice Smith",
            "address": "123 Main St, Springfield IL 62701",
            "dob": "1990-05-15",
            "phone": "+12175550123",
            "email": "alice@example.com",
            "metadata": {"agent_hint": "customer service"},
        },
    ), None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["name"] == "Alice Smith"
    assert body["address"] == "123 Main St, Springfield IL 62701"
    assert body["dob"] == "1990-05-15"
    assert body["phone"] == "+12175550123"
    assert body["email"] == "alice@example.com"
    assert body["metadata"]["agent_hint"] == "customer service"
    persona_id = body["persona_id"]
    assert persona_id.startswith("per_")

    # GET returns same data
    get_resp = handler(_event(
        "GET", f"/v1/personas/{persona_id}",
        path_params={"id": persona_id},
    ), None)
    assert get_resp["statusCode"] == 200
    get_body = json.loads(get_resp["body"])
    assert get_body["persona_id"] == persona_id
    assert get_body["name"] == "Alice Smith"
    assert get_body["email"] == "alice@example.com"


# Test 2: List personas
def test_list_personas(seeded):
    handler(_event("POST", "/v1/personas", body={"name": "Bob"}), None)
    handler(_event("POST", "/v1/personas", body={"name": "Carol"}), None)

    resp = handler(_event("GET", "/v1/personas"), None)
    assert resp["statusCode"] == 200
    personas = json.loads(resp["body"])["personas"]
    assert len(personas) == 2
    names = {p["name"] for p in personas}
    assert names == {"Bob", "Carol"}


# Test 3: Patch persona updates subset of fields
def test_patch_persona_updates_fields(seeded):
    create_resp = handler(_event(
        "POST", "/v1/personas",
        body={"name": "Dave Original", "phone": "+10000000000"},
    ), None)
    persona_id = json.loads(create_resp["body"])["persona_id"]

    patch_resp = handler(_event(
        "PATCH", f"/v1/personas/{persona_id}",
        path_params={"id": persona_id},
        body={"name": "Dave Updated", "metadata": {"role": "tester"}},
    ), None)
    assert patch_resp["statusCode"] == 200
    patch_body = json.loads(patch_resp["body"])
    assert patch_body["name"] == "Dave Updated"
    assert patch_body["phone"] == "+10000000000"   # unchanged
    assert patch_body["metadata"]["role"] == "tester"


# Test 4: Delete → 204; subsequent GET → 404
def test_delete_persona(seeded):
    create_resp = handler(_event("POST", "/v1/personas", body={"name": "Temp"}), None)
    persona_id = json.loads(create_resp["body"])["persona_id"]

    del_resp = handler(_event(
        "DELETE", f"/v1/personas/{persona_id}",
        path_params={"id": persona_id},
    ), None)
    assert del_resp["statusCode"] == 204

    get_resp = handler(_event(
        "GET", f"/v1/personas/{persona_id}",
        path_params={"id": persona_id},
    ), None)
    assert get_resp["statusCode"] == 404


# Test 5: Associate persona with agent → 200; agent.metadata has persona_id
def test_associate_persona_with_agent(seeded):
    create_resp = handler(_event("POST", "/v1/personas", body={"name": "Eve"}), None)
    persona_id = json.loads(create_resp["body"])["persona_id"]

    assoc_resp = handler(_event(
        "POST", "/v1/agents/agt_P1/personas",
        path_params={"agent_id": "agt_P1"},
        body={"persona_id": persona_id},
    ), None)
    assert assoc_resp["statusCode"] == 200
    assoc_body = json.loads(assoc_resp["body"])
    assert assoc_body["metadata"]["persona_id"] == persona_id
    assert assoc_body["agent_id"] == "agt_P1"


# Test 6: generate=true but no bedrock_client → 501
def test_generate_without_bedrock_returns_501(seeded):
    with patch(
        "core.api.personas_handler._generate_persona_fields",
        side_effect=ImportError("generation not enabled - missing Bedrock"),
    ):
        resp = handler(_event("POST", "/v1/personas", body={"generate": True}), None)
    assert resp["statusCode"] == 501
    assert "generation not enabled" in json.loads(resp["body"])["error"].lower()


# Test 7: Agent-scoped caller → 403 on any route
def test_agent_scoped_caller_is_forbidden(seeded):
    for method, path, pp, body in [
        ("GET",    "/v1/personas",          {},              None),
        ("POST",   "/v1/personas",          {},              {"name": "X"}),
        ("GET",    "/v1/personas/fake_id",  {"id": "fake_id"}, None),
        ("DELETE", "/v1/personas/fake_id",  {"id": "fake_id"}, None),
    ]:
        resp = handler(_event(
            method, path,
            path_params=pp,
            body=body,
            scope="agent",
            agent_id="agt_P1",
        ), None)
        assert resp["statusCode"] == 403, (
            f"Expected 403 for {method} {path} with agent scope, got {resp['statusCode']}"
        )


# Test 8: Create missing 'name' → 400
def test_create_missing_name_returns_400(seeded):
    resp = handler(_event("POST", "/v1/personas", body={"phone": "+1555"}), None)
    assert resp["statusCode"] == 400
    assert "name" in json.loads(resp["body"])["error"].lower()
