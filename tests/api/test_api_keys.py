# SPDX-License-Identifier: Apache-2.0

"""Tests for /v1/api-keys routes."""
from __future__ import annotations

import json

import pytest

from core.api.api_keys_handler import handler
from core.data.models import (
    Agent,
    Channel,
    ChannelMode,
    ChannelStatus,
    ChannelType,
    Organization,
    OrgPlan,
)
from core.data.repo import Repo


@pytest.fixture
def seeded(agentcomms_table):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_K", name="Keys", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_K", org_id="org_K", name="KeyBot"))
    repo.put_channel(Channel(
        channel_id="chan_em_K",
        agent_id="agt_K",
        org_id="org_K",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@example.com"},
        status=ChannelStatus.ACTIVE,
    ))
    return repo


def _event(method: str, path: str, *, body=None, path_params=None, scope="org", api_key_id="admin"):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {
                "org_id": "org_K",
                "scope": scope,
                "agent_id": None,
                "channel_id": None,
                "api_key_id": api_key_id,
            }
        },
    }


def test_create_key_returns_plaintext_once_without_hash(seeded):
    resp = handler(_event(
        "POST",
        "/v1/api-keys",
        body={"name": "worker", "scope": "agent", "agent_id": "agt_K"},
    ), None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["key"].startswith("ak_live_")
    assert body["key_prefix"] == body["key"][:12]
    assert body["scope"] == "agent"
    assert body["agent_id"] == "agt_K"
    assert "key_hash" not in body


def test_list_keys_never_returns_plaintext_or_hash(seeded):
    handler(_event("POST", "/v1/api-keys", body={"name": "admin", "scope": "org"}), None)
    resp = handler(_event("GET", "/v1/api-keys"), None)
    assert resp["statusCode"] == 200
    keys = json.loads(resp["body"])["api_keys"]
    assert len(keys) == 1
    assert "key" not in keys[0]
    assert "key_hash" not in keys[0]
    assert keys[0]["key_prefix"].startswith("ak_live_")


def test_create_channel_key_requires_existing_channel(seeded):
    resp = handler(_event(
        "POST",
        "/v1/api-keys",
        body={
            "name": "missing",
            "scope": "channel",
            "agent_id": "agt_K",
            "channel_id": "chan_missing",
        },
    ), None)
    assert resp["statusCode"] == 404


def test_revoke_key_marks_it_revoked(seeded):
    create = handler(_event("POST", "/v1/api-keys", body={"name": "temp", "scope": "org"}), None)
    key_id = json.loads(create["body"])["key_id"]

    resp = handler(_event(
        "DELETE",
        f"/v1/api-keys/{key_id}",
        path_params={"key_id": key_id},
    ), None)
    assert resp["statusCode"] == 204
    stored = seeded.get_api_key_by_id(org_id="org_K", key_id=key_id)
    assert stored is not None
    assert stored.revoked is True


def test_refuses_to_revoke_calling_key(seeded):
    create = handler(_event("POST", "/v1/api-keys", body={"name": "self", "scope": "org"}), None)
    key_id = json.loads(create["body"])["key_id"]

    resp = handler(_event(
        "DELETE",
        f"/v1/api-keys/{key_id}",
        path_params={"key_id": key_id},
        api_key_id=key_id,
    ), None)
    assert resp["statusCode"] == 409


def test_agent_scoped_key_cannot_manage_keys(seeded):
    resp = handler(_event("GET", "/v1/api-keys", scope="agent"), None)
    assert resp["statusCode"] == 403
