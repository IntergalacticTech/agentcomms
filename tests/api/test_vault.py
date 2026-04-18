# tests/api/test_vault.py
"""Tests for /v1/vault/* routes.

Test coverage:
  1. POST password entry → 201, no plaintext in response; GET /{id} returns
     decrypted value.
  2. POST totp entry with known seed → GET /{id}/totp returns 6-digit code
     matching pyotp.TOTP reference.
  3. List → metadata only (no encrypted_blob, no value).
  4. DELETE → 204; subsequent GET → 404.
  5. Agent-scoped caller on any vault route → 403.
  6. GET /{id}/totp on a non-totp item → 400.
  7. POST missing required field → 400.
  8. POST totp with invalid base32 seed → 400.

pyotp is used as the TOTP oracle in tests only.  Install with:
    pip install pyotp
"""
from __future__ import annotations

import json
import time

import pytest

# pyotp is a TEST-ONLY dependency; fail loudly if missing
try:
    import pyotp  # noqa: F401
except ImportError:
    pytest.skip("pyotp not installed — run `pip install pyotp`", allow_module_level=True)

from core.data.models import Agent, Organization, OrgPlan
from core.data.repo import Repo
from core.api.vault_handler import handler

_KNOWN_SEED = "JBSWY3DPEHPK3PXP"  # standard test seed used in RFC examples


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
                "org_id": "org_T",
                "scope": scope,
                "agent_id": agent_id,
                "channel_id": None,
                "api_key_id": "k_test",
            }
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(agentcomms_table, kms_key):
    """Seed org + one agent into the table; return repo."""
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_T", name="TestOrg", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_V", org_id="org_T", name="VaultAgent"))
    return repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# ── Test 1: Create password → no plaintext in POST response; GET returns value

