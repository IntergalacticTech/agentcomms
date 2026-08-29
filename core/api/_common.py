# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/_common.py
"""Shared request/response helpers for hub API handlers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import boto3

from core.data.repo import Repo


def ok(body: Any, status: int = 200) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def err(message: str, status: int = 400) -> dict:
    return ok({"error": message}, status=status)


def no_content() -> dict:
    return {"statusCode": 204, "body": ""}


@dataclass
class Caller:
    org_id: str
    scope: str
    agent_id: str | None = None
    channel_id: str | None = None
    api_key_id: str | None = None

    @classmethod
    def from_event(cls, event: dict) -> Caller:
        a = event["requestContext"]["authorizer"]
        return cls(
            org_id=a["org_id"],
            scope=a["scope"],
            agent_id=a.get("agent_id"),
            channel_id=a.get("channel_id"),
            api_key_id=a.get("api_key_id"),
        )


def get_repo() -> Repo:
    region = os.environ.get("AWS_REGION", "us-east-1")
    table = boto3.resource("dynamodb", region_name=region).Table(
        os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    )
    return Repo(table)


def parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    return json.loads(raw) if isinstance(raw, str) else raw


def require_org_scope(caller: Caller) -> dict | None:
    """Return a 403 error response if *caller* does not have ``org`` scope.

    Returns ``None`` when the scope check passes so callers can do::

        if resp := require_org_scope(caller):
            return resp
    """
    if caller.scope != "org":
        return err("This resource requires an org-scoped API key.", status=403)
    return None


def require_org_or_agent_scope(caller: Caller) -> dict | None:
    """Return a 403 error response if *caller* has channel scope.

    Both ``org`` and ``agent`` scoped keys are allowed; channel-scoped keys
    are not. Returns ``None`` when the check passes so callers can do::

        if denied := require_org_or_agent_scope(caller):
            return denied
    """
    if caller.scope not in ("org", "agent"):
        return err("channel-scoped keys cannot access this endpoint", status=403)
    return None


def require_agent(caller: Caller, agent_id: str, repo: Repo) -> dict | None:
    """Tenant-isolation gate for per-agent routes.

    Returns the standard 404 error response when *agent_id* is not an agent in
    ``caller.org_id`` (either the agent does not exist or it belongs to another
    org). Returns ``None`` when the caller owns the agent, so handlers can do::

        if denied := require_agent(caller, agent_id, repo):
            return denied

    A 404 (rather than 403) is used deliberately so a caller cannot distinguish
    "agent exists in another org" from "agent does not exist" — this avoids a
    cross-tenant enumeration oracle.
    """
    agent = repo.get_agent(org_id=caller.org_id, agent_id=agent_id)
    if not agent:
        return err("agent not found", status=404)
    return None
