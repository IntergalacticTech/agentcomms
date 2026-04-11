# Quickstart Guide

This guide walks you through signing up, creating your first inbox, sending an email, and extracting an OTP -- all in under 5 minutes.

## Prerequisites

- An email address to sign up with
- `curl` (or any HTTP client)
- Optionally: Python 3.8+ or Node.js 18+

## Step 1: Sign Up

FreeMail supports two signup flows:

- **Agent signup** (API-only, no password) -- ideal for AI agents
- **Console signup** (email + password) -- for the developer console at `https://console.victorymail.dev`

### Agent Signup (Recommended for Programmatic Use)

Request a verification code:

```bash
curl -X POST https://api.victorymail.dev/v1/agent/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@yourcompany.com"}'
```

Response:

```json
{
  "message": "Verification code sent",
  "email": "admin@yourcompany.com"
}
```

### Console Signup

```bash
curl -X POST https://api.victorymail.dev/v1/console/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@yourcompany.com",
    "password": "your-secure-password",
    "name": "Your Name"
  }'
```

## Step 2: Verify and Get Your API Key

```bash
curl -X POST https://api.victorymail.dev/v1/agent/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@yourcompany.com", "code": "482917"}'
```

Response:

```json
{
  "organization": {
    "id": "01HXYZ1234567890ABCDEFGHJK",
    "name": "admin",
    "email": "admin@yourcompany.com",
    "tier": "free",
    "status": "active"
  },
  "api_key": {
    "id": "01HXYZ1234567890ABCDEFGHJL",
    "key": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL...",
    "key_prefix": "am_live_7kB3",
    "scope": "org"
  }
}
```

**Important:** Save your API key. The full key is only shown once at creation time.

## Step 3: Create an Inbox

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "Signup Bot"}'
```

Response:

```json
{
  "id": "01HXYZ1234567890ABCDEFGHJM",
  "email": "a7k3m9pq2rx5@victorymail.dev",
  "display_name": "Signup Bot",
  "status": "active",
  "pod_id": "default",
  "message_count": 0,
  "unread_count": 0,
  "created_at": "2025-01-15T10:30:00Z"
}
```

The inbox gets a random `@victorymail.dev` email address. You can also specify your own address if you have a custom domain configured.

## Step 4: Send an Email

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/01HXYZ1234567890ABCDEFGHJM/messages \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": [{"address": "user@example.com"}],
    "subject": "Hello from my AI agent!",
    "body_text": "This email was sent programmatically via FreeMail."
  }'
```

Response:

```json
{
  "id": "01HXYZ1234567890ABCDEFGHJN",
  "thread_id": "01HXYZ1234567890ABCDEFGHJO",
  "inbox_id": "01HXYZ1234567890ABCDEFGHJM",
  "direction": "outbound",
  "status": "queued",
  "subject": "Hello from my AI agent!",
  "to": [{"address": "user@example.com"}],
  "created_at": "2025-01-15T10:31:00Z"
}
```

The message status starts as `queued` and transitions to `sent` once delivered via SES.

## Step 5: Wait for a Reply

Use the `/wait` endpoint to long-poll for incoming messages:

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/01HXYZ1234567890ABCDEFGHJM/wait \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "timeout": 25,
    "filter": {
      "from": "user@example.com"
    }
  }'
```

This blocks for up to 25 seconds until a matching message arrives.

## Step 6: Extract an OTP

The killer feature for AI agents -- wait for a verification email and automatically extract the OTP code:

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/01HXYZ1234567890ABCDEFGHJM/extract-otp \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "noreply@service.com",
    "subject_contains": "verification",
    "timeout": 25
  }'
```

Response:

```json
{
  "code": "482917",
  "message_id": "01HXYZ1234567890ABCDEFGHJP",
  "from": "noreply@service.com",
  "subject": "Your verification code"
}
```

If no OTP can be extracted, `code` will be `null` and `body_text` will be included so you can parse it yourself.

---

## Complete Examples

### Python

```bash
pip install git+https://github.com/IntergalacticTech/FreeMail.ai.git#subdirectory=sdks/python
```

```python
from freemail import FreeMail

client = FreeMail("am_live_YOUR_KEY")

# Create an inbox
inbox = client.inboxes.create(display_name="Signup Bot")
print(f"Inbox email: {inbox['email']}")

# Send an email
msg = client.messages.send(
    inbox["id"],
    to=[{"address": "user@example.com"}],
    subject="Hello!",
    body_text="Sent from my AI agent via FreeMail.",
)
print(f"Message ID: {msg['id']}, status: {msg['status']}")

# Wait for a reply and extract OTP
otp = client.inboxes.extract_otp(
    inbox["id"],
    sender="noreply@service.com",
    timeout=25,
)
print(f"OTP code: {otp['code']}")

# Clean up
client.inboxes.delete(inbox["id"])
```

### Node.js

```bash
npm install IntergalacticTech/FreeMail.ai#main --install-strategy=shallow
```

```typescript
import { FreeMail } from "@freemail/sdk";

const client = new FreeMail("am_live_YOUR_KEY");

// Create an inbox
const inbox = await client.inboxes.create({ display_name: "Signup Bot" });
console.log(`Inbox email: ${inbox.email}`);

// Send an email
const msg = await client.messages.send(inbox.id, {
  to: [{ address: "user@example.com" }],
  subject: "Hello!",
  body_text: "Sent from my AI agent via FreeMail.",
});
console.log(`Message ID: ${msg.id}, status: ${msg.status}`);

// Wait for a reply and extract OTP
const otp = await client.inboxes.extractOtp(inbox.id, {
  sender: "noreply@service.com",
  timeout: 25,
});
console.log(`OTP code: ${otp.code}`);

// Clean up
await client.inboxes.delete(inbox.id);
```

---

## Next Steps

- [API Reference](api-reference.md) -- full endpoint documentation
- [Webhooks](webhooks.md) -- get notified when emails arrive instead of polling
- [Custom Domains](custom-domains.md) -- use your own domain for sending and receiving
- [SDKs](sdks.md) -- detailed SDK documentation
- [MCP Server](mcp-server.md) -- use FreeMail with Claude and other AI agents
