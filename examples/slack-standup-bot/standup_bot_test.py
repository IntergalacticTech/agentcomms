"""
Offline unit tests for standup_bot.py.
All HTTP calls are mocked — no real API key or Slack workspace required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

import standup_bot as bot


TEAM = ["U001", "U002", "U003"]
AGENT_ID = "agt_standup"
SLACK_TEAM = "T012AB3CD"
POST_CHANNEL = "C012AB3CG"


# ---------------------------------------------------------------------------
# Test 1 — prompts are sent to every team member
# ---------------------------------------------------------------------------

def test_prompts_sent_to_all_members():
    """send_standup_prompts calls POST for each team member."""
    with patch.object(bot, "_post") as mock_post, \
         patch.object(bot, "AGENT_ID", AGENT_ID), \
         patch.object(bot, "SLACK_TEAM", SLACK_TEAM):

        mock_post.return_value = {"id": "msg-ok"}
        bot.send_standup_prompts(TEAM)

    assert mock_post.call_count == len(TEAM), (
        f"Expected {len(TEAM)} POST calls, got {mock_post.call_count}"
    )

    for user_id in TEAM:
        expected_path = (
            f"/agents/{AGENT_ID}/slack/workspaces/{SLACK_TEAM}"
            f"/users/{user_id}/messages"
        )
        matching = [
            c for c in mock_post.call_args_list
            if c.args[0] == expected_path
        ]
        assert len(matching) == 1, f"No POST call found for user {user_id}"
        assert "standup" in matching[0].args[1]["text"].lower() or \
               "yesterday" in matching[0].args[1]["text"].lower(), \
               "Standup question should mention yesterday"


# ---------------------------------------------------------------------------
# Test 2 — replies collected and summary is composed
# ---------------------------------------------------------------------------

def test_summary_composed_from_replies():
    """summarize_replies sends raw text to /ai/summarize."""
    replies = {
        "U001": "Yesterday: deployed feature X. Today: fixing bug Y. No blockers.",
        "U002": "Yesterday: code review. Today: writing tests. Blocker: waiting on design.",
    }

    with patch.object(bot, "_post") as mock_post, \
         patch.object(bot, "AGENT_ID", AGENT_ID):

        mock_post.return_value = {
            "summary": "The team deployed feature X and is working on bug Y and tests.",
        }

        summary = bot.summarize_replies(replies)

    assert summary == "The team deployed feature X and is working on bug Y and tests."

    summarize_call = mock_post.call_args_list[0]
    assert summarize_call.args[0] == f"/agents/{AGENT_ID}/ai/summarize"
    assert summarize_call.args[1]["length"] == "short"
    combined_body = summarize_call.args[1]["text"]
    assert "U001" in combined_body
    assert "U002" in combined_body
    assert "feature X" in combined_body


# ---------------------------------------------------------------------------
# Test 3 — summary is posted to the public channel
# ---------------------------------------------------------------------------

def test_summary_posted_to_channel():
    """post_summary_to_channel calls POST on the correct channel endpoint."""
    with patch.object(bot, "_post") as mock_post, \
         patch.object(bot, "AGENT_ID", AGENT_ID), \
         patch.object(bot, "SLACK_TEAM", SLACK_TEAM), \
         patch.object(bot, "POST_CHANNEL", POST_CHANNEL):

        mock_post.return_value = {"id": "msg-summary"}
        bot.post_summary_to_channel("Team is working well today.", "2026-04-17")

    assert mock_post.call_count == 1
    call_path = mock_post.call_args.args[0]
    call_body = mock_post.call_args.args[1]

    expected_path = (
        f"/agents/{AGENT_ID}/slack/workspaces/{SLACK_TEAM}"
        f"/channels/{POST_CHANNEL}/messages"
    )
    assert call_path == expected_path, f"Expected {expected_path!r}, got {call_path!r}"
    assert "Team is working well" in call_body["text"]
    assert "2026-04-17" in call_body["text"]


# ---------------------------------------------------------------------------
# Test 4 — empty replies produce a graceful fallback (no AI call)
# ---------------------------------------------------------------------------

def test_no_replies_fallback():
    """When no replies are collected, summarize_replies returns a fallback string."""
    with patch.object(bot, "_post") as mock_post:
        summary = bot.summarize_replies({})

    mock_post.assert_not_called()
    assert "no standup" in summary.lower() or "no" in summary.lower()


# ---------------------------------------------------------------------------
# Test 5 — validate_config catches missing env vars
# ---------------------------------------------------------------------------

def test_validate_config_missing_vars():
    """validate_config returns a list of all missing required env var names."""
    with patch.object(bot, "API_KEY", ""), \
         patch.object(bot, "AGENT_ID", ""), \
         patch.object(bot, "SLACK_TEAM", ""), \
         patch.object(bot, "STANDUP_TEAM_RAW", ""), \
         patch.object(bot, "POST_CHANNEL", ""):

        missing = bot.validate_config()

    assert "AGENTCOMMS_API_KEY" in missing
    assert "STANDUP_AGENT_ID" in missing
    assert "STANDUP_SLACK_TEAM" in missing
    assert "STANDUP_TEAM" in missing
    assert "STANDUP_POST_CHANNEL" in missing