def test_create_password_and_get_decrypted_value(seeded):
    # Create
    resp = handler(_event(
        "POST", "/v1/vault",
        body={"type": "password", "label": "my-db-password", "value": "s3cr3t!"},
    ), None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    # POST response must NOT contain the plaintext
    assert "value" not in body
    assert "encrypted_blob" not in body
    assert body["type"] == "password"
    assert body["label"] == "my-db-password"
    vault_id = body["vault_id"]

    # GET /{id} → decrypted value present
    get_resp = handler(_event(
        "GET", f"/v1/vault/{vault_id}",
        path_params={"id": vault_id},
    ), None)
    assert get_resp["statusCode"] == 200
    get_body = json.loads(get_resp["body"])
    assert get_body["value"] == "s3cr3t!"
    assert "encrypted_blob" not in get_body


# ── Test 2: TOTP entry → code matches pyotp oracle

def test_create_totp_and_code_matches_pyotp(seeded):
    # Create
    resp = handler(_event(
        "POST", "/v1/vault",
        body={"type": "totp", "label": "github-2fa", "seed": _KNOWN_SEED},
    ), None)
    assert resp["statusCode"] == 201
    vault_id = json.loads(resp["body"])["vault_id"]

    # GET /{id}/totp — sample both references at approximately the same time
    t_sample = int(time.time())

    totp_resp = handler(_event(
        "GET", f"/v1/vault/{vault_id}/totp",
        path_params={"id": vault_id},
    ), None)
    assert totp_resp["statusCode"] == 200
    totp_body = json.loads(totp_resp["body"])
    code = totp_body["code"]
    valid_until = totp_body["valid_until"]

    # Must be 6-digit string
    assert len(code) == 6
    assert code.isdigit()

    # Must match pyotp for the same time window
    reference = pyotp.TOTP(_KNOWN_SEED).at(t_sample)
    assert code == reference, (
        f"handler returned {code!r}, pyotp returned {reference!r} at t={t_sample}"
    )

    # valid_until must be a future epoch (within the next 30s)
    assert valid_until > t_sample
    assert valid_until <= t_sample + 30


# ── Test 3: GET /{id} for TOTP item does NOT expose the seed

def test_get_totp_item_does_not_expose_seed(seeded):
    resp = handler(_event(
        "POST", "/v1/vault",
        body={"type": "totp", "label": "totp-noseed", "seed": _KNOWN_SEED},
    ), None)
    vault_id = json.loads(resp["body"])["vault_id"]

    get_resp = handler(_event(
        "GET", f"/v1/vault/{vault_id}",
        path_params={"id": vault_id},
    ), None)
    assert get_resp["statusCode"] == 200
    get_body = json.loads(get_resp["body"])
    assert "value" not in get_body
    assert "seed" not in get_body
    assert "encrypted_blob" not in get_body


# ── Test 4: List returns metadata only

def test_list_returns_metadata_only(seeded):
    # Create two items
    handler(_event("POST", "/v1/vault",
                   body={"type": "secret", "label": "alpha", "value": "plain1"}), None)
    handler(_event("POST", "/v1/vault",
                   body={"type": "api_key", "label": "beta", "value": "plain2"}), None)

    list_resp = handler(_event("GET", "/v1/vault"), None)
    assert list_resp["statusCode"] == 200
    items = json.loads(list_resp["body"])["items"]
    assert len(items) == 2
    for item in items:
        assert "encrypted_blob" not in item
        assert "value" not in item
        assert "seed" not in item
        assert "vault_id" in item
        assert "label" in item
        assert "type" in item


# ── Test 5: DELETE → 204; subsequent GET → 404

def test_delete_removes_item(seeded):
    # Create
    resp = handler(_event(
        "POST", "/v1/vault",
        body={"type": "secret", "label": "temp", "value": "bye"},
    ), None)
    vault_id = json.loads(resp["body"])["vault_id"]

    # Delete
    del_resp = handler(_event(
        "DELETE", f"/v1/vault/{vault_id}",
        path_params={"id": vault_id},
    ), None)
    assert del_resp["statusCode"] == 204

    # Subsequent GET → 404
    get_resp = handler(_event(
        "GET", f"/v1/vault/{vault_id}",
        path_params={"id": vault_id},
    ), None)
    assert get_resp["statusCode"] == 404


# ── Test 6: Agent-scoped caller → 403

def test_agent_scoped_caller_is_forbidden(seeded):
    for method, path, pp, body in [
        ("GET",    "/v1/vault",              {},              None),
        ("POST",   "/v1/vault",              {},              {"type": "secret", "label": "x", "value": "y"}),
        ("GET",    "/v1/vault/some_id",      {"id": "some_id"}, None),
        ("DELETE", "/v1/vault/some_id",      {"id": "some_id"}, None),
    ]:
        resp = handler(_event(
            method, path,
            path_params=pp,
            body=body,
            scope="agent",
            agent_id="agt_V",
        ), None)
        assert resp["statusCode"] == 403, (
            f"Expected 403 for {method} {path} with agent scope, got {resp['statusCode']}"
        )


# ── Test 7: GET /totp on non-totp item → 400

def test_totp_route_on_non_totp_item_returns_400(seeded):
    resp = handler(_event(
        "POST", "/v1/vault",
        body={"type": "password", "label": "not-totp", "value": "abc"},
    ), None)
    vault_id = json.loads(resp["body"])["vault_id"]

    totp_resp = handler(_event(
        "GET", f"/v1/vault/{vault_id}/totp",
        path_params={"id": vault_id},
    ), None)
    assert totp_resp["statusCode"] == 400
    assert "totp" in json.loads(totp_resp["body"])["error"].lower()


# ── Test 8: POST missing required fields → 400

def test_create_missing_fields_returns_400(seeded):
    # Missing type
    r1 = handler(_event("POST", "/v1/vault",
                         body={"label": "no-type", "value": "x"}), None)
    assert r1["statusCode"] == 400

    # Missing label
    r2 = handler(_event("POST", "/v1/vault",
                         body={"type": "secret", "value": "x"}), None)
    assert r2["statusCode"] == 400

    # TOTP missing seed
    r3 = handler(_event("POST", "/v1/vault",
                         body={"type": "totp", "label": "no-seed"}), None)
    assert r3["statusCode"] == 400

    # TOTP invalid base32 seed
    r4 = handler(_event("POST", "/v1/vault",
                         body={"type": "totp", "label": "bad-seed", "seed": "!!invalid!!"}), None)
    assert r4["statusCode"] == 400
