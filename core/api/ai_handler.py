# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/api/ai_handler.py
"""AI feature routes for agents.

Routes (all require org or agent scope):

  POST /v1/agents/{agent_id}/ai/categorize  — classify a message
  POST /v1/agents/{agent_id}/ai/extract     — extract structured data
  POST /v1/agents/{agent_id}/ai/summarize   — summarize message or thread
  POST /v1/agents/{agent_id}/ai/search      — keyword search
"""
from __future__ import annotations

import logging
from datetime import datetime

from core.api._common import (
    Caller, err, get_repo, ok, parse_body, require_org_or_agent_scope,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Route implementations
# ---------------------------------------------------------------------------

def _handle_categorize(caller: Caller, agent_id: str, body: dict, repo) -> dict:
    """POST /v1/agents/{id}/ai/categorize

    Body: { message_id, labels?, complex? }
    """
    message_id = (body.get("message_id") or "").strip()
    if not message_id:
        return err("'message_id' is required")

    labels = body.get("labels") or ["inbox", "spam", "promotional", "notification", "uncategorized"]
    complex_ = bool(body.get("complex"))

    msg = repo.find_message_by_id(agent_id=agent_id, message_id=message_id)
    if not msg:
        return err("message not found", status=404)

    message_text = msg.body_text or ""
    if msg.subject:
        message_text = f"Subject: {msg.subject}\n\n{message_text}"

    from core.ai.categorize import categorize
    result = categorize(message_text, labels, complex=complex_)

    # Update the message's labels in DynamoDB
    ts_ms = int(msg.received_at.timestamp() * 1000)
    existing_labels = list(msg.channel_native.get("labels") or [])
    new_label = result["label"]
    if new_label not in existing_labels and new_label != "uncategorized":
        existing_labels = [new_label] + existing_labels
    repo.update_message_labels(
        agent_id=agent_id,
        received_at_ms=ts_ms,
        message_id=message_id,
        labels=existing_labels if new_label != "uncategorized" else existing_labels,
    )

    return ok({"label": result["label"], "confidence": result["confidence"]})


def _handle_extract(caller: Caller, agent_id: str, body: dict, repo) -> dict:
    """POST /v1/agents/{id}/ai/extract

    Body: { message_id, schema }
    """
    message_id = (body.get("message_id") or "").strip()
    if not message_id:
        return err("'message_id' is required")

    schema = body.get("schema")
    if not schema:
        return err("'schema' is required")

    msg = repo.find_message_by_id(agent_id=agent_id, message_id=message_id)
    if not msg:
        return err("message not found", status=404)

    message_text = msg.body_text or ""
    if msg.subject:
        message_text = f"Subject: {msg.subject}\n\n{message_text}"

    try:
        from core.ai.extract import extract
        data = extract(message_text, schema)
    except ValueError as exc:
        return err(str(exc), status=422)

    return ok({"data": data})


def _handle_summarize(caller: Caller, agent_id: str, body: dict, repo) -> dict:
    """POST /v1/agents/{id}/ai/summarize

    Body: { message_id?, thread_key?, length? }

    Either message_id or thread_key must be provided.
    """
    message_id = (body.get("message_id") or "").strip()
    thread_key = (body.get("thread_key") or "").strip()
    length = body.get("length", "short")
    if length not in ("short", "long"):
        length = "short"

    if not message_id and not thread_key:
        return err("'message_id' or 'thread_key' is required")

    if message_id:
        msg = repo.find_message_by_id(agent_id=agent_id, message_id=message_id)
        if not msg:
            return err("message not found", status=404)
        text = ""
        if msg.subject:
            text = f"Subject: {msg.subject}\n\n"
        text += msg.body_text or ""
    else:
        # Thread-level summary: concatenate all messages in thread
        msgs = repo.list_thread_messages(thread_key=thread_key)
        if not msgs:
            return err("thread not found or empty", status=404)
        parts = []
        for m in msgs:
            part = ""
            if m.subject:
                part = f"Subject: {m.subject}\n"
            part += m.body_text or ""
            if part.strip():
                parts.append(part)
        text = "\n\n---\n\n".join(parts)

    if not text.strip():
        return ok({"summary": ""})

    from core.ai.summarize import summarize
    summary = summarize(text, length=length)  # type: ignore[arg-type]
    return ok({"summary": summary})


def _handle_search(caller: Caller, agent_id: str, body: dict) -> dict:
    """POST /v1/agents/{id}/ai/search

    Body: { query, channel?, limit?, since? }
    """
    query = (body.get("query") or "").strip()
    if not query:
        return err("'query' is required")

    channel = body.get("channel") or None
    limit = int(body.get("limit") or 20)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    since: datetime | None = None
    if body.get("since"):
        try:
            since = datetime.fromisoformat(str(body["since"]).replace("Z", "+00:00"))
        except ValueError:
            return err("'since' must be an ISO 8601 datetime string")

    from core.ai.search import search
    results = search(
        org_id=caller.org_id,
        agent_id=agent_id,
        query=query,
        channel=channel,
        limit=limit,
        since=since,
    )
    return ok({"results": results, "count": len(results)})


# ---------------------------------------------------------------------------
# Lambda entry-point
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    caller = Caller.from_event(event)

    if denied := require_org_or_agent_scope(caller):
        return denied

    method = event.get("httpMethod", "")
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}

    agent_id = pp.get("agent_id", "")
    if not agent_id:
        return err("agent_id required", status=400)

    if method != "POST":
        return err("method not allowed", status=405)

    body = parse_body(event)
    repo = get_repo()

    if path.endswith("/categorize"):
        return _handle_categorize(caller, agent_id, body, repo)

    if path.endswith("/extract"):
        return _handle_extract(caller, agent_id, body, repo)

    if path.endswith("/summarize"):
        return _handle_summarize(caller, agent_id, body, repo)

    if path.endswith("/search"):
        return _handle_search(caller, agent_id, body)

    return err("not found", status=404)
