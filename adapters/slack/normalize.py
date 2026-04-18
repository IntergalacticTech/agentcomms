# adapters/slack/normalize.py
"""
Parse Slack Events API payloads into UnifiedMessage.

DM inference rules:
  - event.channel starts with "D" (DM channel type) → is_dm=True
  - event.type == "app_mention" → is_dm=True (agent was @mentioned)
  - Otherwise → is_dm=False (channel noise; accessible via native sub-surface)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.data.models import (
    ChannelType, MessageDirection, MessageStatus, Party, UnifiedMessage,
)
from core.data.ulid_ import new_id


def parse_slack_event(
    payload: dict[str, Any],
    *,
    channel_id: str,
    agent_id: str,
    org_id: str,
    bot_user_id: str,
) -> UnifiedMessage | None:
    """Convert a Slack event_callback payload to UnifiedMessage.

    Returns None if the event should be ignored (e.g., bot's own messages,
    message_changed subtypes, etc.).
    """
    event = payload.get("event", {})
    team_id = payload.get("team_id", "")
    event_type = event.get("type", "")

    # Ignore bot messages (to avoid echo loops)
    if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
        return None

    # Only handle message and app_mention events
    if event_type not in ("message", "app_mention"):
        return None

    # The sender's user ID
    user_id = event.get("user", "")
    channel_slack_id = event.get("channel", "")
    ts = event.get("ts", "")
    thread_ts = event.get("thread_ts")
    text = event.get("text", "")
    blocks = event.get("blocks", [])

    # DM inference
    is_dm = (
        channel_slack_id.startswith("D")  # Slack DM channel IDs start with D
        or event_type == "app_mention"
    )
    is_mention = event_type == "app_mention"

    # Parse timestamp
    try:
        ts_float = float(ts)
        received_at = datetime.fromtimestamp(ts_float, tz=timezone.utc)
    except (ValueError, TypeError):
        received_at = datetime.now(timezone.utc)

    external_id = f"{team_id}:{ts}"

    return UnifiedMessage(
        message_id=new_id("msg"),
        agent_id=agent_id,
        org_id=org_id,
        channel_id=channel_id,
        channel=ChannelType.SLACK,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        **{"from": Party(
            address=f"slack:{team_id}:{user_id}",
            platform_user_id=user_id,
        )},
        to=[Party(address=f"slack:{team_id}:{bot_user_id}")],
        subject=None,
        body_text=text,
        is_dm=is_dm,
        received_at=received_at,
        channel_native={
            "team_id": team_id,
            "channel_id": channel_slack_id,
            "ts": ts,
            "thread_ts": thread_ts,
            "is_mention": is_mention,
            "blocks": blocks,
            "event_type": event_type,
        },
        external_id=external_id,
    )
