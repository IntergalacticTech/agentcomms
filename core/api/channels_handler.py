# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/channels_handler.py
"""
/v1/agents/{agent_id}/channels/* route handler.

Dispatches on METHOD + path pattern.  Handles:
  GET    /v1/agents/{id}/channels                  — list all channels
  POST   /v1/agents/{id}/channels                  — create / provision or bridge
  GET    /v1/agents/{id}/channels/{channel_id}     — get single channel
  PATCH  /v1/agents/{id}/channels/{channel_id}     — update config/status
  DELETE /v1/agents/{id}/channels/{channel_id}     — teardown + remove
"""
from __future__ import annotations

from core.api._common import Caller, err, get_repo, no_content, ok, parse_body
from core.adapters.registry import load_registry
from core.data.models import Agent, Channel, ChannelMode, ChannelStatus, ChannelType
from core.data.ulid_ import new_id


_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_registry()
    return _REGISTRY


def _channel_to_response(ch: Channel) -> dict:
    return {
        "channel_id": ch.channel_id,
        "agent_id": ch.agent_id,
        "channel": ch.channel.value,
        "mode": ch.mode.value,
        "status": ch.status.value,
        "config": ch.config,
        "created_at": ch.created_at.isoformat(),
        "updated_at": ch.updated_at.isoformat(),
    }


def _get_agent(repo, caller: Caller, agent_id: str) -> Agent | None:
    """Return the agent iff it belongs to caller's org; None otherwise."""
    return repo.get_agent(org_id=caller.org_id, agent_id=agent_id)


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()

    agent_id = pp.get("agent_id")
    channel_id = pp.get("channel_id")

    if not agent_id:
        return err("agent_id required", 400)

    # Ownership check — all sub-routes require the agent to exist and belong to caller's org
    agent = _get_agent(repo, caller, agent_id)
    if not agent:
        return err("agent not found", 404)

    # ── GET /v1/agents/{id}/channels ────────────────────────────────
    if method == "GET" and not channel_id:
        channels = repo.list_channels(agent_id=agent_id)
        return ok({"channels": [_channel_to_response(c) for c in channels]})

    # ── POST /v1/agents/{id}/channels ───────────────────────────────
    if method == "POST" and not channel_id:
        body = parse_body(event)
        channel_name = body.get("channel")
        if not channel_name:
            return err("channel is required", 400)

        registry = _registry()
        entry = registry.get(channel_name)
        if not entry:
            return err(f"unknown channel type: {channel_name}", 400)

        config = body.get("config") or {}
        mode_hint = body.get("mode", "provision")

        if mode_hint == "bridge" and "bridge" in entry.modes:
            # B-mode: bridge_start
            bs = entry.adapter.bridge_start(agent=agent, config=config)
            ch = Channel(
                channel_id=new_id("chan", suffix=channel_name[:2]),
                agent_id=agent_id,
                org_id=caller.org_id,
                channel=ChannelType(channel_name),
                mode=ChannelMode.BRIDGE,
                config={"oauth_state": bs.state, "oauth_url": bs.oauth_url},
                status=ChannelStatus.PENDING_OAUTH,
            )
        else:
            # A-mode: provision (default)
            provision_result = entry.adapter.provision(agent=agent, config=config)
            address_index = None
            if channel_name == "email":
                address_index = provision_result.details.get("address")
            ch = Channel(
                channel_id=provision_result.channel_id,
                agent_id=agent_id,
                org_id=caller.org_id,
                channel=ChannelType(channel_name),
                mode=ChannelMode.PROVISION,
                config=provision_result.details,
                status=ChannelStatus(provision_result.status)
                    if provision_result.status in [e.value for e in ChannelStatus]
                    else ChannelStatus.PROVISIONING,
                address_index_value=address_index,
            )

        repo.put_channel(ch)
        return ok(_channel_to_response(ch), status=201)

    # ── GET /v1/agents/{id}/channels/{channel_id} ───────────────────
    if method == "GET" and channel_id:
        # channel_id encodes type: e.g. "chan_em_01J..." — scan list to find it
        channels = repo.list_channels(agent_id=agent_id)
        ch = next((c for c in channels if c.channel_id == channel_id), None)
        if not ch:
            return err("channel not found", 404)
        return ok(_channel_to_response(ch))

    # ── PATCH /v1/agents/{id}/channels/{channel_id} ─────────────────
    if method == "PATCH" and channel_id:
        channels = repo.list_channels(agent_id=agent_id)
        ch = next((c for c in channels if c.channel_id == channel_id), None)
        if not ch:
            return err("channel not found", 404)
        body = parse_body(event)
        # Allow updating config and/or status
        if "config" in body:
            ch = ch.model_copy(update={"config": {**ch.config, **body["config"]}})
        if "status" in body:
            try:
                ch = ch.model_copy(update={"status": ChannelStatus(body["status"])})
            except ValueError:
                return err(f"invalid status: {body['status']}", 400)
        from datetime import datetime, timezone
        ch = ch.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        repo.put_channel(ch)
        return ok(_channel_to_response(ch))

    # ── DELETE /v1/agents/{id}/channels/{channel_id} ────────────────
    if method == "DELETE" and channel_id:
        channels = repo.list_channels(agent_id=agent_id)
        ch = next((c for c in channels if c.channel_id == channel_id), None)
        if not ch:
            return err("channel not found", 404)

        # Call adapter teardown if available
        registry = _registry()
        entry = registry.get(ch.channel.value)
        if entry and hasattr(entry.adapter, "teardown"):
            try:
                entry.adapter.teardown(channel=ch)
            except Exception:
                pass  # best-effort; still delete the record

        repo.table.delete_item(
            Key={"PK": f"AGT#{agent_id}", "SK": f"CHAN#{ch.channel.value}#{channel_id}"}
        )
        return no_content()

    return err("not found", 404)
