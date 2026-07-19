# FreeMail Documentation

> ⚠️ **OUTDATED — pre-AgentComms cutover.** The reference pages linked below (api-reference, quickstart,
> sdks, webhooks, custom-domains, billing, agent-instructions, mcp-server, architecture, roadmap,
> openapi.yaml) still document the retired FreeMail API — `ak_live_` keys, `/inboxes`, and
> `api.victorymail.dev`. The platform has since cut over to **AgentComms** (`ak_live_` keys, `/agents`,
> `api.agentcomms.dev/v1`). These docs are being rewritten. Until then, use the repo root
> [README.md](../README.md) and [AGENT.md](../AGENT.md) as the current onboarding path, plus
> [docs/YOUR_INSTANCE.md](YOUR_INSTANCE.md) and [docs/TESTING_PLAN.md](TESTING_PLAN.md).

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
# Response includes your API key (ak_live_...) -- save it!

# 3. Create an inbox
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "My Agent"}'

# 4. Send an email
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages \
  -H "x-api-key: ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": [{"address": "user@example.com"}],
    "subject": "Hello from FreeMail!",
    "body_text": "This email was sent by an AI agent."
  }'

# 5. Wait for a reply and extract an OTP
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/extract-otp \
  -H "x-api-key: ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sender": "noreply@example.com", "timeout": 25}'
```

---

## Documentation

| Page | Description |
|------|-------------|
| [Quickstart Guide](quickstart.md) | Step-by-step getting started tutorial with Python and Node.js examples |
| [API Reference](api-reference.md) | Complete endpoint documentation with request/response schemas and curl examples |
| [Agent Instructions](agent-instructions.md) | Condensed API cheat sheet optimized for AI agents |
| [Webhooks](webhooks.md) | Setting up webhooks, available events, signature verification, retry behavior |
| [Custom Domains](custom-domains.md) | Bringing your own domain, DNS configuration (paid tiers) |
| [SDKs](sdks.md) | Python and Node.js SDK installation, usage, and full API reference |
| [MCP Server](mcp-server.md) | Using FreeMail with AI agents via Model Context Protocol |
| [Architecture](architecture.md) | System design, AWS services, data flow, and security model |
| [Platform Review](platform-review.md) | Current platform assessment, high-priority risks, and recommended roadmap |
| [Azure Native Setup](azure-native-setup.md) | Proposed Azure-native architecture, deployment plan, and inbound email options |
| [Billing & Plans](billing.md) | Free / Starter / Pro / Enterprise limits, upgrading, BYOC tier |
| [BYOC Deployment](byoc.md) | Run FreeMail in your own AWS account via AWS Marketplace |
| [Roadmap](roadmap.md) | What's shipped and what's coming (SMS OTP, vault, persona, push, WhatsApp, BYOC) |

## Additional Resources

- [OpenAPI Spec](openapi.yaml) -- machine-readable API specification (OpenAPI 3.0)
- [Python SDK](https://github.com/IntergalacticTech/freemail/tree/main/sdks/python)
- [Node.js SDK](https://github.com/IntergalacticTech/freemail/tree/main/sdks/node)
