"""
standup_bot.py — AgentComms Slack standup bot example.

At 09:00 local time each day:
  1. DMs each member of STANDUP_TEAM asking for their standup.
  2. Polls the unified inbox every 2 minutes for 60 minutes collecting Slack DM replies.
  3. At 10:00, summarizes the replies with /ai/summarize.
  4. Posts the summary to STANDUP_POST_CHANNEL.

Required env vars:
  AGENTCOMMS_API_KEY     — API key (ac_live_...)
  AGENTCOMMS_BASE_URL    — e.g. https://api.agentcomms.dev/v1
  STANDUP_INBOX_ID       — inbox ID connected to your Slack workspace
  STANDUP_SLACK_TEAM     — Slack workspace/team ID (T...)
  STANDUP_TEAM           — comma-separated Slack user IDs to prompt
  STANDUP_POST_CHANNEL   — Slack channel ID for the summary post

Optional:
  STANDUP_RUN_NOW        — set to "1" to run immediately without sleeping to 9 AM
  COLLECTION_MINUTES     — minutes to collect replies (default 60)
  POLL_INTERVAL_SECONDS  — seconds between polls during collection (default 120)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("AGENTCOMMS_API_KEY", "")
BASE_URL = os.environ.get("AGENTCOMMS_BASE_URL", "https://api.agentcomms.dev/v1").rstrip("/")
INBOX_ID = os.environ.get("STANDUP_INBOX_ID", "")
SLACK_TEAM = os.environ.get("STANDUP_SLACK_TEAM", "")
STANDUP_TEAM_RAW = os.environ.get("STANDUP_TEAM", "")
POST_CHANNEL = os.environ.get("STANDUP_POST_CHANNEL", "")
RUN_NOW = os.environ.get("STANDUP_RUN_NOW", "0") == "1"
COLLECTION_MINUTES = int(os.environ.get("COLLECTION_MINUTES", "60"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "120"))

STANDUP_QUESTION = (
    "Good morning! Please share your standup:\n"
    "1. What did you do yesterday?\n"
    "2. What are you doing today?\n"
    "3. Any blockers?"
)

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def log(event: str, **kwargs) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}
    logger.info(json.dumps(record))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    return {"x-api-key": API_KEY, "Content-Type": "application/json"}


def _get(path: str, **params) -> dict:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict) -> dict:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    resp = requests.post(url, headers=_headers(), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def seconds_until_9am() -> float:
    """Return seconds until the next 09:00 local time."""
    now = datetime.now()
    target = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


# ---------------------------------------------------------------------------
# Core standup logic
# ---------------------------------------------------------------------------

def send_standup_prompts(team_members: list[str]) -> None:
    """DM each team member the standup question via Slack."""
    for user_id in team_members:
        try:
            _post(
                f"/inboxes/{INBOX_ID}/slack/workspaces/{SLACK_TEAM}"
                f"/channels/@{user_id}/messages",
                {"text": STANDUP_QUESTION},
            )
            log("prompt_sent", user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            log("prompt_error", user_id=user_id, error=str(exc))


def collect_replies(start_time: datetime, team_members: list[str]) -> dict[str, str]:
    """
    Poll the unified inbox every POLL_INTERVAL seconds for COLLECTION_MINUTES,
    collecting Slack DM replies from team members.

    Returns a dict of {user_id: reply_text}.
    """
    replies: dict[str, str] = {}
    deadline = start_time + timedelta(minutes=COLLECTION_MINUTES)
    last_check = start_time.isoformat()

    while datetime.now(timezone.utc) < deadline and len(replies) < len(team_members):
        time.sleep(POLL_INTERVAL)

        try:
            page = _get(
                f"/inboxes/{INBOX_ID}/messages",
                channel="slack",
                is_dm=True,
                order="asc",
                limit=100,
            )
            messages = page.get("data", [])
        except Exception as exc:  # noqa: BLE001
            log("collect_poll_error", error=str(exc))
            continue

        for msg in messages:
            if msg.get("received_at", msg.get("created_at", "")) <= last_check:
                continue
            if msg.get("direction") != "inbound":
                continue

            # Identify sender by Slack user ID stored in from_addr metadata
            from_addr = msg.get("from_addr", {})
            slack_user_id = from_addr.get("slack_user_id") or _extract_slack_user_id(from_addr)
            if slack_user_id not in team_members:
                continue
            if slack_user_id in replies:
                continue  # take first reply only

            body = msg.get("body_text") or msg.get("snippet", "")
            replies[slack_user_id] = body
            log("reply_received", user_id=slack_user_id, length=len(body))

        last_check = datetime.now(timezone.utc).isoformat()

    log("collection_complete", replies_received=len(replies),
        team_size=len(team_members))
    return replies


def _extract_slack_user_id(from_addr: dict) -> str | None:
    """
    Best-effort extraction of Slack user ID from from_addr.
    AgentComms stores Slack metadata in from_addr.address for DMs.
    Format: slack:T012AB3CD/U012AB3CE  or just the user ID.
    """
    address = from_addr.get("address", "")
    if address.startswith("slack:"):
        parts = address.split("/")
        if len(parts) >= 2:
            return parts[-1]
    if address.startswith("U") and len(address) == 9:
        return address
    return None


def summarize_replies(replies: dict[str, str]) -> str:
    """Concatenate replies into a single message and summarize via AI."""
    if not replies:
        return "No standup replies received today."

    # Build a synthetic combined message and send it as a temp inbox message
    # then summarize it. The simplest approach: post a combined message to our
    # own inbox and call /ai/summarize on it.
    combined_text = "\n\n".join(
        f"**{user_id}:** {text}" for user_id, text in replies.items()
    )

    # Create a synthetic message in our inbox to summarize
    sent = _post(f"/inboxes/{INBOX_ID}/messages", {
        "to": [{"address": "standup-summary@agentcomms.internal"}],
        "subject": f"Standup replies — {datetime.now().strftime('%Y-%m-%d')}",
        "body_text": combined_text,
    })
    message_id = sent["id"]
    log("summary_message_created", message_id=message_id)

    result = _post("/ai/summarize", {
        "inbox_id": INBOX_ID,
        "message_id": message_id,
    })
    summary = result.get("summary", combined_text)
    log("summarized", message_id=message_id, summary_length=len(summary))
    return summary


def post_summary_to_channel(summary: str, date_str: str) -> None:
    """Post the standup summary to the public Slack channel."""
    text = f":memo: *Team Standup — {date_str}*\n\n{summary}"
    _post(
        f"/inboxes/{INBOX_ID}/slack/workspaces/{SLACK_TEAM}"
        f"/channels/{POST_CHANNEL}/messages",
        {"text": text},
    )
    log("summary_posted", channel=POST_CHANNEL, length=len(text))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_sigterm(signum, frame) -> None:  # noqa: ARG001
    global _shutdown
    log("shutdown_requested")
    _shutdown = True


def validate_config() -> list[str]:
    """Return a list of missing required config items."""
    missing = []
    if not API_KEY:
        missing.append("AGENTCOMMS_API_KEY")
    if not INBOX_ID:
        missing.append("STANDUP_INBOX_ID")
    if not SLACK_TEAM:
        missing.append("STANDUP_SLACK_TEAM")
    if not STANDUP_TEAM_RAW:
        missing.append("STANDUP_TEAM")
    if not POST_CHANNEL:
        missing.append("STANDUP_POST_CHANNEL")
    return missing


def run_standup_cycle(team_members: list[str]) -> None:
    """Run one full standup cycle: prompt, collect, summarize, post."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    log("cycle_start", date=date_str, team_size=len(team_members))

    send_standup_prompts(team_members)
    start_time = datetime.now(timezone.utc)

    replies = collect_replies(start_time, team_members)

    summary = summarize_replies(replies)
    post_summary_to_channel(summary, date_str)

    log("cycle_complete", date=date_str, replies=len(replies))


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_sigterm)

    missing = validate_config()
    if missing:
        print(f"ERROR: Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    team_members = [uid.strip() for uid in STANDUP_TEAM_RAW.split(",") if uid.strip()]
    log("startup", team_members=team_members, post_channel=POST_CHANNEL,
        collection_minutes=COLLECTION_MINUTES, poll_interval=POLL_INTERVAL,
        run_now=RUN_NOW)

    while not _shutdown:
        if not RUN_NOW:
            sleep_secs = seconds_until_9am()
            log("sleeping_until_9am", seconds=int(sleep_secs))
            # Sleep in short chunks so SIGTERM is handled promptly
            deadline = time.monotonic() + sleep_secs
            while time.monotonic() < deadline and not _shutdown:
                time.sleep(min(30, deadline - time.monotonic()))
            if _shutdown:
                break

        try:
            run_standup_cycle(team_members)
        except KeyboardInterrupt:
            log("shutdown_requested", source="keyboard")
            break
        except Exception as exc:  # noqa: BLE001
            log("cycle_error", error=str(exc))

        if RUN_NOW:
            # In run-now mode, exit after one cycle
            break

        # Sleep briefly before calculating the next 9 AM target
        time.sleep(60)

    log("shutdown_complete")


if __name__ == "__main__":
    main()
