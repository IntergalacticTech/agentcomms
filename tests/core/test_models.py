import pytest
from datetime import datetime, timezone
from core.data.models import Organization, OrgPlan


def test_organization_create_with_defaults():
    org = Organization(org_id="org_01HABC", name="Acme")
    assert org.org_id == "org_01HABC"
    assert org.name == "Acme"
    assert org.plan == OrgPlan.FREE
    assert isinstance(org.created_at, datetime)
    assert org.created_at.tzinfo is timezone.utc
    assert org.quotas == {}
    assert org.settings == {}


def test_organization_roundtrip_via_dynamodb_item():
    org = Organization(org_id="org_01HABC", name="Acme", plan=OrgPlan.PRO)
    item = org.to_dynamodb_item()
    assert item["PK"] == "ORG#org_01HABC"
    assert item["SK"] == "META"
    assert item["name"] == "Acme"
    assert item["plan"] == "pro"
    restored = Organization.from_dynamodb_item(item)
    assert restored == org


def test_organization_plan_validation_rejects_unknown():
    with pytest.raises(ValueError):
        Organization(org_id="org_x", name="x", plan="unobtainium")


from core.data.models import Agent


def test_agent_create_with_defaults():
    agent = Agent(agent_id="agt_01HABC", org_id="org_01HDEF", name="InvoiceBot")
    assert agent.agent_id == "agt_01HABC"
    assert agent.org_id == "org_01HDEF"
    assert agent.name == "InvoiceBot"
    assert agent.metadata == {}
    assert agent.status == "active"


def test_agent_dynamodb_item_has_correct_keys():
    agent = Agent(agent_id="agt_01HABC", org_id="org_01HDEF", name="Bot")
    item = agent.to_dynamodb_item()
    assert item["PK"] == "ORG#org_01HDEF"
    assert item["SK"] == "AGT#agt_01HABC"


def test_agent_roundtrip():
    agent = Agent(
        agent_id="agt_01HABC",
        org_id="org_01HDEF",
        name="Bot",
        metadata={"team": "ops"},
    )
    restored = Agent.from_dynamodb_item(agent.to_dynamodb_item())
    assert restored == agent
