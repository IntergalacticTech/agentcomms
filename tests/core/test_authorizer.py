# tests/core/test_authorizer.py
import hashlib
import pytest
from core.data.models import ApiKey, ApiKeyScope
from core.data.repo import Repo
from core.api.authorizer import authorize, DeniedError


@pytest.fixture
def repo_with_keys(agentcomms_table):
    repo = Repo(table=agentcomms_table)
    org_key = ApiKey(
        key_id="k_org", key_hash=hashlib.sha256(b"org_secret").hexdigest(),
        org_id="org_X", scope=ApiKeyScope.ORG, name="admin",
    )
    agent_key = ApiKey(
        key_id="k_agt", key_hash=hashlib.sha256(b"agt_secret").hexdigest(),
        org_id="org_X", scope=ApiKeyScope.AGENT, agent_id="agt_1", name="bot",
    )
    repo.put_table_item = repo.table.put_item  # for reuse if needed
    repo.table.put_item(Item=org_key.to_dynamodb_item())
    repo.table.put_item(Item=agent_key.to_dynamodb_item())
    return repo


def test_valid_org_key_allows_everything(repo_with_keys):
    ctx = authorize(
        repo=repo_with_keys,
        raw_api_key="org_secret",
        requested_path="/v1/agents/agt_1/messages",
        requested_method="POST",
    )
    assert ctx.org_id == "org_X"
    assert ctx.scope == "org"


def test_agent_key_allows_own_agent_path(repo_with_keys):
    ctx = authorize(
        repo=repo_with_keys,
        raw_api_key="agt_secret",
        requested_path="/v1/agents/agt_1/messages",
        requested_method="GET",
    )
    assert ctx.agent_id == "agt_1"


def test_agent_key_denies_other_agent_path(repo_with_keys):
    with pytest.raises(DeniedError):
        authorize(
            repo=repo_with_keys,
            raw_api_key="agt_secret",
            requested_path="/v1/agents/agt_OTHER/messages",
            requested_method="GET",
        )


def test_unknown_key_denied(repo_with_keys):
    with pytest.raises(DeniedError):
        authorize(
            repo=repo_with_keys,
            raw_api_key="nope",
            requested_path="/v1/agents/agt_1/messages",
            requested_method="GET",
        )
