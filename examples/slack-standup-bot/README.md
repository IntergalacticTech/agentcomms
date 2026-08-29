# Slack Standup Bot Example

A working Python agent that DMs each team member at 9 AM asking for their standup,
collects replies for an hour via AgentComms' unified message API, summarizes them with AI,
and posts the summary to a public Slack channel.

## What it does

1. **Waits until 09:00 local time** each day (simple sleep-to-next-9am loop).
2. **DMs each team member** via AgentComms' Slack channel API:
   `POST /agents/{agent_id}/slack/workspaces/{team}/users/{user_id}/messages`
3. **Collects replies** for 60 minutes by polling the unified message API every 2 minutes,
   filtering for `channels=slack` and direct messages.
4. **Summarizes** the concatenated replies using `POST /agents/{agent_id}/ai/summarize`.
5. **Posts the summary** to a public Slack channel:
   `POST /agents/{agent_id}/slack/workspaces/{team}/channels/{channel_id}/messages`

## Prerequisites

- Python 3.11+
- An AgentComms agent with a Slack workspace connected (see Slack App Setup below).
- `AGENTCOMMS_API_KEY` — your API key.
- `AGENTCOMMS_BASE_URL` — e.g. `https://api.agentcomms.dev/v1`.
- `STANDUP_AGENT_ID` — ID of the agent connected to your Slack workspace.
- `STANDUP_SLACK_TEAM` — your Slack workspace/team ID (e.g. `T012AB3CD`).
- `STANDUP_TEAM` — comma-separated Slack user IDs to DM (e.g. `U012AB3CD,U012AB3CE`).
- `STANDUP_POST_CHANNEL` — Slack channel ID to post the summary to (e.g. `C012AB3CF`).

## Slack App Setup

1. Create a new Slack app at https://api.slack.com/apps.
2. Add the following Bot Token Scopes under **OAuth & Permissions**:
   - `chat:write` — post messages to channels
   - `im:write` — open DM conversations
   - `channels:read` — list channels
   - `users:read` — look up user IDs
3. Install the app to your workspace and copy the **Bot User OAuth Token**.
4. In the AgentComms dashboard, go to your agent settings and connect the Slack
   workspace using the Bot Token. AgentComms will register the webhook and start
   routing Slack DMs to your agent's unified message stream.
5. Invite the bot to the summary channel: `/invite @YourBotName` in that channel.

## Quick start

```bash
cd examples/slack-standup-bot

pip install -e .

export AGENTCOMMS_API_KEY="ak_live_your_key"
export AGENTCOMMS_BASE_URL="https://api.agentcomms.dev/v1"
export STANDUP_AGENT_ID="agt_01HXYZ..."
export STANDUP_SLACK_TEAM="T012AB3CD"
export STANDUP_TEAM="U012AB3CD,U012AB3CE,U012AB3CF"
export STANDUP_POST_CHANNEL="C012AB3CG"

python standup_bot.py
```

The bot logs every step to stdout and sleeps until 9 AM. To test immediately,
set `STANDUP_RUN_NOW=1` to skip the sleep:

```bash
STANDUP_RUN_NOW=1 python standup_bot.py
```

## Running the tests (no API key needed)

```bash
pip install pytest
pytest standup_bot_test.py -v
```
