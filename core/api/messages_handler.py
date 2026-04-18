# core/api/messages_handler.py
"""
/v1/agents/{agent_id}/messages/* route handler.

Unified inbox (GET) and send (POST).
"""
from __future__ import annotations

from datetime import datetime

from core.api._common import Caller, err, get_repo, no_content, ok, parse_body
from core.adapters.registry import load_registry
from core.adapters.base import OutboundMessage
from core.data.models import (
    ChannelType, MessageDirection, MessageStatus, Party, UnifiedMessage,
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
        msgs = repo.list_unified_inbox(
            agent_id=agent_id, since=since, until=until,
            channel_filter=channel_filter, limit=limit,
        )
        return ok({"messages": [_message_to_response(m) for m in msgs]})

    # GET /v1/agents/{id}/messages/{msg_id}
    if method == "GET" and pp.get("message_id"):
        ts_ms = int(qs.get("received_at_ms", "0"))
        if not ts_ms:
            return err("received_at_ms query param required", 400)
        msg = repo.get_message(
            agent_id=agent_id, received_at_ms=ts_ms, message_id=pp["message_id"],
        )
        if not msg:
            return err("message not found", 404)
        return ok(_message_to_response(msg))

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

        # Persist outbound UnifiedMessage
        from datetime import timezone
        now_tz = datetime.now(timezone.utc)
        stored = UnifiedMessage(
            message_id=new_id("msg"),
            agent_id=agent_id,
            org_id=caller.org_id,
            channel_id=channel.channel_id,
            channel=ChannelType(channel_type),
            direction=MessageDirection.OUTBOUND,
            status=MessageStatus.SENT if result.status == "sent" else MessageStatus.FAILED,
            from_=Party(address=channel.config.get("address", "")),
            to=[Party(address=to if isinstance(to, str) else to.get("address", ""))],
            body_text=outbound.body_text,
            body_html=outbound.body_html,
            subject=outbound.subject,
            thread_key=outbound.thread_key,
            is_dm=True,
            received_at=now_tz,
            channel_native={"vendor_id": result.channel_native_id},
            external_id=result.channel_native_id or None,
        )
        repo.put_message(stored)
        return ok({
            "message_id": stored.message_id,
            "status": stored.status.value,
            "channel_native_id": result.channel_native_id,
        }, status=201)

    return err("not found", 404)
