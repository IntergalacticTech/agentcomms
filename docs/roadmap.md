# AgentComms Roadmap

AgentComms is moving toward one open-source hub for AI communications: one agent identity model, many channel adapters, one normalized inbox, and native surfaces for channels that are more complex than an inbox.

## Current

| Area | Status |
|---|---|
| Agent-centric API | Working |
| Unified message model | Working |
| API key scopes | Org, agent, and channel scopes |
| Email adapter | Working through AWS SES |
| SMS adapter | Working through AWS End User Messaging setup |
| Push adapter | Working through APNs/FCM via SNS |
| Slack adapter | Working for bridge/native routes with app credentials |
| Telegram adapter | Working for bot channels |
| Python SDK | Working |
| Node SDK | Working |
| MCP server | Working |
| CLI bootstrap | Working, with provider setup still required for some channels |
| External adapter package template | Working |
| Public landing site CDK deployment | Working |
| Discord adapter | Scaffolded |

## Near Term

1. Harden adapter contract tests so every adapter can prove lifecycle, ingest, send, health, and native-surface behavior locally.
2. Complete Discord adapter implementation.
3. Add a generic webhook adapter for any event-shaped source.
4. Make outbound delivery durable with per-channel retry/backoff/dead-letter semantics.
5. Add inbound idempotency keyed by provider event IDs.
6. Improve `agentcomms status` with adapter health and setup remediation.
7. Add examples for MCP-driven agents that can create channels, wait for OTPs, and reply across channels.

## Adapter Targets

| Priority | Adapter | Notes |
|---|---|---|
| P0 | Discord | Scaffold exists; implement guild/channel/DM normalization and sends |
| P0 | Generic webhook | Lowest-friction path for arbitrary systems |
| P1 | WhatsApp Business | Valuable but provider setup-heavy |
| P1 | Matrix | Open/federated channel aligned with OSS |
| P1 | Voice | Calls, transcripts, and outbound call initiation |
| P2 | Fax | Compliance-heavy industries still need it |
| P2 | Postal mail | Physical notices and workflows |
| P2 | Signal | Useful but constrained ecosystem |
| P3 | IRC/XMPP/ActivityPub | Good external adapter package candidates |

## Platform Work

- Provider abstraction beyond AWS for table, blob, queue, event, secrets, email, SMS, push, and AI services.
- Azure-native deployment path once inbound email strategy is settled.
- Console rebuild around agents, channels, native surfaces, and adapter health.
- Security hardening for request authorizer events, least-privilege IAM, secret rotation, and signed webhook delivery.
- Dependency license inventory in `NOTICE`.

## Contribution Path

Start with [adapter-roadmap.md](./adapter-roadmap.md) and open an issue describing the channel, provider, mode (`provision`, `bridge`, or both), required secrets, webhook payload examples, and expected native surfaces.
