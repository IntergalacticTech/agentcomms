# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

"""Org-scoped API key management routes.

Routes:
  GET    /v1/api-keys
  POST   /v1/api-keys
  DELETE /v1/api-keys/{key_id}

Plaintext API keys are returned only from POST. List/get responses never expose
key hashes.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from core.api._common import Caller, err, get_repo, no_content, ok, parse_body, require_org_scope
from core.data.models import ApiKey, ApiKeyScope
from core.data.ulid_ import new_id


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_plaintext_key() -> str:
    env = os.environ.get("AGENTCOMMS_ENV", "live").lower()
    prefix = "ak_test_" if env in {"test", "dev", "local"} else "ak_live_"
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    suffix = "".join(secrets.choice(alphabet) for _ in range(40))
    return f"{prefix}{suffix}"


def _key_prefix(raw: str) -> str:
    return raw[:12]


def _parse_expires_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    if not isinstance(raw, str):
        raise ValueError("'expires_at' must be an ISO 8601 datetime string")
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _response(key: ApiKey, *, plaintext: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "key_id": key.key_id,
        "name": key.name,
        "scope": key.scope.value,
        "org_id": key.org_id,
        "agent_id": key.agent_id,
        "channel_id": key.channel_id,
        "key_prefix": key.key_prefix,
        "revoked": key.revoked,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "created_at": key.created_at.isoformat(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }
    if plaintext is not None:
        body["key"] = plaintext
    return body


def _create(caller: Caller, body: dict, repo) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        return err("'name' is required")

    try:
        scope = ApiKeyScope(body.get("scope") or "agent")
    except ValueError:
        return err("'scope' must be one of: org, agent, channel")

    agent_id = body.get("agent_id")
    channel_id = body.get("channel_id")

    if scope in (ApiKeyScope.AGENT, ApiKeyScope.CHANNEL):
        if not agent_id:
            return err("'agent_id' is required for agent and channel scoped keys")
        if not repo.get_agent(org_id=caller.org_id, agent_id=agent_id):
            return err("agent not found", status=404)

    if scope == ApiKeyScope.CHANNEL:
        if not channel_id:
            return err("'channel_id' is required for channel scoped keys")
        channels = repo.list_channels(agent_id=agent_id)
        if not any(c.channel_id == channel_id for c in channels):
            return err("channel not found", status=404)

    try:
        expires_at = _parse_expires_at(body.get("expires_at"))
    except ValueError as exc:
        return err(str(exc))

    plaintext = _new_plaintext_key()
    now = datetime.now(timezone.utc)
    key = ApiKey(
        key_id=new_id("key"),
        key_hash=_hash(plaintext),
        key_prefix=_key_prefix(plaintext),
        org_id=caller.org_id,
        scope=scope,
        name=name,
        agent_id=agent_id if scope in (ApiKeyScope.AGENT, ApiKeyScope.CHANNEL) else None,
        channel_id=channel_id if scope == ApiKeyScope.CHANNEL else None,
        expires_at=expires_at,
        created_at=now,
    )
    repo.put_api_key(key)
    return ok(_response(key, plaintext=plaintext), status=201)


def handler(event: dict, context) -> dict:
    caller = Caller.from_event(event)
    if denied := require_org_scope(caller):
        return denied

    method = event.get("httpMethod", "")
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}
    key_id = pp.get("key_id") or pp.get("id")
    repo = get_repo()

    if method == "GET" and path.endswith("/api-keys") and not key_id:
        qs = event.get("queryStringParameters") or {}
        include_revoked = str(qs.get("include_revoked", "")).lower() in {"1", "true", "yes"}
        keys = repo.list_api_keys(org_id=caller.org_id, include_revoked=include_revoked)
        return ok({"api_keys": [_response(k) for k in keys]})

    if method == "POST" and path.endswith("/api-keys") and not key_id:
        return _create(caller, parse_body(event), repo)

    if method == "DELETE" and key_id:
        if caller.api_key_id == key_id:
            return err("refusing to revoke the API key used for this request", status=409)
        revoked = repo.revoke_api_key(org_id=caller.org_id, key_id=key_id)
        if not revoked:
            return err("API key not found", status=404)
        return no_content()

    return err("not found", status=404)
