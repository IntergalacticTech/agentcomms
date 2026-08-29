# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/wait_handler.py
"""
POST /v1/agents/{agent_id}/wait

Long-poll for next inbound message matching optional filters:
  - channel: channel type string (e.g. "email", "sms")
  - from:    sender address substring match
  - subject_contains: subject substring match (case-insensitive)
  - timeout_sec: max seconds to wait (default 25, max capped at 25)
  - poll_interval: seconds between polls (default 1, injectable for tests)

Returns the first matching message as JSON, or 408 if timeout expires.

Design note:  sleep/clock is injectable via module-level `_clock` dict so tests
can monkeypatch without touching the real `time` module.  Tests set
`poll_interval=0` and pre-seed messages to avoid any real sleeping.
"""
from __future__ import annotations

import time as _time_module
from datetime import datetime, timezone

from core.api._common import Caller, err, get_repo, ok, parse_body

# Injectable clock — tests may monkeypatch _clock["sleep"] and _clock["now"]
_clock = {
    "sleep": _time_module.sleep,
    "now": lambda: datetime.now(timezone.utc),
}

_MAX_TIMEOUT_SEC = 25
_DEFAULT_TIMEOUT_SEC = 25
_DEFAULT_POLL_INTERVAL = 1


def _message_to_response(m) -> dict:
    return {
        "message_id": m.message_id,
        "channel": m.channel.value,
        "direction": m.direction.value,
        "from": m.from_.model_dump(exclude_none=True),
        "subject": m.subject,
        "body_text": m.body_text,
        "received_at": m.received_at.isoformat(),
        "thread_key": m.thread_key,
    }


def handler(event: dict, context) -> dict:
    pp = event.get("pathParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()

    agent_id = pp.get("agent_id")
    if not agent_id:
        return err("agent_id required", 400)

    # Ownership check
    agent = repo.get_agent(org_id=caller.org_id, agent_id=agent_id)
    if not agent:
        return err("agent not found", 404)

    body = parse_body(event)
    timeout_sec = min(
        float(body.get("timeout_sec") or body.get("timeout") or _DEFAULT_TIMEOUT_SEC),
        _MAX_TIMEOUT_SEC,
    )
    poll_interval = float(body.get("poll_interval") or _DEFAULT_POLL_INTERVAL)
    channel_filter = body.get("channel")      # e.g. "email"
    channels_filter = body.get("channels") if isinstance(body.get("channels"), list) else None
    from_filter = body.get("from") or body.get("sender")  # sender address substring
    subject_filter = body.get("subject_contains")  # subject substring

    start = _clock["now"]()
    since = start  # Only look at messages that arrive after the poll begins

    while True:
        # Query GSI3 for DMs since `since`
        msgs = repo.list_unified_inbox(
            agent_id=agent_id,
            since=since,
            channel_filter=channels_filter or ([channel_filter] if channel_filter else None),
            limit=50,
        )
        # Apply remaining filters
        for m in msgs:
            if from_filter and from_filter.lower() not in m.from_.address.lower():
                continue
            if subject_filter and (not m.subject or subject_filter.lower() not in m.subject.lower()):
                continue
            return ok(_message_to_response(m))

        # Check timeout
        elapsed = (_clock["now"]() - start).total_seconds()
        if elapsed >= timeout_sec:
            return err("timeout waiting for message", 408)

        # Sleep before next poll
        _clock["sleep"](poll_interval)
        # Update cursor so we don't re-scan old messages
        since = _clock["now"]()
