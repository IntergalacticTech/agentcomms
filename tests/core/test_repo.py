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
