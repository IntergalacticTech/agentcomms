# core/api/threads_handler.py
"""
/v1/agents/{agent_id}/threads/* route handler.

Dispatches on METHOD + path pattern.  Handles:
  GET  /v1/agents/{id}/threads                  — list distinct thread_keys
  GET  /v1/agents/{id}/threads/{thread_id}      — all messages in thread (GSI5)
"""
from __future__ import annotations

from core.api._common import Caller, err, get_repo, ok


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    pp = event.get("pathParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()

    agent_id = pp.get("agent_id")
    thread_id = pp.get("thread_id")

    if not agent_id:
        return err("agent_id required", 400)

    # Ownership check
    agent = repo.get_agent(org_id=caller.org_id, agent_id=agent_id)
    if not agent:
        return err("agent not found", 404)

    # ── GET /v1/agents/{id}/threads ──────────────────────────────────
    if method == "GET" and not thread_id:
        # Walk all messages for this agent and collect distinct thread_keys.
        # We query the base table PK=AGT#{agent_id} SK begins_with MSG#.
        # A full scan of agent messages is acceptable here because Phase 1
        # doesn't target massive message volumes; pagination can be added later.
        from boto3.dynamodb.conditions import Key
        resp = repo.table.query(
            KeyConditionExpression=Key("PK").eq(f"AGT#{agent_id}")
                & Key("SK").begins_with("MSG#"),
            ProjectionExpression="thread_key, message_id, received_at, channel",
        )
        items = resp.get("Items", [])
        # Collect distinct thread_keys with summary metadata
        seen: dict[str, dict] = {}
        for item in items:
            tk = item.get("thread_key")
            if not tk:
                continue
            if tk not in seen:
                seen[tk] = {
                    "thread_key": tk,
                    "channel": item.get("channel"),
                    "last_message_at": item.get("received_at"),
                    "message_count": 1,
                }
            else:
                seen[tk]["message_count"] += 1
                # Keep the most recent received_at
                if (item.get("received_at") or "") > (seen[tk]["last_message_at"] or ""):
                    seen[tk]["last_message_at"] = item.get("received_at")
        threads = sorted(seen.values(), key=lambda t: t["last_message_at"] or "", reverse=True)
        return ok({"threads": threads})

    # ── GET /v1/agents/{id}/threads/{thread_id} ─────────────────────
    if method == "GET" and thread_id:
        msgs = repo.list_thread_messages(thread_key=thread_id)
        if not msgs:
            return err("thread not found", 404)
        result = []
        for m in msgs:
            result.append({
                "message_id": m.message_id,
                "channel": m.channel.value,
                "direction": m.direction.value,
                "from": m.from_.model_dump(exclude_none=True),
                "subject": m.subject,
                "body_text": m.body_text,
                "received_at": m.received_at.isoformat(),
                "thread_key": m.thread_key,
            })
        return ok({"thread_key": thread_id, "messages": result})

    return err("not found", 404)
