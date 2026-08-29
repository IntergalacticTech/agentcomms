# tests/core/test_repo.py
import pytest
from core.data.models import (
    Organization, Agent, Channel, ChannelType, ChannelMode, OrgPlan
)
from core.data.repo import Repo


@pytest.fixture
def repo(agentcomms_table):
    return Repo(table=agentcomms_table)


def test_put_and_get_organization(repo):
    org = Organization(org_id="org_X", name="Acme", plan=OrgPlan.DEVELOPER)
    repo.put_organization(org)
    got = repo.get_organization("org_X")
    assert got == org


def test_get_organization_missing_returns_none(repo):
    assert repo.get_organization("org_nope") is None


def test_put_and_get_agent(repo):
    agent = Agent(agent_id="agt_1", org_id="org_X", name="bot")
    repo.put_agent(agent)
    got = repo.get_agent(org_id="org_X", agent_id="agt_1")
    assert got == agent


def test_list_agents_in_org(repo):
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="a"))
    repo.put_agent(Agent(agent_id="agt_2", org_id="org_X", name="b"))
    repo.put_agent(Agent(agent_id="agt_3", org_id="org_Y", name="c"))
    got = repo.list_agents(org_id="org_X")
    assert {a.agent_id for a in got} == {"agt_1", "agt_2"}


def test_put_and_get_channel(repo):
    ch = Channel(
        channel_id="chan_em_1",
        agent_id="agt_1",
        org_id="org_X",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@x.com"},
        address_index_value="bot@x.com",
    )
    repo.put_channel(ch)
    got = repo.get_channel(agent_id="agt_1", channel="email", channel_id="chan_em_1")
    assert got == ch


def test_list_channels_for_agent(repo):
    for cid in ["chan_em_1", "chan_em_2"]:
        repo.put_channel(Channel(
            channel_id=cid, agent_id="agt_1", org_id="org_X",
            channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION, config={},
        ))
    repo.put_channel(Channel(
        channel_id="chan_sm_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.SMS, mode=ChannelMode.PROVISION, config={},
    ))
    got = repo.list_channels(agent_id="agt_1")
    assert len(got) == 3
    assert {c.channel_id for c in got} == {"chan_em_1", "chan_em_2", "chan_sm_1"}


def test_lookup_channel_by_address(repo):
    ch = Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@x.com"}, address_index_value="bot@x.com",
    )
    repo.put_channel(ch)
    got = repo.lookup_channel_by_address(channel="email", address="bot@x.com")
    assert got == ch


def test_lookup_channel_by_address_missing(repo):
    assert repo.lookup_channel_by_address(channel="email", address="nope@x.com") is None


from datetime import datetime, timedelta, timezone
from core.data.models import UnifiedMessage, MessageDirection, MessageStatus, Party


def _msg(agent_id="agt_1", msg_id="msg_1", is_dm=True, channel_id="chan_em_1",
         received_at=None, external_id=None, channel="email"):
    return UnifiedMessage(
        message_id=msg_id,
        agent_id=agent_id,
        org_id="org_X",
        channel_id=channel_id,
        channel=channel,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address="alice@x.com"),
        to=[Party(address="bot@agentcomms.dev")],
        body_text="hi",
        is_dm=is_dm,
        received_at=received_at or datetime(2026, 4, 17, 12, tzinfo=timezone.utc),
        external_id=external_id,
    )


def test_put_message_and_query_unified_inbox(repo):
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    repo.put_message(_msg(msg_id="msg_1", received_at=t0))
    repo.put_message(_msg(msg_id="msg_2", received_at=t0 + timedelta(minutes=1)))
    repo.put_message(_msg(msg_id="msg_3", is_dm=False, received_at=t0 + timedelta(minutes=2)))

    inbox = repo.list_unified_inbox(agent_id="agt_1")
    # Only the two is_dm=True messages, newest first
    ids = [m.message_id for m in inbox]
    assert ids == ["msg_2", "msg_1"]


def test_unified_inbox_since_filter(repo):
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    repo.put_message(_msg(msg_id="msg_old", received_at=t0))
    repo.put_message(_msg(msg_id="msg_new", received_at=t0 + timedelta(hours=1)))
    inbox = repo.list_unified_inbox(agent_id="agt_1", since=t0 + timedelta(minutes=30))
    assert [m.message_id for m in inbox] == ["msg_new"]


def test_list_channel_messages(repo):
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    repo.put_message(_msg(msg_id="m_em", channel_id="chan_em", received_at=t0))
    repo.put_message(_msg(msg_id="m_sl", channel_id="chan_sl", received_at=t0 + timedelta(minutes=1)))
    got = repo.list_channel_messages(channel_id="chan_em")
    assert [m.message_id for m in got] == ["m_em"]


def test_lookup_message_by_external_id_returns_existing(repo):
    msg = _msg(msg_id="msg_ext", external_id="<abc@x>")
    repo.put_message(msg)
    got = repo.lookup_message_by_external_id(channel="email", external_id="<abc@x>")
    assert got is not None
    assert got.message_id == "msg_ext"


def test_lookup_message_by_external_id_missing(repo):
    assert repo.lookup_message_by_external_id(channel="email", external_id="<nope@x>") is None


def test_get_message_by_id(repo):
    msg = _msg(msg_id="msg_42")
    repo.put_message(msg)
    got = repo.get_message(agent_id="agt_1", received_at_ms=int(msg.received_at.timestamp() * 1000), message_id="msg_42")
    assert got == msg
