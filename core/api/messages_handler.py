# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/messages_handler.py
"""
/v1/agents/{agent_id}/messages/* route handler.

Unified inbox (GET) and send (POST).
"""
from __future__ import annotations

from datetime import datetime

from core.api._common import (
    Caller, err, get_repo, no_content, ok, parse_body, require_agent,
)
from core.adapters.registry import load_registry
from core.adapters.base import OutboundMessage
from core.data.models import (
    ChannelStatus, ChannelType, MessageDirection, MessageStatus, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id
from core.router.address import infer_channel, AmbiguousAddressError


_REGISTRY = None
def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_registry()
    return _REGISTRY


def _find_channel_for_send(
    *, repo: Repo, agent_id: str, channel_type: str,
):
    """Return the first ACTIVE Channel of given type on this agent, or None."""
    for ch in repo.list_channels(agent_id=agent_id):
        if ch.channel.value == channel_type and ch.status.value == "active":
            return ch
    return None


def _message_to_response(msg: UnifiedMessage) -> dict:
    item = msg.to_dynamodb_item()
    # Strip internal index keys from API response
    for k in list(item.keys()):
        if k.startswith("gsi") or k in ("PK", "SK", "entity"):
            item.pop(k, None)
    return item


def _find_message(repo: Repo, *, agent_id: str, message_id: str, qs: dict | None = None) -> UnifiedMessage | None:
    """Find a message by public ID, using the exact sort key when provided.

    `received_at_ms` is an internal DynamoDB optimization. API clients should
    be able to use stable message IDs without carrying a timestamp around.
    """
    qs = qs or {}
    if qs.get("received_at_ms"):
        try:
            ts_ms = int(qs["received_at_ms"])
        except (TypeError, ValueError):
            return None
        return repo.get_message(agent_id=agent_id, received_at_ms=ts_ms, message_id=message_id)
    return repo.find_message_by_id(agent_id=agent_id, message_id=message_id)


def _reply_subject(subject: str | None) -> str | None:
    if not subject:
        return None
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def _reply_native_overrides(original: UnifiedMessage) -> dict:
    native = original.channel_native or {}
    parent_id = native.get("message_id_header") or native.get("message_id") or original.external_id
    references = native.get("references") or []
    if isinstance(references, str):
        references = [references]
    if parent_id and parent_id not in references:
        references = [*references, parent_id]
    overrides: dict = {}
    if parent_id:
        overrides["in_reply_to"] = parent_id
    if references:
        overrides["references"] = references
    return overrides


def _store_outbound(
    *,
    repo: Repo,
    caller: Caller,
    agent_id: str,
    channel,
    outbound: OutboundMessage,
    result,
    native_overrides: dict | None = None,
) -> UnifiedMessage:
    from datetime import timezone

    to_address = outbound.to if isinstance(outbound.to, str) else outbound.to.get("address", "")
    now_tz = datetime.now(timezone.utc)
    channel_native = {"vendor_id": result.channel_native_id}
    if native_overrides:
        channel_native.update(native_overrides)
    stored = UnifiedMessage(
        message_id=new_id("msg"),
        agent_id=agent_id,
        org_id=caller.org_id,
        channel_id=channel.channel_id,
        channel=channel.channel,
        direction=MessageDirection.OUTBOUND,
        status=MessageStatus.SENT if result.status == "sent" else MessageStatus.FAILED,
        from_=Party(address=channel.config.get("address", "")),
        to=[Party(address=to_address)],
        body_text=outbound.body_text,
        body_html=outbound.body_html,
        subject=outbound.subject,
        thread_key=outbound.thread_key,
        is_dm=True,
        received_at=now_tz,
        channel_native=channel_native,
        external_id=result.channel_native_id or None,
    )
    repo.put_message(stored)
    return stored


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}
    qs = event.get("queryStringParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()
    agent_id = pp.get("agent_id")
    if not agent_id:
        return err("agent_id required", 400)

    # Tenant-isolation gate: caller may only act on agents in their own org.
    # Applies to every method/path below (GET inbox, GET one, POST send).
    if denied := require_agent(caller, agent_id, repo):
        return denied

    # GET /v1/agents/{id}/messages
    if method == "GET" and path.endswith("/messages"):
        since = None
        until = None
        if qs.get("since"):
            since = datetime.fromisoformat(qs["since"].replace("Z", "+00:00"))
        if qs.get("until"):
            until = datetime.fromisoformat(qs["until"].replace("Z", "+00:00"))
        channel_filter = None
        if qs.get("channels"):
            channel_filter = qs["channels"].split(",")
        limit = int(qs.get("limit", "50"))
        cursor = qs.get("cursor")
        msgs, next_cursor = repo.query_unified_inbox(
            agent_id=agent_id, since=since, until=until,
            channel_filter=channel_filter, limit=limit, cursor=cursor,
        )
        return ok({
            "messages": [_message_to_response(m) for m in msgs],
            "next_cursor": next_cursor,
        })

    # GET /v1/agents/{id}/messages/{msg_id}
    if method == "GET" and pp.get("message_id"):
        msg = _find_message(repo, agent_id=agent_id, message_id=pp["message_id"], qs=qs)
        if not msg:
            return err("message not found", 404)
        return ok(_message_to_response(msg))

    # POST /v1/agents/{id}/messages/{msg_id}/reply
    if method == "POST" and pp.get("message_id") and path.endswith("/reply"):
        original = _find_message(repo, agent_id=agent_id, message_id=pp["message_id"], qs=qs)
        if not original:
            return err("message not found", 404)

        body = parse_body(event)
        body_text = body.get("body_text") or body.get("body") or ""
        body_html = body.get("body_html")
        if not body_text and not body_html:
            return err("'body_text' is required", 400)

        channel = repo.get_channel(
            agent_id=agent_id,
            channel=original.channel.value,
            channel_id=original.channel_id,
        )
        if channel is None or channel.status != ChannelStatus.ACTIVE:
            return err(f"no active {original.channel.value} channel configured on agent {agent_id}", 409)

        native_overrides = _reply_native_overrides(original)
        native_overrides.update(body.get("channel_native_overrides") or {})
        thread_key = (
            body.get("thread_key")
            or original.thread_key
            or native_overrides.get("in_reply_to")
            or original.external_id
        )
        outbound = OutboundMessage(
            to=original.from_.address,
            body_text=body_text,
            body_html=body_html,
            subject=body.get("subject") or _reply_subject(original.subject),
            attachments=body.get("attachments") or [],
            thread_key=thread_key,
            channel_native_overrides=native_overrides,
        )

        entry = _registry().get(original.channel.value)
        if not entry:
            return err(f"no adapter for channel {original.channel.value}", 500)
        result = entry.adapter.send(channel=channel, message=outbound)
        stored = _store_outbound(
            repo=repo,
            caller=caller,
            agent_id=agent_id,
            channel=channel,
            outbound=outbound,
            result=result,
            native_overrides=native_overrides,
        )
        return ok({
            "message_id": stored.message_id,
            "status": stored.status.value,
            "channel_native_id": result.channel_native_id,
        }, status=201)

    # POST /v1/agents/{id}/messages/{msg_id}/read
    if method == "POST" and pp.get("message_id") and path.endswith("/read"):
        msg = _find_message(repo, agent_id=agent_id, message_id=pp["message_id"], qs=qs)
        if not msg:
            return err("message not found", 404)
        labels = list(msg.labels or [])
        if "read" not in labels:
            labels.append("read")
            repo.update_message_labels(
                agent_id=agent_id,
                received_at_ms=int(msg.received_at.timestamp() * 1000),
                message_id=msg.message_id,
                labels=labels,
            )
        return no_content()

    # DELETE /v1/agents/{id}/messages/{msg_id}
    if method == "DELETE" and pp.get("message_id"):
        msg = _find_message(repo, agent_id=agent_id, message_id=pp["message_id"], qs=qs)
        if not msg:
            return err("message not found", 404)
        repo.delete_message(
            agent_id=agent_id,
            received_at_ms=int(msg.received_at.timestamp() * 1000),
            message_id=msg.message_id,
        )
        return no_content()

    # POST /v1/agents/{id}/messages — send
    if method == "POST" and path.endswith("/messages"):
        body = parse_body(event)
        to = body.get("to")
        if not to:
            return err("'to' is required", 400)

        # Determine channel type
        channel_type = body.get("channel")
        if not channel_type:
            try:
                to_str = to if isinstance(to, str) else to.get("address", "")
                channel_type = infer_channel(to_str)
            except AmbiguousAddressError as e:
                return err(str(e), 400)

        # Resolve agent's channel instance of that type
        channel = _find_channel_for_send(
            repo=repo, agent_id=agent_id, channel_type=channel_type,
        )
        if channel is None:
            return err(f"no {channel_type} channel configured on agent {agent_id}", 409)

        # Build outbound message
        outbound = OutboundMessage(
            to=to,
            body_text=body.get("body_text") or body.get("body") or "",
            body_html=body.get("body_html"),
            subject=body.get("subject"),
            attachments=body.get("attachments") or [],
            thread_key=body.get("thread_key"),
        )

        # Resolve adapter + send
        entry = _registry().get(channel_type)
        if not entry:
            return err(f"no adapter for channel {channel_type}", 500)
        result = entry.adapter.send(channel=channel, message=outbound)

        stored = _store_outbound(
            repo=repo,
            caller=caller,
            agent_id=agent_id,
            channel=channel,
            outbound=outbound,
            result=result,
            native_overrides=outbound.channel_native_overrides,
        )
        return ok({
            "message_id": stored.message_id,
            "status": stored.status.value,
            "channel_native_id": result.channel_native_id,
        }, status=201)

    return err("not found", 404)
