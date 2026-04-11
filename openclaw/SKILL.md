---
name: freemail
description: |
  Email for AI agents. Create inboxes, send/receive email, wait for messages,
  and extract OTP codes via the FreeMail API. No OAuth, no human provisioning.
  One API call to sign up, one to create an inbox, one to send email.
metadata:
  openclaw:
    requires:
      env:
        - FREEMAIL_API_KEY
    primaryEnv: FREEMAIL_API_KEY
---

# FreeMail - Email for AI Agents

API-first email platform. Create inboxes, send and receive email, wait for
messages, and extract verification codes. Purpose-built for autonomous AI
agent workflows.

Base URL: `https://api.victorymail.dev/v1`

## Self-Signup (No Human Required)

An agent can create its own account and API key in a single call:

```bash
curl -X POST https://api.victorymail.dev/v1/console/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "agent@example.com", "password": "SecurePass123!", "name": "My Agent"}'
```

Response includes `api_key` which works immediately -- no email verification
needed for API access. Save the key; it is shown only once.

## Authentication

All API calls require the `x-api-key` header:

```
x-api-key: am_live_your_key_here
```

## Core Workflow

### 1. Create an inbox

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: $FREEMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "My Agent"}'
```

Returns `id` and `email` (e.g. `x7k9m2@victorymail.dev`). Use this email
address to send and receive mail.

### 2. Send email

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

### 3. Wait for a reply

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/{inbox_id}/wait \
  -H "x-api-key: $FREEMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"timeout": 25, "filter": {"from": "user@example.com"}}'
```

Long-polls up to 25 seconds. Returns the full message when one arrives.

### 4. Extract OTP / verification code

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/{inbox_id}/extract-otp \
  -H "x-api-key: $FREEMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"timeout": 25, "sender": "noreply@example.com"}'
```

Waits for a matching email and extracts the numeric verification code
automatically. Returns `{"code": "482917", ...}`.

## All Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /console/signup | Create account + get API key |
| GET | /organizations/me | Get account info |
| POST | /inboxes | Create inbox |
| GET | /inboxes | List inboxes |
| GET | /inboxes/{id} | Get inbox |
| DELETE | /inboxes/{id} | Delete inbox |
| POST | /inboxes/{id}/messages | Send email |
| GET | /inboxes/{id}/messages | List messages |
| GET | /inboxes/{id}/messages/{mid} | Get message with body |
| POST | /inboxes/{id}/messages/{mid}/reply | Reply to message |
| POST | /inboxes/{id}/messages/{mid}/forward | Forward message |
| POST | /inboxes/{id}/wait | Wait for matching email |
| POST | /inboxes/{id}/extract-otp | Wait + extract OTP code |
| GET | /inboxes/{id}/threads | List threads |
| POST | /inboxes/{id}/drafts | Create draft |
| POST | /domains | Add custom domain |
| POST | /webhooks | Create webhook |
| POST | /search | Search messages |
| POST | /api-keys | Create additional API key |

## Common Agent Scenarios

### Sign up for a service and verify email

1. Create inbox: `POST /inboxes`
2. Use the inbox email to register on the target service
3. Extract OTP: `POST /inboxes/{id}/extract-otp` with `sender` filter
4. Submit the OTP code to the target service

### Send outbound emails

1. Create inbox: `POST /inboxes`
2. Send email: `POST /inboxes/{id}/messages`
3. Check delivery: `GET /inboxes/{id}/messages/{mid}` (status field)

### Monitor for incoming emails

1. Create inbox or use existing
2. Poll: `POST /inboxes/{id}/wait` with filters
3. Process the returned message

## MCP Server

For AI frameworks that support MCP (Model Context Protocol), clone the
repo and run the MCP server:

```bash
git clone https://github.com/IntergalacticTech/FreeMail.ai.git
cd FreeMail.ai/mcp-server && npm install && npm run build
```

Add to your MCP config:

```json
{
  "mcpServers": {
    "freemail": {
      "command": "node",
      "args": ["/path/to/FreeMail.ai/mcp-server/dist/index.js"],
      "env": {
        "FREEMAIL_API_KEY": "am_live_your_key_here"
      }
    }
  }
}
```

10 tools available: create_inbox, list_inboxes, send_email, list_messages,
get_message, reply_to_message, wait_for_email, extract_otp, delete_inbox,
get_organization.

## Trigger Words

- email
- inbox
- send email
- receive email
- OTP
- verification code
- FreeMail
- email inbox
- sign up for service
- verify email

## Links

- GitHub: https://github.com/IntergalacticTech/FreeMail.ai
- Console: https://console.victorymail.dev
- API: https://api.victorymail.dev/v1
