# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/api/slack_native_handler.py
"""
Slack native sub-surface API routes.

Routes:
  GET  /v1/agents/{agent_id}/slack/workspaces
    → list slack Channels for the agent

  GET  /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels
    → conversations.list for channels the bot is in

  GET  /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels/{channel_id}/messages
    → conversations.history + GSI4 hybrid

  POST /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels/{channel_id}/messages
    → chat.postMessage to that channel

  POST /v1/agents/{agent_id}/slack/workspaces/{team_id}/users/{user_id}/messages
    → conversations.open + chat.postMessage (DM)
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


def _get_slack_channel(repo: Repo, agent_id: str, team_id: str):
    """Find the active Slack channel for the agent + team_id combo."""
    channels = repo.list_channels(agent_id=agent_id)
    for ch in channels:
        if ch.channel.value == "slack" and ch.config.get("team_id") == team_id:
            return ch
    return None


def _slack_client_for_channel(channel):
    """Get a Slack WebClient using the stored workspace token."""
    from adapters.slack.adapter import _slack_client
    from adapters.slack.oauth import get_workspace_token
    team_id = channel.config.get("team_id", "")
    token = get_workspace_token(team_id)
    return _slack_client(token)


def handler(event: dict, context) -> dict:
    """API Gateway event handler for all Slack native sub-surface routes."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    body_raw = event.get("body") or "{}"

    try:
        body = json.loads(body_raw) if body_raw else {}
    except (json.JSONDecodeError, ValueError):
        body = {}

    agent_id = path_params.get("agent_id", "")
    team_id = path_params.get("team_id", "")
    channel_id = path_params.get("channel_id", "")
    user_id = path_params.get("user_id", "")

    repo = Repo(_get_table())

    # ── Route dispatch ──

    # GET /v1/agents/{agent_id}/slack/workspaces
    if method == "GET" and path.endswith("/slack/workspaces") and not team_id:
        return _list_workspaces(repo, agent_id)

    # GET /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels
    if method == "GET" and team_id and not channel_id and not user_id and path.endswith("/channels"):
        return _list_channels(repo, agent_id, team_id)

    # GET /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels/{channel_id}/messages
    if method == "GET" and team_id and channel_id and path.endswith("/messages"):
        return _list_channel_messages(repo, agent_id, team_id, channel_id)

    # POST /v1/agents/{agent_id}/slack/workspaces/{team_id}/channels/{channel_id}/messages
    if method == "POST" and team_id and channel_id and path.endswith("/messages"):
        return _post_to_channel(repo, agent_id, team_id, channel_id, body)

    # POST /v1/agents/{agent_id}/slack/workspaces/{team_id}/users/{user_id}/messages
    if method == "POST" and team_id and user_id and path.endswith("/messages"):
        return _send_dm_to_user(repo, agent_id, team_id, user_id, body)

    return {"statusCode": 404, "body": json.dumps({"error": "not found"})}


def _list_workspaces(repo: Repo, agent_id: str) -> dict:
    """Return all Slack channels (workspaces) for the agent."""
    channels = repo.list_channels(agent_id=agent_id)
    workspaces = [
        {
            "channel_id": ch.channel_id,
            "team_id": ch.config.get("team_id"),
            "bot_user_id": ch.config.get("bot_user_id"),
            "status": ch.status.value,
        }
        for ch in channels
        if ch.channel.value == "slack"
    ]
    return {
        "statusCode": 200,
        "body": json.dumps({"workspaces": workspaces}),
    }


def _list_channels(repo: Repo, agent_id: str, team_id: str) -> dict:
    """List Slack channels the bot is in via conversations.list."""
    channel = _get_slack_channel(repo, agent_id, team_id)
    if channel is None:
        return {"statusCode": 404, "body": json.dumps({"error": "slack workspace not found"})}

    try:
        client = _slack_client_for_channel(channel)
        resp = client.conversations_list(types="public_channel,private_channel")
        channels = [
            {
                "id": c["id"],
                "name": c.get("name", ""),
                "is_member": c.get("is_member", False),
                "is_private": c.get("is_private", False),
                "num_members": c.get("num_members", 0),
            }
            for c in resp.get("channels", [])
            if c.get("is_member")
        ]
        return {
            "statusCode": 200,
            "body": json.dumps({"channels": channels}),
        }
    except Exception as e:
        logger.exception("conversations.list failed: %s", e)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _list_channel_messages(
    repo: Repo, agent_id: str, team_id: str, channel_id: str
) -> dict:
    """Hybrid: GSI4 DB messages + conversations.history backfill."""
    slack_channel = _get_slack_channel(repo, agent_id, team_id)
    if slack_channel is None:
        return {"statusCode": 404, "body": json.dumps({"error": "slack workspace not found"})}

    # GSI4 DB messages for this channel
    db_messages = repo.list_channel_messages(channel_id=slack_channel.channel_id, limit=50)
    # Filter to those from this Slack channel
    db_messages = [
        m for m in db_messages
        if m.channel_native.get("channel_id") == channel_id
    ]

    try:
        client = _slack_client_for_channel(slack_channel)
        resp = client.conversations_history(channel=channel_id, limit=50)
        slack_msgs = resp.get("messages", [])
    except Exception as e:
        logger.warning("conversations.history failed, using DB only: %s", e)
        slack_msgs = []

    # Return DB messages serialized (Slack messages are supplemental backfill)
    result = [
        json.loads(m.model_dump_json(by_alias=True))
        for m in db_messages
    ]

    return {
        "statusCode": 200,
        "body": json.dumps({
            "messages": result,
            "slack_history_count": len(slack_msgs),
        }),
    }


def _post_to_channel(
    repo: Repo, agent_id: str, team_id: str, slack_channel_id: str, body: dict
) -> dict:
    """Post a message to a Slack channel via chat.postMessage."""
    channel = _get_slack_channel(repo, agent_id, team_id)
    if channel is None:
        return {"statusCode": 404, "body": json.dumps({"error": "slack workspace not found"})}

    text = body.get("text", body.get("body_text", ""))
    if not text:
        return {"statusCode": 400, "body": json.dumps({"error": "text is required"})}

    try:
        client = _slack_client_for_channel(channel)
        resp = client.chat_postMessage(channel=slack_channel_id, text=text)
        return {
            "statusCode": 200,
            "body": json.dumps({
                "ok": True,
                "ts": resp.get("ts"),
                "channel": resp.get("channel"),
            }),
        }
    except Exception as e:
        logger.exception("chat.postMessage to channel failed: %s", e)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def _send_dm_to_user(
    repo: Repo, agent_id: str, team_id: str, user_id: str, body: dict
) -> dict:
    """Open a DM and send a message via conversations.open + chat.postMessage."""
    channel = _get_slack_channel(repo, agent_id, team_id)
    if channel is None:
        return {"statusCode": 404, "body": json.dumps({"error": "slack workspace not found"})}

    text = body.get("text", body.get("body_text", ""))
    if not text:
        return {"statusCode": 400, "body": json.dumps({"error": "text is required"})}

    try:
        client = _slack_client_for_channel(channel)
        dm_resp = client.conversations_open(users=[user_id])
        dm_channel_id = dm_resp["channel"]["id"]
        resp = client.chat_postMessage(channel=dm_channel_id, text=text)
        return {
            "statusCode": 200,
            "body": json.dumps({
                "ok": True,
                "ts": resp.get("ts"),
                "channel": dm_channel_id,
            }),
        }
    except Exception as e:
        logger.exception("DM send failed: %s", e)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
