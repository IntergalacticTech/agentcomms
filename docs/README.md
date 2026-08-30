# AgentComms Documentation

AgentComms is an Apache-2.0 communications hub for AI agents. It gives agents durable identities across email, SMS, Slack, Telegram, push, and external adapter channels, then normalizes direct messages and explicit mentions into one agent-scoped inbox.

## Start Here

- [AGENT.md](../AGENT.md) - deploy AgentComms into your AWS account with the CLI
- [quickstart.md](./quickstart.md) - create an agent, provision channels, send, read, wait, and reply
- [architecture.md](./architecture.md) - current system design
- [adapter-authoring.md](./adapter-authoring.md) - adapter package contract and testing checklist
- [adapter-roadmap.md](./adapter-roadmap.md) - how new communication channels should plug in
- [api-reference.md](./api-reference.md) - REST API overview
- [openapi.yaml](./openapi.yaml) - compact OpenAPI contract
- [sdks.md](./sdks.md) - Python and Node SDK usage
- [mcp-server.md](./mcp-server.md) - MCP tools for coding agents
- [licensing.md](./licensing.md) - Apache-2.0 permissions and obligations

## Base URL

Hosted default:

```text
https://api.agentcomms.dev/v1
```

Self-hosted deployments use the API URL emitted by `agentcomms bootstrap`.

## Authentication

Send an API key with either header:

```bash
curl https://api.agentcomms.dev/v1/agents \
  -H "Authorization: Bearer ak_live_YOUR_KEY"
```

```bash
curl https://api.agentcomms.dev/v1/agents \
  -H "x-api-key: ak_live_YOUR_KEY"
```

## Core Objects

| Object | Purpose |
|---|---|
| `Agent` | The durable actor that owns channels, messages, threads, drafts, webhooks, and native surfaces |
| `Channel` | One communication identity or bridge, such as an email address, SMS number, Slack workspace app, Telegram bot, or push target |
| `UnifiedMessage` | The normalized message shape across every channel |
| `Thread` | Cross-channel or channel-native conversation grouping |
| `Webhook` | Event delivery subscription under an agent |
| `ApiKey` | Org, agent, or channel scoped API credential |

## Current Channels

| Channel | Status |
|---|---|
| Email | Working through AWS SES |
| SMS | Working through AWS End User Messaging setup |
| Push | Working through APNs/FCM via SNS platform endpoints |
| Slack | Working for bridge/native routes with app credentials |
| Telegram | Working for bot-based channels |
| Discord | Scaffolded for contribution |
| External adapters | Supported through `agentcomms.adapters` Python entry points |

Historical FreeMail/VictoryMail docs and migration notes remain in [`legacy/`](./legacy/) and `superpowers/` where they are useful for cutover context, but new integrations should use the AgentComms agent-centric API.

## Public Website

The static landing site lives in [`landing/`](../landing/) and is deployed by the `AgentCommsLanding` CDK stack. The stack emits a CloudFront URL. Point `agentcomms.dev` at that distribution after the Route 53 hosted zone and ACM certificate are configured.
