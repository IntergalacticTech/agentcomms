# AgentComms Agent Instructions

These instructions are for coding agents that need to communicate through AgentComms. Humans should start with [quickstart.md](./quickstart.md) or [AGENT.md](../AGENT.md).

## Environment

```bash
export AGENTCOMMS_BASE_URL=https://api.agentcomms.dev/v1
export AGENTCOMMS_API_KEY=ak_live_YOUR_KEY
```

## Create an Agent

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "TaskAgent"}'
```

Save `agent_id`.

## Provision a Channel

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

Use the same route for other channel types. Adapter-specific setup may require provider credentials to be present in SSM first.

## Send

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/messages" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "recipient@example.com",
    "subject": "Hello",
    "body": "Message body here"
  }'
```

## Read

```bash
curl -sS "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/messages?limit=25" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY"
```

## Wait and Extract OTP

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/wait" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"timeout_sec": 25, "from": "noreply@example.com"}'
```

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/extract-otp" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"max_age_sec": 300, "from": "noreply@example.com"}'
```

## Reply

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/messages/$MESSAGE_ID/reply" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"body": "Got it, processing."}'
```

## SDK Shortcut

```python
from agentcomms import Client

client = Client()
agent = client.agents("agt_...")

msg = agent.messages.wait(timeout=25, sender="noreply@example.com")
otp = agent.messages.extract_otp(timeout=300, sender="noreply@example.com")
agent.messages.reply(msg.message_id, body="Received.")
```

## Rules for Agents

- Treat `message_id`, `agent_id`, `channel_id`, and cursors as opaque strings.
- Do not scrape native provider state when AgentComms exposes a native route for that channel.
- Prefer `reply` when responding to an existing message so channel-native threading is preserved.
- Do not log plaintext API keys, webhook secrets, or vault values.
- Use webhooks or the event stream for long-running production workflows instead of infinite polling.
