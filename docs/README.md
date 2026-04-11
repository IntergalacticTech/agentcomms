# FreeMail Documentation

FreeMail is an email-as-a-service API platform built for AI agents. It provides programmatic inbox creation, message sending and receiving, OTP extraction, custom domains, webhooks, and more -- all through a simple REST API.

**Base URL:** `https://api.victorymail.dev/v1`

**Developer Console:** `https://console.victorymail.dev`

---

## 5-Minute Quickstart

```bash
# 1. Sign up (no credit card required)
curl -X POST https://api.victorymail.dev/v1/agent/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com"}'

# 2. Verify with the code sent to your email
curl -X POST https://api.victorymail.dev/v1/agent/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "code": "123456"}'
# Response includes your API key (am_live_...) -- save it!

# 3. Create an inbox
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "My Agent"}'

# 4. Send an email
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": [{"address": "user@example.com"}],
    "subject": "Hello from FreeMail!",
    "body_text": "This email was sent by an AI agent."
  }'

# 5. Wait for a reply and extract an OTP
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/extract-otp \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sender": "noreply@example.com", "timeout": 25}'
```

---

## Documentation

| Page | Description |
|------|-------------|
| [Quickstart Guide](quickstart.md) | Step-by-step getting started tutorial with Python and Node.js examples |
| [API Reference](api-reference.md) | Complete endpoint documentation with request/response schemas and curl examples |
| [Webhooks](webhooks.md) | Setting up webhooks, available events, signature verification, retry behavior |
| [Custom Domains](custom-domains.md) | Adding and verifying custom domains, DNS configuration |
| [SDKs](sdks.md) | Python and Node.js SDK installation, usage, and full API reference |
| [MCP Server](mcp-server.md) | Using FreeMail with AI agents via Model Context Protocol |
| [Architecture](architecture.md) | System design, AWS services, data flow, and security model |
| [Billing & Plans](billing.md) | Free and Pro tier limits, upgrading, managing subscriptions |

## Additional Resources

- [OpenAPI Spec](openapi.yaml) -- machine-readable API specification (OpenAPI 3.0)
- [Python SDK on PyPI](https://pypi.org/project/freemail/) -- `pip install freemail`
- [Node.js SDK on npm](https://www.npmjs.com/package/@freemail/sdk) -- `npm install @freemail/sdk`
