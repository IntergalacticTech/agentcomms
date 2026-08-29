# AgentComms

**An open-source communications hub for AI agents: email, SMS, Slack, Telegram, push, and new adapter channels in one unified inbox.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](./LICENSE)
[![Tests](https://github.com/IntergalacticTech/FreeMail.ai/actions/workflows/test.yml/badge.svg)](https://github.com/IntergalacticTech/FreeMail.ai/actions/workflows/test.yml)

## What It Does

AgentComms gives each AI agent durable communication identity across human and machine channels:

- Email addresses on your domain
- SMS numbers through AWS End User Messaging
- Slack workspace identities through OAuth bridge mode
- Telegram bots
- Mobile push notifications through APNs and FCM
- A small adapter contract for the rest: Discord, WhatsApp, fax, voice, postal mail, radio, or anything else that can send and receive structured events

All direct messages and explicit mentions route into one agent-scoped timeline:

```python
from agentcomms import Client

client = Client(api_key="ak_live_your_key", base_url="https://api.your-domain.com/v1")

created = client.agents.create(
    name="InvoiceBot",
    provision={
        "email": {"local_part": "invoice", "domain": "your-domain.com"},
        "sms": {},
        "telegram": {"bot_token": "..."},
    },
    bridge={"slack": {"return_url": "https://your-app.example/slack/oauth/callback"}},
)

agent = client.agents(created["agent_id"])

for msg in agent.messages.list():
    print(f"[{msg.channel}] {msg.from_.address}: {msg.body_text}")
    if "invoice" in (msg.body_text or "").lower():
        agent.messages.reply(msg.message_id, body="Got it, processing.")
```

## Self-Deploying Infrastructure

The core deployment target is your own AWS account. The CLI is built so a coding agent can run it end to end:

```bash
npm i -g @agentcomms/cli
agentcomms bootstrap \
  --domain your-domain.com \
  --admin-email you@your-domain.com \
  --non-interactive \
  --json
```

See [AGENT.md](./AGENT.md) for the deployment contract, preflight checks, NDJSON output, exit codes, and recovery paths.

## Architecture

```text
    +--- SDKs / MCP / REST clients ---+
    v                                 v
 +----------------------------------------------+
 |   API Gateway + Lambda (Hub API)             |
 +------+-------------------+----------+--------+
        |                   |          |
  +-----v-----+    +--------v---+  +---v--------------------+
  | DynamoDB  |    | Kinesis    |  | Channel Adapter        |
  | single    |    | events     |  | Runtime (Lambda)       |
  | table     |    |            |  +--+------+------+-----+-+
  +-----------+    +------------+     |      |      |     |
                                    SES    SMS    Slack  Telegram
                                  (email) (AWS)  (OAuth)  (bot)
```

- **Agent-centric**: `Agent` is the top-level object. Channels, messages, threads, drafts, webhooks, and native surfaces are scoped under an agent.
- **Unified inbox**: Direct messages and explicit mentions merge into one timeline. Channel-native room traffic remains accessible through channel-specific paths.
- **AWS-native**: DynamoDB, Lambda, SES, SNS, SQS, Kinesis, API Gateway, KMS, Bedrock. No Kafka, Redis, or Postgres required.
- **Adapter-first**: Each channel implements `core.adapters.base.ChannelAdapter`. Adding a channel should mean adding an adapter module, CDK wiring, tests, and docs, not rewriting the hub.

See [docs/architecture.md](./docs/architecture.md) for the current system design, [docs/adapter-authoring.md](./docs/adapter-authoring.md) for the adapter contract, and [docs/adapter-roadmap.md](./docs/adapter-roadmap.md) for the channel-adapter roadmap.

## Status

| Area | Status |
|---|---|
| Core API, data model, auth, unified inbox | Working |
| Email, SMS, push, Slack, Telegram adapters | Working, with external provider setup required |
| Python SDK, Node SDK, MCP server, CLI | Working |
| Discord adapter | Scaffolded |
| API key management | Working |
| Next adapter targets | Discord, WhatsApp, voice, fax, postal |

## Repo Layout

```text
adapters/   Channel adapter implementations
cdk/        AWS CDK infrastructure
cli/        agentcomms CLI
console/    Management console
core/       Shared Python runtime, API handlers, models, registry
docs/       API docs, channel guides, runbooks, historical design notes
examples/   Example agent integrations
mcp/        MCP server for agent tool use
sdks/       Python and Node SDKs
tests/      Unit, integration, and e2e tests
tools/      Seed, migration, smoke, and maintenance scripts
```

## License

AgentComms is true open source under the Apache License 2.0. See [LICENSE](./LICENSE) and [docs/licensing.md](./docs/licensing.md).

## Contributing

Contributions welcome. New channel adapters are the highest-leverage work; start with [examples/adapter-template/](./examples/adapter-template/) for an external package or `adapters/telegram/` for an in-repo adapter. See [CONTRIBUTING.md](./CONTRIBUTING.md).

## Contact

- Issues: [GitHub Issues](https://github.com/IntergalacticTech/FreeMail.ai/issues)
- Security: `security@agentcomms.dev` - see [SECURITY.md](./SECURITY.md)
