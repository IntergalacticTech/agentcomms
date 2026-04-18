# adapters/email/tests/test_adapter.py
from datetime import datetime, timezone
from pathlib import Path
import pytest

from core.data.models import Agent, Channel, ChannelType, ChannelMode, ChannelStatus
from core.adapters.base import IngestPayload, OutboundMessage
from adapters.email.adapter import EmailAdapter


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def adapter():
    return EmailAdapter()


def test_channel_name_and_modes(adapter):
    assert adapter.channel_name == "email"
    assert adapter.supports_modes == ["provision"]


def test_provision_returns_pending_until_dkim_verified(adapter, ses_client):
    agent = Agent(agent_id="agt_1", org_id="org_X", name="bot")
    result = adapter.provision(agent=agent, config={
        "local_part": "bot", "domain": "agentcomms.dev",
    })
    # Provision creates SES identity; returns pending until DKIM succeeds out-of-band
    assert result.status in ("pending_verification", "active")
    assert result.details["address"] == "bot@agentcomms.dev"
    assert "dkim_tokens" in result.details


def test_ingest_routes_by_recipient(adapter, agentcomms_table, s3_buckets, repo_fixture):
    # Seed a channel whose inbound address matches the fixture recipient
    from core.data.models import Channel, ChannelType, ChannelMode
    channel = Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    )
    repo_fixture.put_channel(channel)

    raw = (FIXTURES / "inbound_simple.eml").read_bytes()
    payload = IngestPayload(source="sns", headers={}, body=raw, path_params={})
    msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.channel.value == "email"
    assert msg.direction.value == "inbound"
    assert msg.agent_id == "agt_1"
    assert msg.channel_id == "chan_em_1"
    assert msg.is_dm is True
    assert msg.subject == "March invoice"
    assert msg.from_.address == "alice@example.com"
    assert msg.to[0].address == "bot@agentcomms.dev"
    assert msg.external_id == "<abc123@example.com>"
    assert msg.channel_native["message_id_header"] == "<abc123@example.com>"


def test_ingest_returns_none_for_unknown_recipient(adapter, agentcomms_table, s3_buckets, repo_fixture):
    raw = (FIXTURES / "inbound_simple.eml").read_bytes()
    payload = IngestPayload(source="sns", headers={}, body=raw, path_params={})
    # No channel registered for bot@agentcomms.dev
    msg = adapter.ingest(payload=payload)
    assert msg is None


def test_send_builds_mime_and_calls_ses(adapter, ses_client, repo_fixture):
    # Verify identity first (SES requires for sending)
    ses_client.verify_domain_identity(Domain="agentcomms.dev")
    channel = Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    )
    msg = OutboundMessage(
        to="alice@example.com",
        body_text="Hello",
        subject="Test",
    )
    result = adapter.send(channel=channel, message=msg)
    assert result.status == "sent"
    assert result.channel_native_id  # some SES MessageId


def test_health_check(adapter, ses_client, repo_fixture):
    channel = Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        status=ChannelStatus.ACTIVE,
    )
    status = adapter.health_check(channel=channel)
    assert status.ok is True
