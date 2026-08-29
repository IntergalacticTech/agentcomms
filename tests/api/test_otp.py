# tests/api/test_otp.py
"""Tests for POST /v1/agents/{id}/extract-otp handler."""
import json
from datetime import datetime, timedelta, timezone
import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    MessageDirection, MessageStatus, Organization, OrgPlan, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.api.otp_handler import handler


@pytest.fixture
def fixture(agentcomms_table):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_X", name="Acme", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="bot"))
    repo.put_channel(Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        status=ChannelStatus.ACTIVE,
    ))
    repo.put_channel(Channel(
        channel_id="chan_sms_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.SMS, mode=ChannelMode.PROVISION,
        config={"phone": "+15551234567"},
        status=ChannelStatus.ACTIVE,
    ))
    return repo


def _event(agent_id="agt_1", body=None):
    return {
        "httpMethod": "POST",
        "path": f"/v1/agents/{agent_id}/extract-otp",
        "pathParameters": {"agent_id": agent_id},
        "queryStringParameters": {},
        "body": json.dumps(body) if body is not None else "{}",
        "requestContext": {"authorizer": {
            "org_id": "org_X", "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


def _seed_message(repo, *, msg_id, channel, channel_id, body_text, received_at=None):
    if received_at is None:
        received_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    repo.put_message(UnifiedMessage(
        message_id=msg_id,
        agent_id="agt_1", org_id="org_X",
        channel_id=channel_id,
        channel=channel,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address="noreply@auth.example.com"),
        to=[Party(address="bot@agentcomms.dev")],
        body_text=body_text,
        is_dm=True,
        received_at=received_at,
    ))


def test_otp_extracted_from_email_body(fixture):
    """OTP in email body with keyword 'verification code' is extracted."""
    _seed_message(
        fixture,
        msg_id="msg_email_otp",
        channel=ChannelType.EMAIL,
        channel_id="chan_em_1",
        body_text="Your verification code is 847291. It expires in 10 minutes.",
    )
    resp = handler(_event(body={"channel": "email", "max_age_sec": 600}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["code"] == "847291"
    assert body["message_id"] == "msg_email_otp"
    assert "received_at" in body


def test_otp_extracted_from_sms_body(fixture):
    """OTP in SMS body with keyword 'pin' is extracted (channel-agnostic)."""
    _seed_message(
        fixture,
        msg_id="msg_sms_otp",
        channel=ChannelType.SMS,
        channel_id="chan_sms_1",
        body_text="Your PIN: 5521 — do not share this with anyone.",
    )
    resp = handler(_event(body={"channel": "sms", "max_age_sec": 600}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["code"] == "5521"
    assert body["message_id"] == "msg_sms_otp"


def test_otp_no_match_returns_404(fixture):
    """When no matching message has an OTP, return 404."""
    # Seed a message without OTP keywords
    _seed_message(
        fixture,
        msg_id="msg_no_otp",
        channel=ChannelType.EMAIL,
        channel_id="chan_em_1",
        body_text="Hello! Welcome to our platform. No codes here.",
    )
    resp = handler(_event(body={"channel": "email", "max_age_sec": 600}), None)
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert "no otp" in body["error"].lower()
