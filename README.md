# AgentComms

**Your agent's identity and communications hub — email, SMS, Slack, Telegram, push — one unified inbox, one AWS deployment, one source-available codebase.**

[![License: FSL-1.1-Apache-2.0](https://img.shields.io/badge/License-FSL--1.1--Apache--2.0-blue.svg)](./LICENSE)
[![Tests: 277 passing](https://img.shields.io/badge/tests-277-brightgreen)](https://github.com/IntergalacticTech/FreeMail.ai/actions)

---

## What it does

When you spin up a new AI agent, one API call gets that agent:
- An email address at your domain
- A phone number for SMS (US 10DLC)
- A Slack bot identity (bridged into your workspace)
- A Telegram bot
- Mobile push notifications (APNs + FCM)

All routing into **one unified inbox** the agent reads from:

```python
from agentcomms import Client

client = Client(api_key="ak_live_...")
agent = client.agents.create(
    name="InvoiceBot",
    provision={
        "email": {"local_part": "invoice"},
        "sms": {},
        "telegram": {"bot_token": "..."},
    },
    bridge={"slack": {"return_url": "https://..."}},
)

for msg in agent.messages.stream():
    print(f"[{msg.channel}] {msg.from_.address}: {msg.body_text}")
    if "invoice" in msg.body_text.lower():
        agent.messages.reply(msg.message_id, body="Got it, processing...")
```

## The differentiator: your coding agent deploys it

Point Claude Code, Cursor, or Aider at this repo and your AWS credentials. Twenty minutes later your agent has its own email, phone, and Slack identity — running in YOUR cloud, under YOUR control.

```bash
npm i -g @agentcomms/cli
agentcomms bootstrap --domain your-domain.com --admin-email you@your-domain.com --json
```

See [AGENT.md](./AGENT.md) for the full deployment guide written for coding agents.

## Why source-available, not open source

Functional Source License (FSL-1.1-Apache-2.0). You can:
- Self-host for personal, internal, or company use
- Modify and redistribute under FSL
- Build commercial products on top of your AgentComms deployment

You cannot:
- Offer AgentComms as a paid hosted service to third parties (that's the Competing Use clause)

After 2 years, each file automatically relicenses to Apache 2.0.

Commercial licenses available — contact `commercial@agentcomms.dev`.

See [docs/licensing.md](./docs/licensing.md) for the plain-English explanation.

## Architecture

```
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

- **Agent-centric**: `Agent` is the top-level object. Everything else (channels, messages, threads) is scoped under an agent.
- **Unified inbox**: Direct messages and @mentions from every channel merged into one timeline. Channel-native activity accessible via per-channel sub-surfaces.
- **AWS-native**: DynamoDB, Lambda, SES, SNS, SQS, Kinesis, Bedrock. No Kafka, no Redis, no Postgres.
- **Plugin adapter SDK**: Each channel is a module in `adapters/` implementing the `ChannelAdapter` contract. Add a new channel by copying an existing adapter and changing ~300 lines.

See [docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md](./docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md) for the full design spec.

## Status

| Phase | Status |
|---|---|
| Phase 1: Foundation | Complete |
| Phase 2: SMS + Push + Vault + Personas + Domains + AI | Complete |
| Phase 3: Slack + Telegram | Complete |
| Phase 4: OSS packaging | In progress |
| Phase 5: Migration + cutover | Upcoming |
| Phase 6: Public launch | Upcoming |

## Quickstart

See [AGENT.md](./AGENT.md) for agent-assisted deploy, or [docs/quickstart.md](./docs/quickstart.md) for manual setup.

The live API is available at `https://agentcomms.dev/v1/` — sign up at `agentcomms.dev` if you don't want to run your own deployment.

## Repo layout

```
adapters/         Channel adapter implementations (email, sms, push, slack, telegram)
cdk/              AWS CDK infrastructure (TypeScript)
cli/              agentcomms CLI (TypeScript) — Phase 4 Task 3
console/          React management console
core/             Shared Python runtime (data models, event bus, adapter registry)
docs/             API reference, quickstart, per-channel guides
lambdas/          Lambda handlers (Hub API, authorizer, billing, etc.)
mcp-server/       MCP server for agent tool use
sdks/             Client SDKs — Python (agentcomms) + Node (@agentcomms/client)
tests/            Integration + unit tests (277 passing)
tools/            Ops scripts (seed, SPDX headers, etc.)
```

## Contributing

Contributions welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md).

New channel adapters are the highest-leverage contribution: start with `adapters/telegram/` as the simplest template. Discord scaffolding is already at `adapters/discord/`.

## Contact

- Issues: [GitHub Issues](https://github.com/IntergalacticTech/FreeMail.ai/issues)
- Commercial licensing: `commercial@agentcomms.dev`
- Security: `security@agentcomms.dev` — see [SECURITY.md](./SECURITY.md) for responsible disclosure policy
