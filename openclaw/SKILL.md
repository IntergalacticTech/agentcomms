---
name: agentcomms
description: |
  Communications hub for AI agents. Create agents, provision channels, send and
  receive messages, wait for replies, extract OTP codes, and use native channel
  surfaces through the AgentComms API.
metadata:
  openclaw:
    requires:
      env:
        - AGENTCOMMS_API_KEY
    primaryEnv: AGENTCOMMS_API_KEY
---

# AgentComms - Communications Hub for AI Agents

AgentComms gives AI agents durable identities across email, SMS, Slack, Telegram, push, and adapter channels. Direct messages and explicit mentions land in one unified inbox.

Base URL: `https://api.agentcomms.dev/v1`

## Authentication

Use either header:

```text
Authorization: Bearer ak_live_your_key_here
```

```text
x-api-key: ak_live_your_key_here
```

## Core Workflow

### 1. Create an agent

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "TaskAgent"}'
```

### 2. Provision a channel

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/channels" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "email",
    "mode": "provision",
    "config": {"local_part": "task-agent", "domain": "example.com"}
  }'
```

### 3. Send a message

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/messages" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "user@example.com",
    "subject": "Hello",
    "body": "Sent by an AI agent via AgentComms"
  }'
```

### 4. Wait for a reply

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/wait" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"timeout_sec": 25, "from": "user@example.com"}'
```

### 5. Extract OTP / verification code

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/extract-otp" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"max_age_sec": 300, "from": "noreply@example.com"}'
```

## Main Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/agents` | Create an agent |
| `GET` | `/agents` | List agents |
| `POST` | `/agents/{agent_id}/channels` | Provision or bridge a channel |
| `GET` | `/agents/{agent_id}/messages` | List unified inbox messages |
| `POST` | `/agents/{agent_id}/messages` | Send a message |
| `POST` | `/agents/{agent_id}/messages/{message_id}/reply` | Reply to a message |
| `POST` | `/agents/{agent_id}/wait` | Wait for a matching message |
| `POST` | `/agents/{agent_id}/extract-otp` | Wait and extract OTP |
| `POST` | `/api-keys` | Create a scoped API key |
| `GET` | `/vault` | List vault items |

## Guidance for Agents

- Prefer `message_reply`/reply routes for existing conversations so provider threading is preserved.
- Treat IDs and cursors as opaque.
- Never log API keys, vault secrets, TOTP seeds, or webhook signing secrets.
- Use native routes for room/channel context instead of forcing all provider traffic into the unified inbox.
