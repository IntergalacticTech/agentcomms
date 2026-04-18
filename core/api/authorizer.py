# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/api/authorizer.py
"""
AgentComms authorizer.

Looks up an API key via GSI1, returns a caller context with scope enforcement.
Agent-scoped keys may only access paths containing their agent_id; channel-
scoped keys additionally restrict to their channel_id.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from boto3.dynamodb.conditions import Key

from core.data.models import ApiKey, ApiKeyScope
from core.data.repo import Repo


class DeniedError(Exception):
    pass


@dataclass
class CallerContext:
    org_id: str
    scope: str
    agent_id: str | None = None
    channel_id: str | None = None
    api_key_id: str | None = None


_AGENT_PATH_RE = re.compile(r"^/v1/agents/(?P<agent_id>agt_[A-Za-z0-9_]+)")
_CHANNEL_PATH_RE = re.compile(
    r"^/v1/agents/agt_[A-Za-z0-9_]+/channels/(?P<channel_id>chan_[A-Za-z0-9_]+)"
)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_by_hash(repo: Repo, key_hash: str) -> ApiKey | None:
    resp = repo.table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("gsi1_pk").eq(f"APIKEY#{key_hash}"),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return ApiKey.from_dynamodb_item(items[0])


def authorize(
    *, repo: Repo, raw_api_key: str,
    requested_path: str, requested_method: str,
) -> CallerContext:
    key = _load_by_hash(repo, _hash(raw_api_key))
    if key is None:
        raise DeniedError("invalid API key")

    ctx = CallerContext(
        org_id=key.org_id,
        scope=key.scope.value,
        agent_id=key.agent_id,
        channel_id=key.channel_id,
        api_key_id=key.key_id,
    )

    if key.scope == ApiKeyScope.ORG:
        return ctx  # full access within the org

    if key.scope == ApiKeyScope.AGENT:
        m = _AGENT_PATH_RE.match(requested_path)
        if not m or m.group("agent_id") != key.agent_id:
            raise DeniedError(
                f"agent-scoped key {key.key_id} denied for path {requested_path}"
            )
        return ctx

    if key.scope == ApiKeyScope.CHANNEL:
        m_agt = _AGENT_PATH_RE.match(requested_path)
        m_ch = _CHANNEL_PATH_RE.match(requested_path)
        if not m_agt or m_agt.group("agent_id") != key.agent_id:
            raise DeniedError("channel-scoped key denied (wrong agent)")
        if m_ch and m_ch.group("channel_id") != key.channel_id:
            raise DeniedError("channel-scoped key denied (wrong channel)")
        return ctx

    raise DeniedError(f"unknown scope: {key.scope}")
