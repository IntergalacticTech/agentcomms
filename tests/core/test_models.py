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


def test_channel_type_accepts_external_adapter_slugs():
    channel_type = ChannelType("smoke_signal")
    assert channel_type.value == "smoke_signal"
    assert ChannelType("smoke_signal") is channel_type


@pytest.mark.parametrize("slug", ["", "Smoke", "../email", "email/slack", "a" * 64])
def test_channel_type_rejects_unsafe_external_adapter_slugs(slug):
    with pytest.raises(ValueError):
        ChannelType(slug)


def test_external_adapter_channel_roundtrip():
    ch = Channel(
        channel_id="chan_al_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType("alien-transmission"),
        mode=ChannelMode.BRIDGE,
        config={"beam": "narrowband"},
        address_index_value="sector-7g",
        status=ChannelStatus.ACTIVE,
    )
    item = ch.to_dynamodb_item()
    assert item["SK"] == "CHAN#alien-transmission#chan_al_01HABC"
    assert item["gsi2_pk"] == "ADDR#alien-transmission#sector-7g"
    restored = Channel.from_dynamodb_item(item)
    assert restored == ch


from core.data.models import (
    UnifiedMessage, MessageDirection, MessageStatus, Party
)


def _email_message():
    return UnifiedMessage(
        message_id="msg_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel_id="chan_em_01HJKL",
        channel=ChannelType.EMAIL,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address="alice@example.com", display_name="Alice"),
        to=[Party(address="bot@agentcomms.dev")],
        subject="hi",
        body_text="hello",
        is_dm=True,
        thread_key="thr_01HMNO",
        received_at=datetime(2026, 4, 17, tzinfo=timezone.utc),
        channel_native={"message_id_header": "<abc@x>"},
        external_id="<abc@x>",
    )


def test_unified_message_is_dm_projects_to_gsi3():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01HDEF"
    assert item["SK"].startswith("MSG#")
    assert item["gsi3_pk"] == "AGT_DM#agt_01HDEF"
    assert item["gsi3_sk"] == item["SK"]


def test_unified_message_not_dm_omits_gsi3():
    msg = _email_message()
    msg.is_dm = False
    item = msg.to_dynamodb_item()
    assert "gsi3_pk" not in item
    assert "gsi3_sk" not in item


def test_unified_message_populates_gsi4_channel():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    assert item["gsi4_pk"] == "CHAN#chan_em_01HJKL"


def test_unified_message_populates_gsi5_thread_when_present():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    assert item["gsi5_pk"] == "THR#thr_01HMNO"


def test_unified_message_populates_gsi6_external_id():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    assert item["gsi6_pk"] == "EXTID#email#<abc@x>"


def test_unified_message_sort_key_uses_timestamp_ms_then_id():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    expected_ts_ms = int(msg.received_at.timestamp() * 1000)
    assert item["SK"] == f"MSG#{expected_ts_ms}#msg_01HABC"


def test_unified_message_roundtrip():
    msg = _email_message()
    restored = UnifiedMessage.from_dynamodb_item(msg.to_dynamodb_item())
    assert restored == msg


from core.data.models import ApiKey, ApiKeyScope, Thread, Draft, Webhook


def test_external_adapter_message_thread_and_draft_roundtrip():
    external = ChannelType("ham_radio")
    msg = UnifiedMessage(
        message_id="msg_01HXYZ",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel_id="chan_hr_01HJKL",
        channel=external,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address="callsign:k1abc"),
        to=[Party(address="callsign:n0bot")],
        body_text="cq agentcomms",
        thread_key="freq:146.520",
        external_id="packet-123",
    )
    msg_item = msg.to_dynamodb_item()
    assert msg_item["channel"] == "ham_radio"
    assert msg_item["gsi6_pk"] == "EXTID#ham_radio#packet-123"
    assert UnifiedMessage.from_dynamodb_item(msg_item) == msg

    thread = Thread(
        thread_key="thr_hr_01H",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=external,
        native_thread_id="freq:146.520",
    )
    assert Thread.from_dynamodb_item(thread.to_dynamodb_item()) == thread

    draft = Draft(
        draft_id="drf_hr_01H",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=external,
        to=[Party(address="callsign:k1abc")],
        body_text="roger",
    )
    assert Draft.from_dynamodb_item(draft.to_dynamodb_item()) == draft


def test_api_key_projects_gsi1():
    key = ApiKey(
        key_id="key_01HABC",
        key_hash="sha256:deadbeef",
        org_id="org_01HDEF",
        scope=ApiKeyScope.AGENT,
        agent_id="agt_01HGHI",
        name="bot key",
    )
    item = key.to_dynamodb_item()
    assert item["PK"] == "ORG#org_01HDEF"
    assert item["SK"] == "APIKEY#sha256:deadbeef"
    assert item["gsi1_pk"] == "APIKEY#sha256:deadbeef"
    assert item["gsi1_sk"] == "ORG#org_01HDEF"


def test_api_key_roundtrip():
    key = ApiKey(key_id="k", key_hash="h", org_id="o", scope=ApiKeyScope.ORG, name="n")
    assert ApiKey.from_dynamodb_item(key.to_dynamodb_item()) == key


def test_thread_keys():
    t = Thread(
        thread_key="thr_01H",
        agent_id="agt_01H",
        org_id="org_01H",
        channel=ChannelType.EMAIL,
        native_thread_id="<root@x>",
        subject="Re: ping",
    )
    item = t.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01H"
    assert item["SK"] == "THR#email#<root@x>"


def test_draft_keys():
    d = Draft(
        draft_id="drf_01H",
        agent_id="agt_01H",
        org_id="org_01H",
        channel=ChannelType.EMAIL,
        to=[Party(address="x@y.z")],
        body_text="hi",
    )
    item = d.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01H"
    assert item["SK"] == "DRF#email#drf_01H"


def test_webhook_keys_and_channel_filter():
    w = Webhook(
        webhook_id="whk_01H",
        agent_id="agt_01H",
        org_id="org_01H",
        url="https://example.com/hook",
        events=["message.received"],
        channels=["email", "slack"],
        secret="sek",
    )
    item = w.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01H"
    assert item["SK"] == "WHK#whk_01H"
    assert item["channels"] == ["email", "slack"]
