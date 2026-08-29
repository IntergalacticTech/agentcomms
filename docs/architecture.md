# AgentComms Architecture

AgentComms is an open-source communications hub for AI agents. The product boundary is simple: agents get durable identities on many channels, every direct message and explicit mention becomes a normalized `UnifiedMessage`, and channel-specific behavior stays available through native sub-surfaces.

## System Shape

```text
SDKs / MCP / REST clients
        |
        v
API Gateway + Lambda handlers
        |
        +--> Lambda authorizer -> DynamoDB API key lookup
        |
        +--> DynamoDB single-table metadata
        +--> S3 buckets for large message bodies and attachments
        +--> Kinesis event stream for message and lifecycle events
        +--> Channel adapters for provider-specific ingress/egress

Adapters today: email, SMS, push, Slack, Telegram
Scaffolded next: Discord
Open adapter targets: WhatsApp, voice, fax, postal, Matrix, Signal, webhooks, and anything event-shaped
```

## Core Invariants

- `Agent` is the top-level actor. Channels, messages, threads, drafts, webhooks, and native surfaces hang under an agent.
- `Channel` records describe one identity or bridge on one medium: email address, SMS number, Slack workspace app, Telegram bot, push target, and future adapters.
- `UnifiedMessage` is the channel-neutral message shape. It preserves `channel_native` metadata so adapters do not flatten away details the agent may need.
- Direct messages and explicit mentions use `is_dm=true` and project into the unified inbox index.
- Ambient room traffic, such as Slack channels or Discord guild chatter, stays out of the unified inbox and is exposed through native channel routes.
- API keys are hashed before storage and scoped to org, agent, or channel.

## Main Data Flow

### Inbound

1. A provider delivers an event to an adapter endpoint or AWS event source.
2. The adapter validates provider signatures and normalizes the payload.
3. The adapter returns a `UnifiedMessage` or `None` if the event is not message material.
4. Core persistence writes the message, updates indexes, and publishes a `message.received` event.
5. Webhooks, wait/OTP polling, SDKs, MCP tools, and future async consumers observe the normalized message.

### Outbound

1. A client calls `POST /v1/agents/{agent_id}/messages` or `.../{message_id}/reply`.
2. The API selects the active channel by explicit `channel`, inferred recipient address, or original thread context.
3. The adapter sends using the provider-native API.
4. Core persistence stores the outbound message with native provider IDs and status.
5. Delivery, bounce, complaint, or provider callback events update status when available.

## Adapter Contract

Every adapter implements `core.adapters.base.ChannelAdapter`:

```python
class ChannelAdapter:
    channel_name: str
    supports_modes: list[Literal["provision", "bridge"]]

    def provision(self, *, agent, config): ...
    def bridge_start(self, *, agent, config): ...
    def bridge_complete(self, *, channel, callback_params): ...
    def teardown(self, *, channel): ...
    def health_check(self, *, channel): ...
    def ingest(self, *, payload): ...
    def send(self, *, channel, message): ...
    def list_native_containers(self, *, channel): ...
    def list_native_messages(self, *, channel, container_id, **filters): ...
    def send_to_native_target(self, *, channel, target, message): ...
    def cdk_wiring(self, *, stack, context): ...
```

Adapters are discovered from in-repo `adapters/*/manifest.toml` files and Python entry points in the `agentcomms.adapters` group. That means the OSS hub can grow through independent adapter packages, not only through core repo changes. See [adapter-authoring.md](./adapter-authoring.md) for channel slug rules, package shape, security expectations, and adapter tests.

## AWS Implementation

The default deployment target is AWS:

| Layer | AWS service |
|---|---|
| HTTP API | API Gateway REST |
| Compute | Lambda Python 3.12 |
| Metadata | DynamoDB single-table |
| Large bodies and attachments | S3 |
| Events | Kinesis |
| Queues and notifications | SQS/SNS where adapters need them |
| Email | SES |
| SMS | AWS End User Messaging |
| Secrets | SSM Parameter Store and KMS |
| AI helpers | Bedrock |
| Static console/landing | CloudFront and S3 |
| Infrastructure | AWS CDK v2 |

The CDK app defaults to the caller's account/region via CDK context or `CDK_DEFAULT_ACCOUNT`/`CDK_DEFAULT_REGION`. Legacy VictoryMail stacks are opt-in and are not part of normal AgentComms bootstrap.

## API Surface

The stable public surface is agent-centric:

- `/v1/agents`
- `/v1/agents/{agent_id}/channels`
- `/v1/agents/{agent_id}/messages`
- `/v1/agents/{agent_id}/messages/{message_id}/reply`
- `/v1/agents/{agent_id}/wait`
- `/v1/agents/{agent_id}/extract-otp`
- `/v1/agents/{agent_id}/threads`
- `/v1/agents/{agent_id}/drafts`
- `/v1/agents/{agent_id}/webhooks`
- `/v1/agents/{agent_id}/slack/...`
- `/v1/agents/{agent_id}/telegram/...`
- `/v1/agents/{agent_id}/push/...`
- `/v1/api-keys`
- `/v1/vault`
- `/v1/personas`
- `/v1/domains`

SDKs and the MCP server should be treated as contract tests for this surface. When a route changes, update API handler tests, SDK tests, MCP tests, OpenAPI docs, and CLI docs in the same change.

## Design Direction

AgentComms should become a hub for any communication medium an agent can use. The core should stay boring and strict: auth, tenancy, normalized persistence, event publication, and dispatch. The adapters should absorb provider-specific complexity.

See [adapter-authoring.md](./adapter-authoring.md) for the adapter implementation guide and [adapter-roadmap.md](./adapter-roadmap.md) for the deeper OSS adapter roadmap.
