# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/api/otp_handler.py
"""
POST /v1/agents/{agent_id}/extract-otp

Channel-agnostic OTP extraction from recent inbound messages.

Body params:
  - channel:      optional channel filter (e.g. "email", "sms")
  - from:         optional sender address substring filter
  - since:        optional ISO datetime — only look at messages after this time
  - max_age_sec:  max age of messages to scan (default 600 = 10 minutes)

Algorithm:
  1. Pull recent DMs via GSI3 (filtered per body params)
  2. For each message (newest first), run OTP regex: \\b\\d{4,8}\\b
  3. A candidate is accepted only if the message body ALSO contains at least one
     OTP keyword: "code", "otp", "verification", "verify", "pin" (case-insensitive)
  4. Return the first (most-recent) match as {code, message_id, received_at}
  5. If no match, return 404

Returns:
  200  { code, message_id, received_at }
  404  { error: "no OTP found" }
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from core.api._common import Caller, err, get_repo, ok, parse_body

_OTP_RE = re.compile(r"\b(\d{4,8})\b")
_KEYWORD_RE = re.compile(r"\b(code|otp|verification|verify|pin)\b", re.IGNORECASE)

_DEFAULT_MAX_AGE_SEC = 600


def _extract_otp(body_text: str) -> str | None:
    """Return the first OTP-looking digit run if an OTP keyword is present."""
    if not _KEYWORD_RE.search(body_text):
        return None
    m = _OTP_RE.search(body_text)
    return m.group(1) if m else None


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
    channel_filter = body.get("channel")
    channels_filter = body.get("channels") if isinstance(body.get("channels"), list) else None
    from_filter = body.get("from") or body.get("sender")
    max_age_sec = int(body.get("max_age_sec") or _DEFAULT_MAX_AGE_SEC)

    # Determine the `since` window
    if body.get("since"):
        since = datetime.fromisoformat(str(body["since"]).replace("Z", "+00:00"))
    else:
        since = datetime.now(timezone.utc) - timedelta(seconds=max_age_sec)

    # Pull matching messages from GSI3 (newest first)
    msgs = repo.list_unified_inbox(
        agent_id=agent_id,
        since=since,
        channel_filter=channels_filter or ([channel_filter] if channel_filter else None),
        limit=50,
    )

    for m in msgs:
        # Apply from filter
        if from_filter and from_filter.lower() not in m.from_.address.lower():
            continue
        code = _extract_otp(m.body_text or "")
        if code:
            return ok({
                "code": code,
                "message_id": m.message_id,
                "received_at": m.received_at.isoformat(),
            })

    return err("no OTP found", 404)
