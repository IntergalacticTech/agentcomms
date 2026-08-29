# tests/api/test_domains.py
"""Tests for /v1/domains/* routes.

Coverage:
  1. Create domain → 201 with DKIM tokens (mock SES).
  2. List domains returns all created domains.
  3. Duplicate domain (same org) → idempotent re-register (not 409).
  4. Duplicate domain different org → 409.
  5. Zone-file output starts with "$ORIGIN domain_name.".
  6. Delete blocked when a Channel uses the domain → 409.
  7. Delete succeeds when no channel references → 204.
  8. Agent-scoped caller → 403.
  9. Create missing domain_name → 400.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import Agent, Channel, ChannelMode, ChannelStatus, ChannelType, Organization, OrgPlan
from core.data.repo import Repo
from core.api.domains_handler import handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(agentcomms_table):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_D", name="DomainOrg", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_D1", org_id="org_D", name="EmailAgent"))
    return repo


@pytest.fixture
def seeded_org2(agentcomms_table, seeded):
    """Second org in the same table for cross-org uniqueness tests."""
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_D2", name="OtherOrg", plan=OrgPlan.FREE))
    return repo


# ---------------------------------------------------------------------------
# SES mock factory
# ---------------------------------------------------------------------------

def _mock_sesv2(dkim_tokens=None):
    """Return a MagicMock that quacks like a boto3 sesv2 client."""
    if dkim_tokens is None:
        dkim_tokens = ["tok1abc", "tok2def", "tok3ghi"]

    mock = MagicMock()
    mock.create_email_identity.return_value = {
        "DkimAttributes": {"Tokens": dkim_tokens}
    }
    mock.get_email_identity.return_value = {
        "VerifiedForSendingStatus": False,
        "DkimAttributes": {"Status": "PENDING", "Tokens": dkim_tokens},
    }
    mock.delete_email_identity.return_value = {}
    # Replicate exceptions as attributes (boto3 pattern)
    mock.exceptions.AlreadyExistsException = type(
        "AlreadyExistsException", (Exception,), {}
    )
    return mock


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
    org_id: str = "org_D",
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
                "org_id": org_id,
                "scope": scope,
                "agent_id": agent_id,
                "channel_id": None,
                "api_key_id": "k_test",
            }
        },
    }


def _create_domain(domain_name: str = "example.com", org_id: str = "org_D", mock_ses=None) -> dict:
    """Helper: POST /v1/domains with a given mock SES client."""
    if mock_ses is None:
        mock_ses = _mock_sesv2()
    with patch("core.api.domains_handler._get_sesv2", return_value=mock_ses):
        resp = handler(_event("POST", "/v1/domains", body={"domain_name": domain_name}, org_id=org_id), None)
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# Test 1: Create domain → 201 with DKIM tokens
def test_create_domain_returns_dkim_tokens(seeded):
    mock_ses = _mock_sesv2(["aaa", "bbb", "ccc"])
    with patch("core.api.domains_handler._get_sesv2", return_value=mock_ses):
        resp = handler(_event("POST", "/v1/domains", body={"domain_name": "acme.com"}), None)

    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["domain_name"] == "acme.com"
    assert body["dkim_tokens"] == ["aaa", "bbb", "ccc"]
    assert body["status"] == "pending_dns"
    assert "dns_records" in body
    assert len(body["dns_records"]["dkim"]) == 3
    assert body["domain_id"].startswith("dom_")


# Test 2: List domains
def test_list_domains(seeded):
    _create_domain("foo.com")
    _create_domain("bar.com")

    with patch("core.api.domains_handler._get_sesv2", return_value=_mock_sesv2()):
        resp = handler(_event("GET", "/v1/domains"), None)

    assert resp["statusCode"] == 200
    domains = json.loads(resp["body"])["domains"]
    assert len(domains) == 2
    names = {d["domain_name"] for d in domains}
    assert names == {"foo.com", "bar.com"}


# Test 3: Same org re-registers same domain — idempotent (not 409)
def test_same_org_duplicate_domain_is_ok(seeded):
    mock_ses = _mock_sesv2()
    # Simulate AlreadyExistsException on second call
    mock_ses.create_email_identity.side_effect = [
        {"DkimAttributes": {"Tokens": ["t1", "t2", "t3"]}},  # first call succeeds
        mock_ses.exceptions.AlreadyExistsException("already exists"),  # second call
    ]
    with patch("core.api.domains_handler._get_sesv2", return_value=mock_ses):
        resp1 = handler(_event("POST", "/v1/domains", body={"domain_name": "same.com"}), None)
        assert resp1["statusCode"] == 201
        resp2 = handler(_event("POST", "/v1/domains", body={"domain_name": "same.com"}), None)
        # Same org re-registering is allowed (GSI7 check passes; SES returns AlreadyExists → we use existing)
        assert resp2["statusCode"] == 201


# Test 4: Different org claims same domain → 409
def test_different_org_duplicate_domain_is_409(seeded, seeded_org2):
    _create_domain("taken.com", org_id="org_D")

    mock_ses = _mock_sesv2()
    with patch("core.api.domains_handler._get_sesv2", return_value=mock_ses):
        resp = handler(_event("POST", "/v1/domains", body={"domain_name": "taken.com"}, org_id="org_D2"), None)

    assert resp["statusCode"] == 409
    assert "another organisation" in json.loads(resp["body"])["error"].lower()


# Test 5: Zone-file starts with "$ORIGIN domain_name."
def test_zone_file_format(seeded):
    create_resp = _create_domain("zone-test.com")
    domain_id = json.loads(create_resp["body"])["domain_id"]

    with patch("core.api.domains_handler._get_sesv2", return_value=_mock_sesv2()):
        resp = handler(_event(
            "GET", f"/v1/domains/{domain_id}/zone-file",
            path_params={"id": domain_id},
        ), None)

    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "text/plain"
    zone_text = resp["body"]
    assert zone_text.startswith("$ORIGIN zone-test.com.\n"), (
        f"Zone file does not start with expected $ORIGIN line. Got:\n{zone_text[:200]}"
    )
    assert "MX" in zone_text
    assert "CNAME" in zone_text
    assert "TXT" in zone_text


# Test 6: Delete blocked when a Channel uses the domain → 409
def test_delete_blocked_when_channel_uses_domain(seeded, agentcomms_table):
    create_resp = _create_domain("inuse.com")
    domain_id = json.loads(create_resp["body"])["domain_id"]

    # Create a channel with an email address on that domain
    repo = Repo(agentcomms_table)
    ch = Channel(
        channel_id="chan_email1",
        agent_id="agt_D1",
        org_id="org_D",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@inuse.com"},
        status=ChannelStatus.ACTIVE,
    )
    repo.put_channel(ch)

    with patch("core.api.domains_handler._get_sesv2", return_value=_mock_sesv2()):
        resp = handler(_event(
            "DELETE", f"/v1/domains/{domain_id}",
            path_params={"id": domain_id},
        ), None)

    assert resp["statusCode"] == 409
    assert "in use" in json.loads(resp["body"])["error"].lower()


# Test 7: Delete succeeds when no channel references
def test_delete_domain_success_no_channels(seeded):
    create_resp = _create_domain("unused.com")
    domain_id = json.loads(create_resp["body"])["domain_id"]

    mock_ses = _mock_sesv2()
    with patch("core.api.domains_handler._get_sesv2", return_value=mock_ses):
        del_resp = handler(_event(
            "DELETE", f"/v1/domains/{domain_id}",
            path_params={"id": domain_id},
        ), None)
    assert del_resp["statusCode"] == 204

    # Verify gone from DB
    with patch("core.api.domains_handler._get_sesv2", return_value=_mock_sesv2()):
        get_resp = handler(_event(
            "GET", f"/v1/domains/{domain_id}",
            path_params={"id": domain_id},
        ), None)
    assert get_resp["statusCode"] == 404


# Test 8: Agent-scoped caller → 403
def test_agent_scoped_caller_is_forbidden(seeded):
    for method, path, pp, body in [
        ("GET",    "/v1/domains",          {},              None),
        ("POST",   "/v1/domains",          {},              {"domain_name": "x.com"}),
        ("GET",    "/v1/domains/fake_id",  {"id": "fake_id"}, None),
        ("DELETE", "/v1/domains/fake_id",  {"id": "fake_id"}, None),
    ]:
        resp = handler(_event(
            method, path,
            path_params=pp,
            body=body,
            scope="agent",
            agent_id="agt_D1",
        ), None)
        assert resp["statusCode"] == 403, (
            f"Expected 403 for {method} {path} with agent scope, got {resp['statusCode']}"
        )


# Test 9: Create missing domain_name → 400
def test_create_missing_domain_name_returns_400(seeded):
    with patch("core.api.domains_handler._get_sesv2", return_value=_mock_sesv2()):
        resp = handler(_event("POST", "/v1/domains", body={}), None)
    assert resp["statusCode"] == 400
    assert "domain_name" in json.loads(resp["body"])["error"].lower()
