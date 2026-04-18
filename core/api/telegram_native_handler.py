# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/api/telegram_native_handler.py
"""
Telegram native sub-surface API routes.

Routes:
  GET  /v1/agents/{agent_id}/telegram/chats
    → list Telegram chats the bot has seen (derived from past messages)

  GET  /v1/agents/{agent_id}/telegram/chats/{chat_id}/messages
    → list messages from a specific Telegram chat

  POST /v1/agents/{agent_id}/telegram/chats/{chat_id}/messages
    → send a message to a Telegram chat
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from core.data.models import ChannelType
from core.data.repo import Repo

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _get_telegram_channel(repo: Repo, agent_id: str):
    """Find the active Telegram channel for the agent (first one found)."""
    channels = repo.list_channels(agent_id=agent_id)
    for ch in channels:
        if ch.channel.value == "telegram" and ch.status.value == "active":
            return ch
    return None


def handler(event: dict, context) -> dict:
    """API Gateway event handler for all Telegram native sub-surface routes."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    body_raw = event.get("body") or "{}"

    try:
        body = json.loads(body_raw) if body_raw else {}
    except (json.JSONDecodeError, ValueError):
        body = {}

    agent_id = path_params.get("agent_id", "")
    chat_id = path_params.get("chat_id", "")

    repo = Repo(_get_table())

    # ── Route dispatch ──

    # GET /v1/agents/{agent_id}/telegram/chats
    if method == "GET" and not chat_id and path.endswith("/chats"):
        return _list_chats(repo, agent_id)

    # GET /v1/agents/{agent_id}/telegram/chats/{chat_id}/messages
    if method == "GET" and chat_id and path.endswith("/messages"):
        return _list_chat_messages(repo, agent_id, chat_id)

    # POST /v1/agents/{agent_id}/telegram/chats/{chat_id}/messages
    if method == "POST" and chat_id and path.endswith("/messages"):
        return _send_to_chat(repo, agent_id, chat_id, body)

    return {"statusCode": 404, "body": json.dumps({"error": "not found"})}


def _list_chats(repo: Repo, agent_id: str) -> dict:
    """Return unique Telegram chats the bot has interacted with."""
    channel = _get_telegram_channel(repo, agent_id)
    if channel is None:
        return {
            "statusCode": 200,
            "body": json.dumps({"chats": []}),
        }

    from adapters.telegram.adapter import TelegramAdapter
    adapter = TelegramAdapter()
    containers = adapter.list_native_containers(channel=channel)
    chats = [
        {
            "chat_id": c.id,
            "chat_type": c.type,
            "name": c.name,
        }
        for c in containers
    ]
    return {
        "statusCode": 200,
        "body": json.dumps({"chats": chats}),
    }


def _list_chat_messages(repo: Repo, agent_id: str, chat_id: str) -> dict:
    """List messages from a specific Telegram chat via GSI4 + chat_id filter."""
    channel = _get_telegram_channel(repo, agent_id)
    if channel is None:
        return {"statusCode": 404, "body": json.dumps({"error": "telegram channel not found"})}

    from adapters.telegram.adapter import TelegramAdapter
    adapter = TelegramAdapter()

    with _repo_table_patch(repo):
        messages = adapter.list_native_messages(
            channel=channel, container_id=chat_id
        )

    result = [
        json.loads(m.model_dump_json(by_alias=True))
        for m in messages
    ]
    return {
        "statusCode": 200,
        "body": json.dumps({"messages": result}),
    }


def _send_to_chat(repo: Repo, agent_id: str, chat_id: str, body: dict) -> dict:
    """Send a message to a Telegram chat."""
    channel = _get_telegram_channel(repo, agent_id)
    if channel is None:
        return {"statusCode": 404, "body": json.dumps({"error": "telegram channel not found"})}

    text = body.get("text", body.get("body_text", ""))
    if not text:
        return {"statusCode": 400, "body": json.dumps({"error": "text is required"})}

    from adapters.telegram.adapter import TelegramAdapter
    from core.adapters.base import OutboundMessage
    adapter = TelegramAdapter()

    message = OutboundMessage(
        to=f"telegram:chat:{chat_id}",
        body_text=text,
        body_html=body.get("body_html"),
    )

    try:
        result = adapter.send(channel=channel, message=message)
        if result.status == "sent":
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "ok": True,
                    "message_id": result.channel_native_id,
                }),
            }
        else:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": result.error or "send failed"}),
            }
    except Exception as e:
        logger.exception("send_to_chat failed: %s", e)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


class _repo_table_patch:
    """Context manager that patches _get_table for the adapter call."""
    def __init__(self, repo: Repo):
        self._table = repo.table

    def __enter__(self):
        import adapters.telegram.adapter as adapter_mod
        self._orig = adapter_mod._get_table
        adapter_mod._get_table = lambda: self._table
        return self

    def __exit__(self, *args):
        import adapters.telegram.adapter as adapter_mod
        adapter_mod._get_table = self._orig
