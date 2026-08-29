# tests/api/test_agents_one_shot.py
"""
One-shot provisioning tests for POST /v1/agents with telegram and slack.

Verifies that the _provision_channels dispatcher in agents_handler.py:
  - Routes provision:{telegram:{bot_token:...}} → TelegramAdapter.provision()
    and returns an active channel in the response.
  - Routes bridge:{slack:{return_url:...}} → SlackAdapter.bridge_start()
    and returns a pending_oauth channel with oauth_url.
  - Handles mixed provision + bridge in a single call.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.data.models import Organization, OrgPlan
from core.data.repo import Repo
from core.adapters.base import BridgeStart, ProvisionResult
from core.data.ulid_ import new_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(agentcomms_table, ses_client, s3_buckets):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_os", name="OneShot Inc", plan=OrgPlan.FREE))
    return repo


def _event(body: dict, org_id: str = "org_os") -> dict:
    return {
        "httpMethod": "POST",
        "path": "/v1/agents",
        "pathParameters": {},
        "body": json.dumps(body),
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
                "scope": "org",
                "agent_id": None,
                "channel_id": None,
                "api_key_id": "k_os",
            }
        },
    }


# ---------------------------------------------------------------------------
# Test 1: provision telegram via POST /v1/agents
# ---------------------------------------------------------------------------

def test_provision_telegram_via_agents_post(seeded):
    """provision:{telegram:{bot_token:...}} → TelegramAdapter.provision() → active channel."""
    import core.api.agents_handler as agents_mod
    agents_mod._REGISTRY = None

    tg_channel_id = new_id("chan", suffix="tg")
    tg_prov_result = ProvisionResult(
        status="active",
        channel_id=tg_channel_id,
        details={
            "bot_username": "invoicebot",
            "bot_user_id": 123456789,
            "token_hash": "deadbeef01234567",
        },
    )

    with patch("adapters.telegram.adapter.TelegramAdapter.provision",
               return_value=tg_prov_result) as mock_provision:
        resp = agents_mod.handler(
            _event({
                "name": "InvoiceBotTg",
                "provision": {
                    "telegram": {"bot_token": "123456789:ABCDEF_fake_token"},
                },
            }),
            None,
        )

    assert resp["statusCode"] == 201, f"Unexpected status: {resp['body']}"
    body = json.loads(resp["body"])

    assert body["agent_id"].startswith("agt_")
    assert len(body["channels"]) == 1

    ch = body["channels"][0]
    assert ch["channel"] == "telegram", f"Expected telegram channel, got: {ch['channel']}"
    assert ch["status"] == "active", f"Expected active status, got: {ch['status']}"
    assert ch["channel_id"] == tg_channel_id
    assert "bot_username" in ch["details"]

    mock_provision.assert_called_once()
    call_kwargs = mock_provision.call_args.kwargs
    assert call_kwargs["config"]["bot_token"] == "123456789:ABCDEF_fake_token"


# ---------------------------------------------------------------------------
# Test 2: bridge slack via POST /v1/agents
# ---------------------------------------------------------------------------

def test_bridge_slack_via_agents_post(seeded):
    """bridge:{slack:{return_url:...}} → SlackAdapter.bridge_start() → pending_oauth channel."""
    import core.api.agents_handler as agents_mod
    agents_mod._REGISTRY = None

    fake_oauth_url = "https://slack.com/oauth/v2/authorize?client_id=test&state=abc123"
    fake_state = "abc123noncexyz"

    bridge_result = BridgeStart(
        oauth_url=fake_oauth_url,
        state=fake_state,
        instructions="Visit oauth_url to connect your workspace.",
    )

    with patch("adapters.slack.adapter.SlackAdapter.bridge_start",
               return_value=bridge_result) as mock_bridge_start:
        resp = agents_mod.handler(
            _event({
                "name": "InvoiceBotSlack",
                "bridge": {
                    "slack": {"return_url": "https://myapp.example.com/slack/callback"},
                },
            }),
            None,
        )

    assert resp["statusCode"] == 201, f"Unexpected status: {resp['body']}"
    body = json.loads(resp["body"])

    assert body["agent_id"].startswith("agt_")
    assert len(body["channels"]) == 1

    ch = body["channels"][0]
    assert ch["channel"] == "slack", f"Expected slack channel, got: {ch['channel']}"
    assert ch["status"] == "pending_oauth", f"Expected pending_oauth status, got: {ch['status']}"
    # oauth_url must be in the details
    assert ch["details"].get("oauth_url") == fake_oauth_url, (
        f"oauth_url missing or wrong. details={ch['details']}"
    )

    mock_bridge_start.assert_called_once()
    call_kwargs = mock_bridge_start.call_args.kwargs
    assert call_kwargs["config"]["return_url"] == "https://myapp.example.com/slack/callback"


# ---------------------------------------------------------------------------
# Test 3: mixed provision + bridge in one call
# ---------------------------------------------------------------------------

def test_mixed_provision_and_bridge_in_one_call(seeded):
    """provision telegram + bridge slack in one POST /v1/agents request."""
    import core.api.agents_handler as agents_mod
    agents_mod._REGISTRY = None

    tg_channel_id = new_id("chan", suffix="tg")
    tg_prov_result = ProvisionResult(
        status="active",
        channel_id=tg_channel_id,
        details={"bot_username": "mixedbot", "bot_user_id": 987, "token_hash": "ff00ff"},
    )

    fake_oauth_url = "https://slack.com/oauth/v2/authorize?state=mixed_nonce"
    bridge_result = BridgeStart(
        oauth_url=fake_oauth_url,
        state="mixed_nonce",
        instructions="Connect Slack.",
    )

    with (
        patch("adapters.telegram.adapter.TelegramAdapter.provision",
              return_value=tg_prov_result),
        patch("adapters.slack.adapter.SlackAdapter.bridge_start",
              return_value=bridge_result),
    ):
        resp = agents_mod.handler(
            _event({
                "name": "MixedBot",
                "provision": {
                    "telegram": {"bot_token": "987:XYZ_fake"},
                },
                "bridge": {
                    "slack": {"return_url": "https://example.com/oauth"},
                },
            }),
            None,
        )

    assert resp["statusCode"] == 201, f"Unexpected status: {resp['body']}"
    body = json.loads(resp["body"])

    assert len(body["channels"]) == 2, (
        f"Expected 2 channels, got {len(body['channels'])}: {body['channels']}"
    )

    by_channel = {c["channel"]: c for c in body["channels"]}
    assert "telegram" in by_channel
    assert "slack" in by_channel

    tg_ch = by_channel["telegram"]
    assert tg_ch["status"] == "active"
    assert tg_ch["channel_id"] == tg_channel_id

    sl_ch = by_channel["slack"]
    assert sl_ch["status"] == "pending_oauth"
    assert sl_ch["details"]["oauth_url"] == fake_oauth_url
