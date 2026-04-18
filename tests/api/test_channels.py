# tests/api/test_channels.py
"""Tests for /v1/agents/{id}/channels/* handler."""
import json
import pytest
from unittest.mock import MagicMock, patch

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType, Organization, OrgPlan,
)
from core.data.repo import Repo
from core.api.channels_handler import handler


@pytest.fixture
def fixture(agentcomms_table, ses_client, s3_buckets):
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


def test_list_channels_returns_all_for_agent(fixture):
    """Seed 3 channels on agent, list returns all 3."""
    repo = fixture
    for i in range(3):
        repo.put_channel(Channel(
            channel_id=f"chan_{i}", agent_id="agt_1", org_id="org_X",
            channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
            config={"address": f"bot{i}@agentcomms.dev"},
            status=ChannelStatus.ACTIVE,
        ))
    resp = handler(_event("GET", "/v1/agents/agt_1/channels",
                          path_params={"agent_id": "agt_1"}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["channels"]) == 3


def test_create_channel_calls_provision(fixture):
    """POST /channels with email calls adapter.provision and returns 201."""
    with patch("adapters.email.adapter.boto3") as mock_boto3:
        mock_ses = mock_boto3.client.return_value
        mock_ses.verify_domain_dkim.return_value = {"DkimTokens": ["t1", "t2", "t3"]}
        resp = handler(_event(
            "POST", "/v1/agents/agt_1/channels",
            path_params={"agent_id": "agt_1"},
            body={"channel": "email", "config": {"local_part": "bot", "domain": "agentcomms.dev"}},
        ), None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["channel"] == "email"
    assert body["mode"] == "provision"


def test_get_channel_by_id(fixture):
    """GET /channels/{channel_id} returns the specific channel."""
    repo = fixture
    repo.put_channel(Channel(
        channel_id="chan_em_abc", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        status=ChannelStatus.ACTIVE,
    ))
    resp = handler(_event(
        "GET", "/v1/agents/agt_1/channels/chan_em_abc",
        path_params={"agent_id": "agt_1", "channel_id": "chan_em_abc"},
    ), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["channel_id"] == "chan_em_abc"
    assert body["channel"] == "email"


def test_delete_channel_calls_teardown_and_removes(fixture):
    """DELETE /channels/{channel_id} calls adapter.teardown and removes from DynamoDB."""
    repo = fixture
    repo.put_channel(Channel(
        channel_id="chan_em_del", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "del@agentcomms.dev"},
        status=ChannelStatus.ACTIVE,
    ))
    teardown_called = []
    with patch("adapters.email.adapter.boto3"):
        with patch("core.api.channels_handler._registry") as mock_reg:
            mock_entry = MagicMock()
            mock_entry.adapter.teardown = lambda channel: teardown_called.append(True)
            mock_reg.return_value.get.return_value = mock_entry

            resp = handler(_event(
                "DELETE", "/v1/agents/agt_1/channels/chan_em_del",
                path_params={"agent_id": "agt_1", "channel_id": "chan_em_del"},
            ), None)

    assert resp["statusCode"] == 204
    assert teardown_called == [True]

    # Verify channel is gone from DB
    channels = repo.list_channels(agent_id="agt_1")
    assert not any(c.channel_id == "chan_em_del" for c in channels)
