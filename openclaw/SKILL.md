---
name: freemail
description: |
  Email for AI agents. Create inboxes, send/receive email, wait for messages,
  and extract OTP codes via the FreeMail API. Supports MCP server integration
  for direct tool access.
metadata:
  openclaw:
    requires:
      env:
        - FREEMAIL_API_KEY
      bins:
        - node
    primaryEnv: FREEMAIL_API_KEY
---

# FreeMail - Email for AI Agents

Create email inboxes, send and receive email, wait for incoming messages, and
extract verification codes -- all via API. Built for AI agent workflows.

## Setup

### Option 1: MCP Server (Recommended)

Add to your `openclaw.json` or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "freemail": {
      "command": "npx",
      "args": ["-y", "@freemail/mcp-server"],
      "env": {
        "FREEMAIL_API_KEY": "am_live_your_key_here"
      }
    }
  }
}
```

### Option 2: Direct API

Set your API key:
```bash
export FREEMAIL_API_KEY="am_live_your_key_here"
```

## Getting an API Key

1. Sign up at https://console.victorymail.dev
2. Or via API:
```bash
curl -X POST https://api.victorymail.dev/v1/agent/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com"}'
```
3. Verify your email, then your API key is returned

## Available Tools (MCP)

| Tool | Description |
|------|-------------|
| create_inbox | Create a new email inbox |
| list_inboxes | List all inboxes |
| send_email | Send an email from an inbox |
| list_messages | List messages in an inbox |
| get_message | Get a message with full body |
| reply_to_message | Reply to a message |
| wait_for_email | Wait for a matching email (long poll) |
| extract_otp | Wait for email and extract verification code |
| delete_inbox | Delete an inbox |
| get_organization | Get account info |

## Common Workflows

### Create inbox and send email

"Create a new inbox called 'signup-agent' and send a welcome email to user@example.com"

### Wait for verification email

"Create an inbox, sign up for the service at example.com using that email, then wait for the verification email and extract the OTP code"

### Monitor inbox

"Check my inbox inbox_id for new messages from noreply@service.com"

## Direct API Usage

Base URL: `https://api.victorymail.dev/v1`
Auth header: `x-api-key: {FREEMAIL_API_KEY}`

### Create inbox
```bash
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: $FREEMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "My Agent"}'
```

### Send email
```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/{inbox_id}/messages \
  -H "x-api-key: $FREEMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": [{"address": "user@example.com"}],
    "subject": "Hello",
    "body_text": "Sent by an AI agent via FreeMail"
  }'
```

### Wait for email
```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/{inbox_id}/wait \
  -H "x-api-key: $FREEMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"timeout": 25, "filter": {"from": "noreply@example.com"}}'
```

### Extract OTP
```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/{inbox_id}/extract-otp \
  -H "x-api-key: $FREEMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"timeout": 25, "sender": "noreply@example.com"}'
```

## Trigger Words

- email
- inbox
- send email
- receive email
- check email
- OTP
- verification code
- mail
- FreeMail
- send message
- email inbox

## Links

- Documentation: https://docs.victorymail.dev
- Console: https://console.victorymail.dev
- API Reference: https://api.victorymail.dev/v1
- GitHub: https://github.com/IntergalacticTech/FreeMail.ai
- Python SDK: `pip install git+https://github.com/IntergalacticTech/FreeMail.ai.git#subdirectory=sdks/python`
- Node.js SDK: `npm install IntergalacticTech/FreeMail.ai#main --install-strategy=shallow`
