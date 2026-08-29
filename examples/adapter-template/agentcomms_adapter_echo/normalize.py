# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

from __future__ import annotations

from typing import Any

from core.data.models import (
    ChannelType,
    MessageDirection,
    MessageStatus,
    Party,
    UnifiedMessage,
)
from core.data.ulid_ import new_id


def normalize_echo_event(
    *,
    body: dict[str, Any],
    agent_id: str,
    org_id: str,
    channel_id: str,
) -> UnifiedMessage | None:
    if body.get("type", "message") != "message":
        return None

    sender = str(body.get("from") or body.get("sender") or "")
    text = str(body.get("text") or body.get("body_text") or body.get("body") or "")
    if not sender or not text:
        return None

    recipients = body.get("to") or [f"echo:{agent_id}"]
    if isinstance(recipients, str):
        recipients = [recipients]

    external_id = str(body.get("id") or body.get("event_id") or new_id("evt", suffix="ec"))
    return UnifiedMessage(
        message_id=new_id("msg"),
        agent_id=agent_id,
        org_id=org_id,
        channel_id=channel_id,
        channel=ChannelType("echo"),
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(
            address=sender,
            display_name=body.get("from_name"),
            platform_user_id=body.get("from_id"),
        ),
        to=[Party(address=str(address)) for address in recipients],
        subject=body.get("subject"),
        body_text=text,
        thread_key=body.get("thread_key") or body.get("room") or sender,
        is_dm=bool(body.get("is_dm", True)),
        channel_native={
            "provider": "echo",
            "raw_type": body.get("type", "message"),
            "room": body.get("room"),
        },
        external_id=external_id,
    )
