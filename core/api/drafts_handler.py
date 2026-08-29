# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/drafts_handler.py
"""
/v1/agents/{agent_id}/drafts/* route handler.

Dispatches on METHOD + path pattern.  Handles:
  POST    /v1/agents/{id}/drafts              — create draft
  GET     /v1/agents/{id}/drafts              — list all drafts for agent
  GET     /v1/agents/{id}/drafts/{draft_id}   — get single draft
  PATCH   /v1/agents/{id}/drafts/{draft_id}   — update draft
  DELETE  /v1/agents/{id}/drafts/{draft_id}   — delete draft
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.api._common import Caller, err, get_repo, no_content, ok, parse_body
from core.data.models import ChannelType, Draft, Party
from core.data.ulid_ import new_id


def _draft_to_response(d: Draft) -> dict:
    return {
        "draft_id": d.draft_id,
        "agent_id": d.agent_id,
        "channel": d.channel.value,
        "to": [p.model_dump(exclude_none=True) for p in d.to],
        "subject": d.subject,
        "body_text": d.body_text,
        "body_html": d.body_html,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()

    agent_id = pp.get("agent_id")
    draft_id = pp.get("draft_id")

    if not agent_id:
        return err("agent_id required", 400)

    # Ownership check
    agent = repo.get_agent(org_id=caller.org_id, agent_id=agent_id)
    if not agent:
        return err("agent not found", 404)

    # ── POST /v1/agents/{id}/drafts ──────────────────────────────────
    if method == "POST" and not draft_id:
        body = parse_body(event)
        channel_name = body.get("channel")
        if not channel_name:
            return err("channel is required", 400)
        try:
            channel_type = ChannelType(channel_name)
        except ValueError:
            return err(f"unknown channel: {channel_name}", 400)

        to_raw = body.get("to") or []
        if isinstance(to_raw, str):
            to_raw = [{"address": to_raw}]
        to_parties = [Party(**p) if isinstance(p, dict) else Party(address=p) for p in to_raw]

        draft = Draft(
            draft_id=new_id("drf"),
            agent_id=agent_id,
            org_id=caller.org_id,
            channel=channel_type,
            to=to_parties,
            subject=body.get("subject"),
            body_text=body.get("body_text") or "",
            body_html=body.get("body_html"),
        )
        repo.put_draft(draft)
        return ok(_draft_to_response(draft), status=201)

    # ── GET /v1/agents/{id}/drafts ───────────────────────────────────
    if method == "GET" and not draft_id:
        drafts = repo.list_drafts(agent_id=agent_id)
        return ok({"drafts": [_draft_to_response(d) for d in drafts]})

    # ── GET /v1/agents/{id}/drafts/{draft_id} ───────────────────────
    if method == "GET" and draft_id:
        # draft_id doesn't encode channel, so scan the list
        drafts = repo.list_drafts(agent_id=agent_id)
        draft = next((d for d in drafts if d.draft_id == draft_id), None)
        if not draft:
            return err("draft not found", 404)
        return ok(_draft_to_response(draft))

    # ── PATCH /v1/agents/{id}/drafts/{draft_id} ─────────────────────
    if method == "PATCH" and draft_id:
        drafts = repo.list_drafts(agent_id=agent_id)
        draft = next((d for d in drafts if d.draft_id == draft_id), None)
        if not draft:
            return err("draft not found", 404)

        body = parse_body(event)
        updates: dict = {}
        if "body_text" in body:
            updates["body_text"] = body["body_text"]
        if "body_html" in body:
            updates["body_html"] = body["body_html"]
        if "subject" in body:
            updates["subject"] = body["subject"]
        if "to" in body:
            to_raw = body["to"]
            if isinstance(to_raw, str):
                to_raw = [{"address": to_raw}]
            updates["to"] = [Party(**p) if isinstance(p, dict) else Party(address=p) for p in to_raw]
        updates["updated_at"] = datetime.now(timezone.utc)

        draft = draft.model_copy(update=updates)
        # Delete old and re-put (SK encodes channel)
        repo.delete_draft(
            agent_id=agent_id,
            channel=draft.channel.value,
            draft_id=draft_id,
        )
        repo.put_draft(draft)
        return ok(_draft_to_response(draft))

    # ── DELETE /v1/agents/{id}/drafts/{draft_id} ────────────────────
    if method == "DELETE" and draft_id:
        drafts = repo.list_drafts(agent_id=agent_id)
        draft = next((d for d in drafts if d.draft_id == draft_id), None)
        if not draft:
            return err("draft not found", 404)
        repo.delete_draft(
            agent_id=agent_id,
            channel=draft.channel.value,
            draft_id=draft_id,
        )
        return no_content()

    return err("not found", 404)
