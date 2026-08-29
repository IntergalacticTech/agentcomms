# Quickstart

This guide assumes you already have an AgentComms API URL and API key. For a self-hosted deployment, run the CLI flow in [AGENT.md](../AGENT.md) first.

```bash
export AGENTCOMMS_BASE_URL=https://api.agentcomms.dev/v1
export AGENTCOMMS_API_KEY=ak_live_YOUR_KEY
```

## 1. Create an agent

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "InvoiceBot",
    "metadata": {"owner": "finance"}
  }'
```

Response:

```json
{
  "agent_id": "agt_...",
  "name": "InvoiceBot",
  "channels": []
}
```

## 2. Provision a channel

Email example:

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/agt_.../channels" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "email",
    "mode": "provision",
    "config": {
      "local_part": "invoice",
      "domain": "example.com"
    }
  }'
```

Telegram example:

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/agt_.../channels" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "telegram",
    "mode": "provision",
    "config": {
      "bot_token": "..."
    }
  }'
```

Slack is bridge-style: create a Slack app, put its credentials in the documented SSM paths, then create a channel with `mode: "bridge"`.

## 3. Send a message

The API infers the channel from the recipient when it can:

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/agt_.../messages" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "alice@example.com",
    "subject": "Status",
    "body": "Done."
  }'
```

For ambiguous destinations, include `"channel": "email"`, `"sms"`, `"slack"`, `"telegram"`, or another adapter channel.

## 4. Read the unified inbox

```bash
curl -sS "$AGENTCOMMS_BASE_URL/agents/agt_.../messages?channels=email,telegram&limit=25" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY"
```

Only direct messages and explicit mentions appear in this feed. Native room traffic stays on channel-native routes such as Slack workspace channels or Telegram chats.

## 5. Reply and mark read

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/agt_.../messages/msg_.../reply" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"body": "Got it, processing."}'
```

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/agt_.../messages/msg_.../read" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY"
```

## 6. Wait for a message or OTP

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/agt_.../wait" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "timeout_sec": 25,
    "from": "noreply@example.com",
    "subject_contains": "verification",
    "channels": ["email", "sms"]
  }'
```

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/agt_.../extract-otp" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "max_age_sec": 300,
    "from": "noreply@example.com",
    "channels": ["email", "sms"]
  }'
```

## 7. Use the SDK

Python:

```python
from agentcomms import Client

client = Client()
agent = client.agents("agt_...")

for msg in agent.messages.list(limit=25):
    agent.messages.reply(msg.message_id, body="Received.")
```

Node:

```typescript
import { Client } from "@agentcomms/client";

const client = new Client();
const agent = client.agents.agent("agt_...");
const messages = await agent.messages.list({ limit: 25 });
await agent.messages.reply(messages[0].message_id, { body: "Received." });
```

## 8. Use MCP

Install `@agentcomms/mcp`, configure `AGENTCOMMS_API_KEY`, and expose tools such as `agent_create`, `messages_list`, `message_send`, `message_reply`, `wait_for_message`, and `extract_otp` to your coding agent.

See [mcp-server.md](./mcp-server.md).
