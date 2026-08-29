# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/webhooks_handler.py
"""
/v1/agents/{agent_id}/webhooks/* route handler.

Dispatches on METHOD + path pattern.  Handles:
  POST    /v1/agents/{id}/webhooks               — create webhook subscription
  GET     /v1/agents/{id}/webhooks               — list all webhooks
  GET     /v1/agents/{id}/webhooks/{webhook_id}  — get single webhook
  PATCH   /v1/agents/{id}/webhooks/{webhook_id}  — update webhook
  DELETE  /v1/agents/{id}/webhooks/{webhook_id}  — delete webhook

Validation:
  - url must start with https://
  - events must be a subset of VALID_EVENTS
  - secret auto-generated as 32-byte hex if not provided by client
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from core.api._common import Caller, err, get_repo, no_content, ok, parse_body
from core.data.models import Webhook
from core.data.ulid_ import new_id


VALID_EVENTS = frozenset({
    "message.received",
    "message.sent",
    "message.delivered",
    "message.bounced",
    "message.failed",
    "channel.status_changed",
})


def _webhook_to_response(w: Webhook) -> dict:
    return {
        "webhook_id": w.webhook_id,
        "agent_id": w.agent_id,
        "url": w.url,
        "events": w.events,
        "channels": w.channels,
        "status": w.status,
        "created_at": w.created_at.isoformat(),
        # NOTE: secret is intentionally omitted from GET responses for security.
        # It is only returned at creation time.
    }


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    pp = event.get("pathParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()

    agent_id = pp.get("agent_id")
    webhook_id = pp.get("webhook_id")

    if not agent_id:
        return err("agent_id required", 400)

    # Ownership check
    agent = repo.get_agent(org_id=caller.org_id, agent_id=agent_id)
    if not agent:
        return err("agent not found", 404)

    # ── POST /v1/agents/{id}/webhooks ────────────────────────────────
    if method == "POST" and not webhook_id:
        body = parse_body(event)

        url = body.get("url", "")
        if not url.startswith("https://"):
            return err("url must start with https://", 400)

        events = body.get("events") or []
        unknown = set(events) - VALID_EVENTS
        if unknown:
            return err(f"unknown event names: {sorted(unknown)}", 400)

        # Auto-generate secret if not provided
        secret = body.get("secret") or secrets.token_hex(32)

        webhook = Webhook(
            webhook_id=new_id("whk"),
            agent_id=agent_id,
            org_id=caller.org_id,
            url=url,
            events=events,
            channels=body.get("channels") or ["*"],
            secret=secret,
            status="active",
        )
        repo.put_webhook(webhook)
        # Return secret at creation time only
        resp_body = _webhook_to_response(webhook)
        resp_body["secret"] = secret
        return ok(resp_body, status=201)

    # ── GET /v1/agents/{id}/webhooks ─────────────────────────────────
    if method == "GET" and not webhook_id:
        webhooks = repo.list_webhooks(agent_id=agent_id)
        return ok({"webhooks": [_webhook_to_response(w) for w in webhooks]})

    # ── GET /v1/agents/{id}/webhooks/{webhook_id} ────────────────────
    if method == "GET" and webhook_id:
        wh = repo.get_webhook(agent_id=agent_id, webhook_id=webhook_id)
        if not wh:
            return err("webhook not found", 404)
        return ok(_webhook_to_response(wh))

    # ── PATCH /v1/agents/{id}/webhooks/{webhook_id} ──────────────────
    if method == "PATCH" and webhook_id:
        wh = repo.get_webhook(agent_id=agent_id, webhook_id=webhook_id)
        if not wh:
            return err("webhook not found", 404)
        body = parse_body(event)
        updates: dict = {}
        if "url" in body:
            if not body["url"].startswith("https://"):
                return err("url must start with https://", 400)
            updates["url"] = body["url"]
        if "events" in body:
            unknown = set(body["events"]) - VALID_EVENTS
            if unknown:
                return err(f"unknown event names: {sorted(unknown)}", 400)
            updates["events"] = body["events"]
        if "channels" in body:
            updates["channels"] = body["channels"]
        if "status" in body:
            updates["status"] = body["status"]
        wh = wh.model_copy(update=updates)
        repo.put_webhook(wh)
        return ok(_webhook_to_response(wh))

    # ── DELETE /v1/agents/{id}/webhooks/{webhook_id} ─────────────────
    if method == "DELETE" and webhook_id:
        wh = repo.get_webhook(agent_id=agent_id, webhook_id=webhook_id)
        if not wh:
            return err("webhook not found", 404)
        repo.delete_webhook(agent_id=agent_id, webhook_id=webhook_id)
        return no_content()

    return err("not found", 404)
