# tests/api/test_agents.py
import json
import pytest
from unittest.mock import patch

from core.data.models import Organization, OrgPlan
from core.data.repo import Repo
from core.api.agents_handler import handler


@pytest.fixture
def seeded(agentcomms_table, ses_client, s3_buckets):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_X", name="Acme", plan=OrgPlan.FREE))
    return repo


def _event(method, path, body=None, ctx=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": ctx or {
                "org_id": "org_X", "scope": "org",
                "agent_id": None, "channel_id": None, "api_key_id": "k_org",
            },
        },
    }


def test_create_agent_with_email_provision(seeded):
    with patch("adapters.email.adapter.boto3") as mock_boto3:
        # Mock SES client
        mock_ses = mock_boto3.client.return_value
        mock_ses.verify_domain_dkim.return_value = {"DkimTokens": ["t1", "t2", "t3"]}
        event = _event("POST", "/v1/agents", body={
            "name": "InvoiceBot",
            "provision": {
                "email": {"local_part": "invoice-bot", "domain": "agentcomms.dev"}
            },
        })
        resp = handler(event, None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["agent_id"].startswith("agt_")
    assert len(body["channels"]) == 1
    assert body["channels"][0]["channel"] == "email"
    assert body["channels"][0]["details"]["address"] == "invoice-bot@agentcomms.dev"


def test_create_agent_no_provision(seeded):
    event = _event("POST", "/v1/agents", body={"name": "Minimal"})
    resp = handler(event, None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["channels"] == []


def test_list_agents(seeded):
    # seed two agents
    handler(_event("POST", "/v1/agents", body={"name": "A"}), None)
    handler(_event("POST", "/v1/agents", body={"name": "B"}), None)
    resp = handler(_event("GET", "/v1/agents"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["agents"]) == 2


def test_get_agent_by_id(seeded):
    c = handler(_event("POST", "/v1/agents", body={"name": "GetMe"}), None)
    agent_id = json.loads(c["body"])["agent_id"]
    event = _event("GET", f"/v1/agents/{agent_id}")
    event["pathParameters"] = {"agent_id": agent_id}
    resp = handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["name"] == "GetMe"


def test_delete_agent(seeded):
    c = handler(_event("POST", "/v1/agents", body={"name": "Trash"}), None)
    agent_id = json.loads(c["body"])["agent_id"]
    event = _event("DELETE", f"/v1/agents/{agent_id}")
    event["pathParameters"] = {"agent_id": agent_id}
    resp = handler(event, None)
    assert resp["statusCode"] == 204
