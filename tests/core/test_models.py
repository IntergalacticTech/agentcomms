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


from core.data.models import Channel, ChannelMode, ChannelStatus, ChannelType


def test_channel_email_provision_defaults():
    ch = Channel(
        channel_id="chan_em_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
    )
    assert ch.channel == ChannelType.EMAIL
    assert ch.status == ChannelStatus.PROVISIONING


def test_channel_dynamodb_keys_and_gsi2():
    ch = Channel(
        channel_id="chan_em_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
    )
    item = ch.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01HDEF"
    assert item["SK"] == "CHAN#email#chan_em_01HABC"
    assert item["gsi2_pk"] == "ADDR#email#bot@agentcomms.dev"
    assert item["gsi2_sk"] == "CHAN#chan_em_01HABC"


def test_channel_without_address_index_value_has_no_gsi2():
    ch = Channel(
        channel_id="chan_sl_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType.SLACK,
        mode=ChannelMode.BRIDGE,
        config={},
    )
    item = ch.to_dynamodb_item()
    assert "gsi2_pk" not in item


def test_channel_roundtrip():
    ch = Channel(
        channel_id="chan_em_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    )
    restored = Channel.from_dynamodb_item(ch.to_dynamodb_item())
    assert restored == ch
