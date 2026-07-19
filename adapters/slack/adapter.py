# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/slack/adapter.py
"""
Slack channel adapter for AgentComms.

Bridge-mode only for v0.1. Each Agent gets one Slack workspace connection
via the OAuth v2 flow. Bot messages are routed via the Slack Events API.

Implements the ChannelAdapter contract from core/adapters/base.py.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from core.adapters.base import (
    BridgeResult, BridgeStart, ChannelAdapter, HealthStatus, IngestPayload,
    NativeContainer, OutboundMessage, ProvisionResult, SendResult,
)
from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    MessageDirection, MessageStatus, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id

from adapters.slack.normalize import parse_slack_event
from adapters.slack.oauth import (
    build_oauth_url, get_and_consume_oauth_state, get_workspace_token,
    delete_workspace_token, store_oauth_state, store_workspace_token,
    exchange_oauth_code,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    import boto3
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _slack_client(token: str):
    """Return a Slack WebClient configured with the given token."""
    from slack_sdk import WebClient
    return WebClient(token=token)


def _lookup_slack_channel_by_team(repo: Repo, team_id: str):
    """Resolve a Slack channel from team_id alone.

    Fallback for event_callback payloads that omit the 'authorizations' array:
    without it the bot_user_id is unknown, so the exact GSI2 address
    ({team_id}:{bot_user_id}) cannot be formed. Slack v0.1 connects one
    workspace per channel, so team_id resolves to a single Slack channel.

    GSI2's partition key embeds the bot_user_id, so a team-only lookup can't use
    it — we fall back to a bounded scan (a handful of pages) filtered on
    config.team_id. This is an infrequent path; a dedicated team-only index is
    the preferred long-term fix (see workstream deferred notes).
    """
    if not team_id:
        return None
    from boto3.dynamodb.conditions import Attr

    filter_expr = (
        Attr("entity").eq("channel")
        & Attr("channel").eq("slack")
        & Attr("config.team_id").eq(team_id)
    )
    start_key = None
    for _ in range(5):  # bound the work to avoid unbounded scans on this path
        kwargs: dict[str, Any] = {"FilterExpression": filter_expr, "Limit": 200}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        try:
            resp = repo.table.scan(**kwargs)
        except Exception as e:
            logger.warning("team-only slack lookup scan failed: %s", e)
            return None
        items = resp.get("Items", [])
        if items:
            item = items[0]
            return repo.get_channel(
                agent_id=item["agent_id"], channel="slack", channel_id=item["channel_id"],
            )
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            break
    return None


class SlackAdapter(ChannelAdapter):
    """Slack channel adapter — bridge (OAuth) mode only in v0.1."""

    channel_name = "slack"
    supports_modes = ["bridge"]

    # ── provision / teardown / health ──────────────────────────────────────

    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult:
        """Slack v0.1 does not support provision mode; use bridge mode."""
        raise NotImplementedError(
            "Slack v0.1 requires bridge mode; use POST /v1/agents with "
            "bridge:{slack:{return_url:...}}"
        )

    def bridge_start(self, *, agent: Agent, config: dict[str, Any]) -> BridgeStart:
        """Initiate Slack OAuth v2 flow.

        config must contain:
          - return_url (str): where to redirect after OAuth completes.

        Returns a BridgeStart with:
          - oauth_url: the Slack authorization URL
          - state: random nonce stored in DynamoDB for CSRF protection
          - instructions: human-readable instructions
        """
        return_url = config.get("return_url", "")
        if not return_url:
            raise ValueError("bridge_start requires config.return_url")

        # Generate random state nonce (16 hex bytes = 32 chars)
        state = secrets.token_hex(16)

        # Store state in DynamoDB with 10-minute TTL
        store_oauth_state(
            state=state,
            return_url=return_url,
            agent_id=agent.agent_id,
            org_id=agent.org_id,
        )

        # Build the Slack OAuth URL
        oauth_url = build_oauth_url(return_url=return_url, state=state)

        return BridgeStart(
            oauth_url=oauth_url,
            state=state,
            instructions=(
                "Visit the oauth_url to authorize AgentComms to connect to your "
                "Slack workspace. You will be redirected back to return_url when complete."
            ),
        )

    def bridge_complete(
        self, *, channel: Channel, callback_params: dict[str, Any]
    ) -> BridgeResult:
        """Complete Slack OAuth v2 flow.

        callback_params must contain:
          - code: the OAuth authorization code from Slack
          - redirect_uri: the redirect_uri used in bridge_start
          - team_id: the Slack team ID
          - bot_user_id: the bot user ID
          - app_id: the Slack app ID
          - bot_token: the bot access token

        Stores the bot token in SSM and updates the Channel record.
        """
        team_id = callback_params["team_id"]
        bot_token = callback_params["bot_token"]
        bot_user_id = callback_params.get("bot_user_id", "")
        app_id = callback_params.get("app_id", "")

        # Store bot token in SSM
        store_workspace_token(team_id, bot_token)

        # Update channel
        channel.config = {
            "team_id": team_id,
            "bot_user_id": bot_user_id,
            "app_id": app_id,
        }
        channel.status = ChannelStatus.ACTIVE
        channel.address_index_value = f"{team_id}:{bot_user_id}"

        repo = Repo(_get_table())
        repo.put_channel(channel)

        return BridgeResult(
            status="active",
            channel_id=channel.channel_id,
            details={
                "team_id": team_id,
                "bot_user_id": bot_user_id,
                "app_id": app_id,
            },
        )

    def teardown(self, *, channel: Channel) -> None:
        """Revoke the Slack bot token and delete SSM parameter."""
        team_id = channel.config.get("team_id", "")
        if not team_id:
            logger.warning("teardown: channel %s has no team_id", channel.channel_id)
            return None

        try:
            bot_token = get_workspace_token(team_id)
            client = _slack_client(bot_token)
            client.auth_revoke(test=False)
        except Exception as e:
            logger.error("auth.revoke failed: %s", e)

        try:
            delete_workspace_token(team_id)
        except Exception as e:
            logger.error("delete_workspace_token failed: %s", e)

        return None

    def health_check(self, *, channel: Channel) -> HealthStatus:
        """Verify the Slack bot token is still valid via auth.test."""
        team_id = channel.config.get("team_id", "")
        now = datetime.now(timezone.utc).isoformat()

        if not team_id:
            return HealthStatus(
                ok=False,
                last_success_at=now,
                error="no team_id in channel config",
            )

        try:
            bot_token = get_workspace_token(team_id)
            client = _slack_client(bot_token)
            resp = client.auth_test()
            if resp.get("ok"):
                return HealthStatus(ok=True, last_success_at=now)
            return HealthStatus(
                ok=False,
                last_success_at=now,
                error=f"auth.test returned ok=false: {resp.get('error')}",
            )
        except Exception as e:
            return HealthStatus(ok=False, last_success_at=now, error=str(e))

    # ── ingest (inbound) ────────────────────────────────────────────────────

    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None:
        """Parse Slack Events API payload into a UnifiedMessage.

        Handles:
          - url_verification: returns None (challenge is handled at Lambda level)
          - event_callback: converts message / app_mention events to UnifiedMessage
        """
        import json as _json

        body = payload.body
        if isinstance(body, bytes):
            body = _json.loads(body)

        event_type = body.get("type", "")

        # url_verification is handled at the Lambda handler level before ingest
        if event_type == "url_verification":
            return None

        if event_type != "event_callback":
            return None

        team_id = body.get("team_id", "")
        event = body.get("event", {})
        bot_user_id_from_auth = ""

        # Extract bot_user_id from authorizations array
        authorizations = body.get("authorizations", [])
        if authorizations:
            bot_user_id_from_auth = authorizations[0].get("user_id", "")

        # Look up the channel by GSI2: ADDR#slack#{team_id}:{bot_user_id}
        repo = Repo(_get_table())
        channel = None
        if bot_user_id_from_auth:
            address = f"{team_id}:{bot_user_id_from_auth}"
            channel = repo.lookup_channel_by_address(channel="slack", address=address)

        # Fallback: 'authorizations' absent (or exact address unresolved) — the
        # address would be "{team_id}:" which never matches. Resolve by team_id.
        if channel is None and team_id:
            channel = _lookup_slack_channel_by_team(repo, team_id)

        if channel is None:
            logger.info(
                "ingest: no slack channel for team=%s bot_user=%s",
                team_id, bot_user_id_from_auth,
            )
            return None

        bot_user_id = channel.config.get("bot_user_id", bot_user_id_from_auth)

        # Idempotency check
        ts = event.get("ts", "")
        external_id = f"{team_id}:{ts}"
        if ts:
            existing = repo.lookup_message_by_external_id(
                channel="slack", external_id=external_id,
            )
            if existing:
                logger.info("ingest: duplicate slack event %s, skipping", external_id)
                return None

        msg = parse_slack_event(
            body,
            channel_id=channel.channel_id,
            agent_id=channel.agent_id,
            org_id=channel.org_id,
            bot_user_id=bot_user_id,
        )
        return msg

    # ── send (outbound) ─────────────────────────────────────────────────────

    def send(self, *, channel: Channel, message: OutboundMessage) -> SendResult:
        """Send a message via Slack chat.postMessage.

        If message.to is "slack:T{team}:U{user}", calls conversations.open
        first to get (or create) the DM channel, then posts to that channel.

        Otherwise, message.to should be a Slack channel ID (C.../D...).
        """
        team_id = channel.config.get("team_id", "")
        if not team_id:
            return SendResult(channel_native_id="", status="failed", error="no team_id in channel config")

        try:
            bot_token = get_workspace_token(team_id)
        except Exception as e:
            return SendResult(channel_native_id="", status="failed", error=f"token retrieval failed: {e}")

        client = _slack_client(bot_token)
        to = message.to if isinstance(message.to, str) else str(message.to)

        # Parse "slack:T{team}:U{user}" → open DM channel first
        if to.startswith("slack:") and ":U" in to:
            parts = to.split(":")
            # Format: slack:{team_id}:{user_id}  e.g. slack:T012AB3C4:U012AB3C4
            if len(parts) >= 3:
                user_id = parts[2]
                try:
                    dm_resp = client.conversations_open(users=[user_id])
                    to = dm_resp["channel"]["id"]
                except Exception as e:
                    return SendResult(channel_native_id="", status="failed", error=f"conversations.open failed: {e}")

        try:
            resp = client.chat_postMessage(
                channel=to,
                text=message.body_text,
            )
            ts = resp.get("ts", "")
            return SendResult(
                channel_native_id=f"{to}:{ts}",
                status="sent",
            )
        except Exception as e:
            logger.exception("chat.postMessage failed")
            return SendResult(channel_native_id="", status="failed", error=str(e))

    # ── Native sub-surfaces ─────────────────────────────────────────────────

    def list_native_containers(self, *, channel: Channel) -> list[NativeContainer]:
        """Return the connected Slack workspace as a NativeContainer."""
        team_id = channel.config.get("team_id", "")
        if not team_id:
            return []

        try:
            bot_token = get_workspace_token(team_id)
            client = _slack_client(bot_token)
            resp = client.auth_test()
            team_name = resp.get("team", team_id)
            return [NativeContainer(id=team_id, name=team_name, type="workspace")]
        except Exception as e:
            logger.error("list_native_containers failed: %s", e)
            return [NativeContainer(id=team_id, name=team_id, type="workspace")]

    def list_native_messages(
        self, *, channel: Channel, container_id: str, **filters: Any
    ) -> list[UnifiedMessage]:
        """List messages from a Slack channel via conversations.history.

        container_id should be a Slack channel ID (C...).
        Returns UnifiedMessage objects with is_dm=False.
        """
        team_id = channel.config.get("team_id", "")
        if not team_id:
            return []

        try:
            bot_token = get_workspace_token(team_id)
            client = _slack_client(bot_token)
            bot_user_id = channel.config.get("bot_user_id", "")

            resp = client.conversations_history(
                channel=container_id,
                limit=filters.get("limit", 50),
            )
            messages = resp.get("messages", [])
            result = []
            for msg_data in messages:
                unified = parse_slack_event(
                    {
                        "type": "event_callback",
                        "team_id": team_id,
                        "event": {**msg_data, "channel": container_id},
                        "authorizations": [{"user_id": bot_user_id}],
                    },
                    channel_id=channel.channel_id,
                    agent_id=channel.agent_id,
                    org_id=channel.org_id,
                    bot_user_id=bot_user_id,
                )
                if unified is not None:
                    unified.is_dm = False  # force non-DM for channel messages
                    result.append(unified)
            return result
        except Exception as e:
            logger.error("list_native_messages failed: %s", e)
            return []

    def send_to_native_target(
        self, *, channel: Channel, target: dict[str, Any], message: OutboundMessage,
    ) -> SendResult:
        """Post a message to a specific Slack channel ID.

        target must contain:
          - channel_id (str): the Slack channel ID to post to
        """
        slack_channel_id = target.get("channel_id", "")
        if not slack_channel_id:
            return SendResult(channel_native_id="", status="failed", error="no channel_id in target")

        # Temporarily override message.to with the target channel
        from copy import copy
        msg_copy = copy(message)
        msg_copy = OutboundMessage(
            to=slack_channel_id,
            body_text=message.body_text,
            body_html=message.body_html,
            subject=message.subject,
            attachments=message.attachments,
            channel_native_overrides=message.channel_native_overrides,
        )
        return self.send(channel=channel, message=msg_copy)
