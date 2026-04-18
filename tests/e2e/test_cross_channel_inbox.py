# tests/e2e/test_cross_channel_inbox.py
"""
Cross-channel unified inbox end-to-end test.

Exercises the X1 guarantee: GET /v1/agents/{id}/messages returns ONLY
is_dm=True messages, interleaved across all channels. Non-DM channel noise
is accessible exclusively via channel-native sub-surfaces (GSI4).

Steps:
  1. Seed Org + agent directly via Repo.
  2. Provision 3 channels (email, sms, telegram) via Repo + stub slack
     channel (mode=bridge) directly.
  3. Seed 6 messages across all 4 channels via Repo.put_message:
       - email inbound DM            → is_dm=True
       - SMS inbound                 → is_dm=True
       - Slack DM (channel_id=D...)  → is_dm=True
       - Slack @mention              → is_dm=True  (channel_native.is_mention=True)
       - Slack channel noise         → is_dm=False
       - Telegram group noise        → is_dm=False
  4. GET /v1/agents/{id}/messages → EXACTLY 4 DMs, descending timestamp.
  5. GET /v1/agents/{id}/slack/workspaces/{team_id}/channels/{ch_id}/messages
       → patched to return from GSI4: 1 slack noise item.
  6. GET /v1/agents/{id}/telegram/chats/{chat_id}/messages
       → GSI4 + chat_id filter: 1 telegram noise item.

All Slack/Telegram network clients are patched with unittest.mock.
DynamoDB uses moto (via shared conftest fixtures).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apigw_event(
    method: str,
    path: str,
    path_params: dict | None = None,
    qs: dict | None = None,
    org_id: str = "org_xc",
) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": qs or {},
        "headers": {},
        "body": None,
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
                "scope": "org",
                "api_key_id": "key_xc",
            }
        },
    }


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def test_cross_channel_unified_inbox(agentcomms_table, s3_buckets, ses_client):
    """Unified inbox shows only DMs; channel-native surfaces expose noise."""
    from core.data.models import (
        Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
        MessageDirection, MessageStatus, Organization, OrgPlan,
        Party, UnifiedMessage,
    )
    from core.data.repo import Repo
    from core.data.ulid_ import new_id

    # ── Reset module-level singletons ──────────────────────────────────────────
    import core.api.messages_handler as messages_mod
    import core.api.slack_native_handler as slack_native_mod
    import core.api.telegram_native_handler as telegram_native_mod

    messages_mod._REGISTRY = None

    # ── Step 1: Seed Org + Agent ───────────────────────────────────────────────
    repo = Repo(agentcomms_table)

    org = Organization(org_id="org_xc", name="CrossChannelCo", plan=OrgPlan.FREE)
    repo.put_organization(org)

    agent_id = new_id("agt")
    agent = Agent(agent_id=agent_id, org_id="org_xc", name="XChannelBot")
    repo.put_agent(agent)

    # ── Step 2: Provision channels directly via Repo ───────────────────────────
    email_ch_id = new_id("chan", suffix="em")
    sms_ch_id = new_id("chan", suffix="sm")
    tg_ch_id = new_id("chan", suffix="tg")
    slack_ch_id = new_id("chan", suffix="sl")

    repo.put_channel(Channel(
        channel_id=email_ch_id,
        agent_id=agent_id,
        org_id="org_xc",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": f"xcbot@agentcomms.dev"},
        status=ChannelStatus.ACTIVE,
    ))
    repo.put_channel(Channel(
        channel_id=sms_ch_id,
        agent_id=agent_id,
        org_id="org_xc",
        channel=ChannelType.SMS,
        mode=ChannelMode.PROVISION,
        config={"phone_e164": "+18005551234"},
        status=ChannelStatus.ACTIVE,
    ))
    repo.put_channel(Channel(
        channel_id=tg_ch_id,
        agent_id=agent_id,
        org_id="org_xc",
        channel=ChannelType.TELEGRAM,
        mode=ChannelMode.PROVISION,
        config={"bot_username": "xcbot", "bot_user_id": 777, "token_hash": "abc123"},
        status=ChannelStatus.ACTIVE,
    ))
    # Stub bridged slack (mode=bridge; no real OAuth)
    team_id = "T_XC_001"
    slack_ch_channel_id = "C_NOISE_01"
    repo.put_channel(Channel(
        channel_id=slack_ch_id,
        agent_id=agent_id,
        org_id="org_xc",
        channel=ChannelType.SLACK,
        mode=ChannelMode.BRIDGE,
        config={"team_id": team_id, "bot_user_id": "U_BOT_XC", "app_id": "A_XC"},
        status=ChannelStatus.ACTIVE,
    ))

    # ── Step 3: Seed 6 messages ────────────────────────────────────────────────
    base_ts = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)

    def _msg(i, channel_id, channel_type, is_dm, channel_native=None):
        ts = base_ts + timedelta(seconds=i * 60)
        msg = UnifiedMessage(
            message_id=new_id("msg"),
            agent_id=agent_id,
            org_id="org_xc",
            channel_id=channel_id,
            channel=channel_type,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            **{"from": Party(address=f"sender-{i}@example.com")},
            body_text=f"Message {i}",
            is_dm=is_dm,
            received_at=ts,
            channel_native=channel_native or {},
        )
        return msg

    # 4 DMs (is_dm=True)
    email_dm = _msg(1, email_ch_id, ChannelType.EMAIL, is_dm=True)
    sms_dm = _msg(2, sms_ch_id, ChannelType.SMS, is_dm=True)
    slack_dm = _msg(3, slack_ch_id, ChannelType.SLACK, is_dm=True,
                    channel_native={
                        "team_id": team_id,
                        "channel_id": "D_DM_001",  # D... prefix → DM channel
                        "ts": "1000000003.000000",
                        "is_mention": False,
                        "event_type": "message",
                    })
    slack_mention = _msg(4, slack_ch_id, ChannelType.SLACK, is_dm=True,
                         channel_native={
                             "team_id": team_id,
                             "channel_id": slack_ch_channel_id,
                             "ts": "1000000004.000000",
                             "is_mention": True,
                             "event_type": "app_mention",
                         })

    # 2 non-DMs (is_dm=False)
    slack_noise = _msg(5, slack_ch_id, ChannelType.SLACK, is_dm=False,
                       channel_native={
                           "team_id": team_id,
                           "channel_id": slack_ch_channel_id,
                           "ts": "1000000005.000000",
                           "is_mention": False,
                           "event_type": "message",
                       })
    tg_noise = _msg(6, tg_ch_id, ChannelType.TELEGRAM, is_dm=False,
                    channel_native={
                        "chat_id": "-1234567",
                        "chat_type": "supergroup",
                        "update_id": 9001,
                    })

    for m in [email_dm, sms_dm, slack_dm, slack_mention, slack_noise, tg_noise]:
        repo.put_message(m)

    # ── Step 4: GET /v1/agents/{id}/messages → exactly 4 DMs ─────────────────
    with patch("core.api.messages_handler.get_repo", return_value=repo):
        resp_inbox = messages_mod.handler(
            _apigw_event(
                "GET",
                f"/v1/agents/{agent_id}/messages",
                path_params={"agent_id": agent_id},
            ),
            None,
        )

    assert resp_inbox["statusCode"] == 200, f"Inbox failed: {resp_inbox['body']}"
    inbox_body = json.loads(resp_inbox["body"])
    msgs = inbox_body["messages"]

    assert len(msgs) == 4, (
        f"Expected exactly 4 DMs in unified inbox, got {len(msgs)}. "
        f"Channels: {[m['channel'] for m in msgs]}, "
        f"is_dm values: {[m['is_dm'] for m in msgs]}"
    )

    # All returned must have is_dm=True
    for m in msgs:
        assert m["is_dm"] is True, f"Non-DM message leaked into inbox: {m['message_id']}"

    # Must be in descending received_at order
    received_ats = [m["received_at"] for m in msgs]
    assert received_ats == sorted(received_ats, reverse=True), (
        f"Inbox not in descending order: {received_ats}"
    )

    # Verify all 4 channel types represented
    channels_in_inbox = {m["channel"] for m in msgs}
    assert "email" in channels_in_inbox
    assert "sms" in channels_in_inbox
    assert "slack" in channels_in_inbox

    # The 2 non-DM items must NOT appear in the unified inbox
    non_dm_ids = {slack_noise.message_id, tg_noise.message_id}
    inbox_ids = {m["message_id"] for m in msgs}
    assert not non_dm_ids.intersection(inbox_ids), (
        f"Non-DM items leaked into unified inbox: {non_dm_ids & inbox_ids}"
    )

    # ── Step 5: Slack channel-native — 1 noise item ────────────────────────────
    # GET /v1/agents/{id}/slack/workspaces/{team_id}/channels/{ch_id}/messages
    # Patch _get_table + _slack_client_for_channel (no real OAuth/token needed).
    mock_slack_client = MagicMock()
    # conversations.history returns nothing (all channel msgs are from our repo via GSI4).
    mock_slack_client.conversations_history.return_value = {"messages": []}

    with (
        patch("core.api.slack_native_handler._get_table", return_value=agentcomms_table),
        patch("core.api.slack_native_handler._slack_client_for_channel",
              return_value=mock_slack_client),
    ):
        resp_slack_ch = slack_native_mod.handler(
            _apigw_event(
                "GET",
                f"/v1/agents/{agent_id}/slack/workspaces/{team_id}/channels/{slack_ch_channel_id}/messages",
                path_params={
                    "agent_id": agent_id,
                    "team_id": team_id,
                    "channel_id": slack_ch_channel_id,
                },
            ),
            None,
        )

    assert resp_slack_ch["statusCode"] == 200, (
        f"Slack channel messages failed: {resp_slack_ch['body']}"
    )
    slack_ch_body = json.loads(resp_slack_ch["body"])
    slack_msgs = slack_ch_body.get("messages", [])

    # At minimum the slack_noise item should be found via GSI4 on the slack channel.
    # (slack_mention also lives in this channel, but it IS a DM — still accessible here.)
    slack_noise_found = any(
        m.get("message_id") == slack_noise.message_id
        for m in slack_msgs
    )
    assert slack_noise_found, (
        f"Slack noise item not visible in channel-native surface. "
        f"Got message_ids: {[m.get('message_id') for m in slack_msgs]}"
    )

    # ── Step 6: Telegram native — 1 noise item ────────────────────────────────
    # GET /v1/agents/{id}/telegram/chats/{chat_id}/messages
    # Patch _get_table so the handler uses our moto table.
    with patch("core.api.telegram_native_handler._get_table", return_value=agentcomms_table):
        resp_tg = telegram_native_mod.handler(
            _apigw_event(
                "GET",
                f"/v1/agents/{agent_id}/telegram/chats/-1234567/messages",
                path_params={"agent_id": agent_id, "chat_id": "-1234567"},
            ),
            None,
        )

    assert resp_tg["statusCode"] == 200, (
        f"Telegram chat messages failed: {resp_tg['body']}"
    )
    tg_body = json.loads(resp_tg["body"])
    tg_msgs = tg_body.get("messages", [])

    tg_noise_found = any(
        m.get("message_id") == tg_noise.message_id
        for m in tg_msgs
    )
    assert tg_noise_found, (
        f"Telegram noise item not visible in chat-native surface. "
        f"Got message_ids: {[m.get('message_id') for m in tg_msgs]}"
    )
