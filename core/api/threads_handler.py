# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/threads_handler.py
"""
/v1/agents/{agent_id}/threads/* route handler.

Dispatches on METHOD + path pattern.  Handles:
  GET  /v1/agents/{id}/threads                  — list distinct thread_keys
  GET  /v1/agents/{id}/threads/{thread_id}      — all messages in thread (GSI5)
"""
from __future__ import annotations

from core.api._common import Caller, err, get_repo, ok, require_agent


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    pp = event.get("pathParameters") or {}
    qs = event.get("queryStringParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()

    agent_id = pp.get("agent_id")
    thread_id = pp.get("thread_id")

    if not agent_id:
        return err("agent_id required", 400)

    # Tenant-isolation gate: caller may only read threads on agents in their org.
    if denied := require_agent(caller, agent_id, repo):
        return denied

    # ── GET /v1/agents/{id}/threads ──────────────────────────────────
    if method == "GET" and not thread_id:
        # Walk all messages for this agent and collect distinct thread_keys.
        # We query the base table PK=AGT#{agent_id} SK begins_with MSG#. The
        # aggregation must see every message, so we follow LastEvaluatedKey to
        # completion rather than silently truncating at the first 1MB page.
        from boto3.dynamodb.conditions import Key
        seen: dict[str, dict] = {}
        last_key = None
        while True:
            kwargs: dict = {
                "KeyConditionExpression": Key("PK").eq(f"AGT#{agent_id}")
                    & Key("SK").begins_with("MSG#"),
                "ProjectionExpression": "thread_key, message_id, received_at, channel",
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            resp = repo.table.query(**kwargs)
            for item in resp.get("Items", []):
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
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        threads = sorted(seen.values(), key=lambda t: t["last_message_at"] or "", reverse=True)
        return ok({"threads": threads})

    # ── GET /v1/agents/{id}/threads/{thread_id} ─────────────────────
    if method == "GET" and thread_id:
        limit = int(qs.get("limit", "100"))
        # GSI5 is a global index; query_thread_messages scopes the thread to
        # this caller's agent server-side and never returns a raw index cursor,
        # so a foreign thread_key + own agent_id can neither read another org's
        # messages nor enumerate their identifiers via a pagination token.
        msgs = repo.query_thread_messages(thread_key=thread_id, agent_id=agent_id)[:limit]
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
        return ok({"thread_key": thread_id, "messages": result, "next_cursor": None})

    return err("not found", 404)
