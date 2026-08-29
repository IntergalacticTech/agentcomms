# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# adapters/telegram/adapter.py
"""
Telegram channel adapter for AgentComms.

Provision mode only (A-mode): deployer creates a bot via @BotFather and
provides the token. Each Agent gets its own bot. Inbound messages arrive
via a webhook registered with setWebhook.

Implements the ChannelAdapter contract from core/adapters/base.py.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from core.adapters.base import (
    ChannelAdapter, HealthStatus, IngestPayload, NativeContainer,
    OutboundMessage, ProvisionResult, SendResult,
)
from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType,
    MessageDirection, MessageStatus, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id

from adapters.telegram.bot_client import TelegramBotClient, TelegramAPIError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    import boto3
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _api_host() -> str:
    return os.environ.get("AGENTCOMMS_API_HOST", "api.agentcomms.dev")


def _env() -> str:
    return os.environ.get("AGENTCOMMS_ENV", "prod")


def _token_hash(bot_token: str) -> str:
    """First 16 hex chars of sha256(bot_token)."""
    return hashlib.sha256(bot_token.encode("utf-8")).hexdigest()[:16]


# ── SSM helpers ────────────────────────────────────────────────────────────────

def store_bot_token(channel_id: str, bot_token: str) -> None:
    """Store bot token as a SecureString in SSM."""
    import boto3
    env = _env()
    name = f"/agentcomms/{env}/adapters/telegram/tokens/{channel_id}"
    boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1")).put_parameter(
        Name=name,
        Value=bot_token,
        Type="SecureString",
        Overwrite=True,
    )


def get_bot_token(channel_id: str) -> str:
    """Retrieve stored bot token from SSM."""
    import boto3
    env = _env()
    name = f"/agentcomms/{env}/adapters/telegram/tokens/{channel_id}"
    resp = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1")).get_parameter(
        Name=name,
        WithDecryption=True,
    )
    return resp["Parameter"]["Value"]


def delete_bot_token(channel_id: str) -> None:
    """Delete stored bot token from SSM."""
    import boto3
    env = _env()
    name = f"/agentcomms/{env}/adapters/telegram/tokens/{channel_id}"
    try:
        boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1")).delete_parameter(Name=name)
    except Exception as e:
        logger.warning("delete_bot_token: %s", e)


def _webhook_secret_param(channel_id: str) -> str:
    return f"/agentcomms/{_env()}/adapters/telegram/webhook_secrets/{channel_id}"


def store_webhook_secret(channel_id: str, secret_token: str) -> None:
    """Store the webhook secret_token as a SecureString in SSM.

    This value is INDEPENDENT of the public {token_hash} URL path segment: it
    is the shared secret Telegram echoes back in the
    X-Telegram-Bot-Api-Secret-Token header, and must never be derivable from
    (or equal to) anything that appears in the public webhook URL.
    """
    import boto3
    boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1")).put_parameter(
        Name=_webhook_secret_param(channel_id),
        Value=secret_token,
        Type="SecureString",
        Overwrite=True,
    )


def get_webhook_secret(channel_id: str) -> str | None:
    """Retrieve the stored webhook secret_token, or None if not provisioned."""
    import boto3
    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    try:
        resp = ssm.get_parameter(Name=_webhook_secret_param(channel_id), WithDecryption=True)
    except Exception as e:
        logger.info("get_webhook_secret miss for %s: %s", channel_id, e)
        return None
    return resp["Parameter"]["Value"]


def delete_webhook_secret(channel_id: str) -> None:
    """Delete the stored webhook secret_token from SSM."""
    import boto3
    try:
        boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1")).delete_parameter(
            Name=_webhook_secret_param(channel_id)
        )
    except Exception as e:
        logger.warning("delete_webhook_secret: %s", e)


# ── Adapter ────────────────────────────────────────────────────────────────────

class TelegramAdapter(ChannelAdapter):
    """Telegram channel adapter — provision (A-mode) only."""

    channel_name = "telegram"
    supports_modes = ["provision"]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult:
        """Provision a Telegram channel by registering a bot webhook.

        config must contain:
          - bot_token (str): token from @BotFather

        Steps:
          1. Validate token via getMe.
          2. Compute token_hash = sha256(bot_token)[:16] (public URL path id).
          3. Generate an INDEPENDENT random webhook secret_token.
          4. Call setWebhook with URL https://{api_host}/webhooks/telegram/{token_hash}
             and the random secret_token (NOT the token_hash).
          5. Store token + webhook secret in SSM (both keyed by channel_id).
          6. Return ProvisionResult.
        """
        bot_token = config.get("bot_token", "")
        if not bot_token:
            raise ValueError("provision requires config.bot_token")

        client = TelegramBotClient(bot_token)
        bot_info = client.get_me()
        bot_username = bot_info.get("username", "")
        bot_id = bot_info.get("id")

        tok_hash = _token_hash(bot_token)
        webhook_url = f"https://{_api_host()}/webhooks/telegram/{tok_hash}"

        channel_id = new_id("chan", suffix="tg")

        # Generate an INDEPENDENT random secret_token. It is stored in SSM only
        # and is never placed in the (public) webhook URL, so the shared secret
        # is not exposed by the {token_hash} path segment.
        secret_token = secrets.token_hex(32)

        # setWebhook — authenticate inbound updates with the random secret_token
        client.set_webhook(webhook_url, secret_token=secret_token)

        # Store token + webhook secret in SSM
        store_bot_token(channel_id, bot_token)
        store_webhook_secret(channel_id, secret_token)

        # Persist channel to DynamoDB
        channel = Channel(
            channel_id=channel_id,
            agent_id=agent.agent_id,
            org_id=agent.org_id,
            channel=ChannelType.TELEGRAM,
            mode=ChannelMode.PROVISION,
            config={
                "bot_username": bot_username,
                "bot_id": bot_id,
                "token_hash": tok_hash,
            },
            status=ChannelStatus.ACTIVE,
            # GSI2 key: token_hash is the stable lookup key for inbound routing
            address_index_value=f"token:{tok_hash}",
        )
        repo = Repo(_get_table())
        repo.put_channel(channel)

        return ProvisionResult(
            status="active",
            channel_id=channel_id,
            details={
                "bot_username": bot_username,
                "bot_id": bot_id,
                "token_hash": tok_hash,
            },
        )

    def teardown(self, *, channel: Channel) -> None:
        """Delete the Telegram webhook and SSM token."""
        tok_hash = channel.config.get("token_hash", "")
        try:
            bot_token = get_bot_token(channel.channel_id)
            client = TelegramBotClient(bot_token)
            client.delete_webhook()
        except Exception as e:
            logger.error("teardown: delete_webhook failed: %s", e)

        try:
            delete_bot_token(channel.channel_id)
        except Exception as e:
            logger.error("teardown: delete_bot_token failed: %s", e)

        try:
            delete_webhook_secret(channel.channel_id)
        except Exception as e:
            logger.error("teardown: delete_webhook_secret failed: %s", e)

        return None

    def health_check(self, *, channel: Channel) -> HealthStatus:
        """Verify the bot token is still valid via getMe."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            bot_token = get_bot_token(channel.channel_id)
            client = TelegramBotClient(bot_token)
            info = client.get_me()
            username = info.get("username", "?")
            return HealthStatus(ok=True, last_success_at=now)
        except Exception as e:
            return HealthStatus(ok=False, last_success_at=now, error=str(e))

    # ── Ingest (inbound webhook) ───────────────────────────────────────────────

    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None:
        """Parse a Telegram Update payload into a UnifiedMessage.

        Authentication:
          Validates the X-Telegram-Bot-Api-Secret-Token header against the
          channel's stored token_hash. Drops the update on mismatch.

        DM inference:
          - message.chat.type == "private" → is_dm=True
          - group/supergroup + bot @mention or reply to bot → is_dm=True
          - Otherwise → is_dm=False
        """
        headers = {k.lower(): v for k, v in payload.headers.items()}
        secret_header = headers.get("x-telegram-bot-api-secret-token", "")

        body = payload.body
        if isinstance(body, bytes):
            body = json.loads(body)

        # Resolve channel from path_params token_hash (set by ingest Lambda)
        token_hash = payload.path_params.get("token_hash", "")

        # GSI2 lookup: ADDR#telegram#token:{token_hash}
        repo = Repo(_get_table())
        address = f"token:{token_hash}"
        channel = repo.lookup_channel_by_address(channel="telegram", address=address)

        if channel is None:
            logger.info("ingest: no telegram channel for token_hash=%s", token_hash)
            return None

        # Authenticate via the X-Telegram-Bot-Api-Secret-Token header against
        # the INDEPENDENT secret stored in SSM (not the public token_hash).
        expected_secret = get_webhook_secret(channel.channel_id)
        if expected_secret is None:
            # Legacy channel provisioned before independent secrets existed:
            # fall back to the token_hash it was originally configured with.
            expected_secret = channel.config.get("token_hash", "")
        if not expected_secret or not hmac.compare_digest(secret_header, expected_secret):
            logger.warning(
                "ingest: secret_token mismatch for channel %s", channel.channel_id
            )
            return None

        # Only handle message updates; ignore everything else in v0.1
        message = body.get("message")
        if not message:
            return None

        update_id = body.get("update_id")
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        msg_id = message.get("message_id")
        text = message.get("text") or message.get("caption") or ""
        from_user = message.get("from", {})
        user_id = from_user.get("id")
        user_username = from_user.get("username", "")
        entities = message.get("entities", [])
        reply_to = message.get("reply_to_message")

        # DM inference
        bot_username = channel.config.get("bot_username", "")
        bot_id = channel.config.get("bot_id")

        if chat_type == "private":
            is_dm = True
        elif chat_type in ("group", "supergroup"):
            # Telegram entity offset/length are counted in UTF-16 code units,
            # not Python code points, so slice against the UTF-16-LE encoding to
            # stay correct after emoji / astral characters in the text.
            text_utf16 = text.encode("utf-16-le")

            def _entity_text(entity: dict) -> str:
                start = entity.get("offset", 0) * 2
                end = start + entity.get("length", 0) * 2
                return text_utf16[start:end].decode("utf-16-le", errors="replace")

            # Check for @mention of bot in entities
            bot_mentioned = any(
                e.get("type") == "mention"
                and _entity_text(e) == f"@{bot_username}"
                for e in entities
            )
            # Check for reply to bot's own message
            reply_to_bot = (
                reply_to is not None
                and reply_to.get("from", {}).get("id") == bot_id
            )
            is_dm = bot_mentioned or reply_to_bot
        else:
            is_dm = False

        reply_to_message_id = reply_to.get("message_id") if reply_to else None

        external_id = f"{chat_id}:{msg_id}"

        # Idempotency check
        existing = repo.lookup_message_by_external_id(
            channel="telegram", external_id=external_id
        )
        if existing:
            logger.info("ingest: duplicate telegram message %s, skipping", external_id)
            return None

        now = datetime.now(timezone.utc)

        # Build sender address
        if user_username:
            sender_address = f"telegram:user:{user_username}"
        else:
            sender_address = f"telegram:user:{user_id}"

        return UnifiedMessage(
            message_id=new_id("msg"),
            agent_id=channel.agent_id,
            org_id=channel.org_id,
            channel_id=channel.channel_id,
            channel=ChannelType.TELEGRAM,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            **{"from": Party(
                address=sender_address,
                platform_user_id=str(user_id) if user_id else None,
            )},
            to=[Party(address=f"telegram:bot:{bot_username}")],
            body_text=text,
            is_dm=is_dm,
            received_at=now,
            channel_native={
                "chat_id": chat_id,
                "chat_type": chat_type,
                "update_id": update_id,
                "entities": entities,
                "reply_to_message_id": reply_to_message_id,
            },
            external_id=external_id,
        )

    # ── Send (outbound) ────────────────────────────────────────────────────────

    def send(self, *, channel: Channel, message: OutboundMessage) -> SendResult:
        """Send a text message via Telegram sendMessage.

        message.to formats accepted:
          - "telegram:chat:{chat_id}"  → send to that chat
          - "telegram:user:{user_id}"  → DM (Telegram user_id == chat_id for private chats)
        """
        to = message.to if isinstance(message.to, str) else str(message.to)

        # Parse chat_id from message.to
        if to.startswith("telegram:chat:"):
            chat_id_str = to[len("telegram:chat:"):]
        elif to.startswith("telegram:user:"):
            chat_id_str = to[len("telegram:user:"):]
        else:
            chat_id_str = to

        # Try to convert to int for numeric chat_ids
        try:
            chat_id: int | str = int(chat_id_str)
        except (ValueError, TypeError):
            chat_id = chat_id_str

        # Get parse_mode + the matching body. When parse_mode is HTML we must
        # send the HTML body (sending body_text with parse_mode=HTML would ship
        # unformatted text and risk entity-parse errors from stray < & chars).
        parse_mode = "HTML" if message.body_html else None
        text_to_send = message.body_html if parse_mode == "HTML" else message.body_text

        # Get reply_to from thread_key if present
        reply_to_message_id: int | None = None
        if message.thread_key:
            try:
                # thread_key format: "{chat_id}:{message_id}"
                parts = message.thread_key.split(":")
                if len(parts) >= 2:
                    reply_to_message_id = int(parts[-1])
            except (ValueError, IndexError):
                pass

        try:
            bot_token = get_bot_token(channel.channel_id)
            client = TelegramBotClient(bot_token)
            result = client.send_message(
                chat_id=chat_id,
                text=text_to_send,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to_message_id,
            )
            msg_id = result.get("message_id")
            return SendResult(
                channel_native_id=str(msg_id),
                status="sent",
            )
        except Exception as e:
            logger.exception("telegram send_message failed")
            return SendResult(channel_native_id="", status="failed", error=str(e))

    # ── Native sub-surfaces ────────────────────────────────────────────────────

    def list_native_containers(self, *, channel: Channel) -> list[NativeContainer]:
        """Return unique chats the bot has seen messages from (via GSI4 dedup)."""
        repo = Repo(_get_table())
        messages = repo.list_channel_messages(
            channel_id=channel.channel_id, limit=200
        )
        seen: dict[str, NativeContainer] = {}
        for msg in messages:
            native = msg.channel_native or {}
            chat_id = native.get("chat_id")
            chat_type = native.get("chat_type", "unknown")
            if chat_id is not None:
                key = str(chat_id)
                if key not in seen:
                    seen[key] = NativeContainer(
                        id=key,
                        name=f"Chat {chat_id}",
                        type=chat_type,
                        metadata={"chat_id": chat_id, "chat_type": chat_type},
                    )
        return list(seen.values())

    def list_native_messages(
        self, *, channel: Channel, container_id: str, **filters: Any
    ) -> list[UnifiedMessage]:
        """List messages from a specific Telegram chat (GSI4 + filter on chat_id)."""
        repo = Repo(_get_table())
        messages = repo.list_channel_messages(
            channel_id=channel.channel_id, limit=filters.get("limit", 50)
        )
        return [
            m for m in messages
            if str(m.channel_native.get("chat_id", "")) == str(container_id)
        ]

    def send_to_native_target(
        self, *, channel: Channel, target: dict[str, Any], message: OutboundMessage,
    ) -> SendResult:
        """Send to a specific Telegram chat.

        target must contain:
          - chat_id (int|str): the Telegram chat ID
        """
        chat_id = target.get("chat_id")
        if chat_id is None:
            return SendResult(channel_native_id="", status="failed", error="no chat_id in target")

        from copy import copy
        msg_copy = OutboundMessage(
            to=f"telegram:chat:{chat_id}",
            body_text=message.body_text,
            body_html=message.body_html,
            subject=message.subject,
            attachments=message.attachments,
            thread_key=message.thread_key,
            channel_native_overrides=message.channel_native_overrides,
        )
        return self.send(channel=channel, message=msg_copy)
