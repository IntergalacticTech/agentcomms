# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/agents_handler.py
"""
/v1/agents/* route handlers.

Dispatches on METHOD + path pattern. Uses the adapter registry to provision
channels declared in the request body.
"""
from __future__ import annotations

from core.api._common import Caller, get_repo, err, ok, no_content, parse_body
from core.adapters.registry import load_registry
from core.data.models import Agent, Channel, ChannelMode, ChannelType, ChannelStatus
from core.data.ulid_ import new_id


_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_registry()
    return _REGISTRY


def _provision_channels(
    *, agent: Agent, provision: dict, bridge: dict
) -> list[Channel]:
    repo = get_repo()
    registry = _registry()
    results: list[Channel] = []

    # A-mode: provision
    for channel_name, config in (provision or {}).items():
        entry = registry.get(channel_name)
        if not entry:
            continue
        if channel_name == "push" and config is True:
            config = {}
        provision_result = entry.adapter.provision(agent=agent, config=config or {})
        address_index = None
        if channel_name == "email":
            address_index = provision_result.details.get("address")
        ch = Channel(
            channel_id=provision_result.channel_id,
            agent_id=agent.agent_id,
            org_id=agent.org_id,
            channel=ChannelType(channel_name),
            mode=ChannelMode.PROVISION,
            config=provision_result.details,
            status=ChannelStatus(provision_result.status)
                if provision_result.status in [e.value for e in ChannelStatus]
                else ChannelStatus.PROVISIONING,
            address_index_value=address_index,
        )
        repo.put_channel(ch)
        results.append(ch)

    # B-mode: bridge_start
    for channel_name, cfg in (bridge or {}).items():
        entry = registry.get(channel_name)
        if not entry or "bridge" not in entry.modes:
            continue
        bs = entry.adapter.bridge_start(agent=agent, config=cfg)
        ch = Channel(
            channel_id=new_id("chan", suffix=channel_name[:2]),
            agent_id=agent.agent_id,
            org_id=agent.org_id,
            channel=ChannelType(channel_name),
            mode=ChannelMode.BRIDGE,
            config={"oauth_state": bs.state, "oauth_url": bs.oauth_url},
            status=ChannelStatus.PENDING_OAUTH,
        )
        repo.put_channel(ch)
        results.append(ch)

    return results


def _channel_to_response(ch: Channel) -> dict:
    details = dict(ch.config)
    return {
        "channel": ch.channel.value,
        "channel_id": ch.channel_id,
        "status": ch.status.value,
        "details": details,
    }


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()

    # POST /v1/agents → create
    if method == "POST" and path == "/v1/agents":
        body = parse_body(event)
        if not body.get("name"):
            return err("name is required", 400)
        agent_id = new_id("agt")
        agent = Agent(
            agent_id=agent_id,
            org_id=caller.org_id,
            name=body["name"],
            metadata=body.get("metadata") or {},
        )
        repo.put_agent(agent)
        try:
            channels = _provision_channels(
                agent=agent,
                provision=body.get("provision") or {},
                bridge=body.get("bridge") or {},
            )
        except Exception as exc:  # noqa: BLE001
            return err(str(exc), 400)
        return ok({
            "agent_id": agent.agent_id,
            "name": agent.name,
            "channels": [_channel_to_response(c) for c in channels],
        }, status=201)

    # GET /v1/agents → list
    if method == "GET" and path == "/v1/agents":
        agents = repo.list_agents(org_id=caller.org_id)
        return ok({"agents": [{"agent_id": a.agent_id, "name": a.name} for a in agents]})

    # GET /v1/agents/{id} → read
    if method == "GET" and pp.get("agent_id"):
        agent = repo.get_agent(org_id=caller.org_id, agent_id=pp["agent_id"])
        if not agent:
            return err("agent not found", 404)
        return ok({"agent_id": agent.agent_id, "name": agent.name, "metadata": agent.metadata})

    # PUT /v1/agents/{id} → update name/metadata
    if method == "PUT" and pp.get("agent_id"):
        agent = repo.get_agent(org_id=caller.org_id, agent_id=pp["agent_id"])
        if not agent:
            return err("agent not found", 404)
        body = parse_body(event)
        updates: dict = {}
        if "name" in body:
            if not body.get("name"):
                return err("name cannot be empty", 400)
            updates["name"] = body["name"]
        if "metadata" in body:
            metadata = body.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                return err("metadata must be an object", 400)
            updates["metadata"] = metadata or {}
        if updates:
            from datetime import datetime, timezone
            updates["updated_at"] = datetime.now(timezone.utc)
            agent = agent.model_copy(update=updates)
            repo.put_agent(agent)
        return ok({
            "agent_id": agent.agent_id,
            "name": agent.name,
            "metadata": agent.metadata,
        })

    # DELETE /v1/agents/{id}
    if method == "DELETE" and pp.get("agent_id"):
        agent = repo.get_agent(org_id=caller.org_id, agent_id=pp["agent_id"])
        if not agent:
            return err("agent not found", 404)
        repo.table.delete_item(
            Key={"PK": f"ORG#{caller.org_id}", "SK": f"AGT#{pp['agent_id']}"}
        )
        return no_content()

    return err("not found", 404)
