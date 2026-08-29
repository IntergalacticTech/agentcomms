# Adapter Roadmap

AgentComms should be the open-source hub for AI communications. Email and SMS are only the beginning; the core architecture should make new transports boring to add, whether the transport is Slack, Discord, WhatsApp, voice, fax, postal mail, webhooks, ham radio, satellite links, or something nobody has named yet.

## North Star

A new channel should be shippable as an adapter package with:

- A `ChannelAdapter` implementation.
- A manifest that declares channel name, supported modes, webhook routes, required secrets, and optional CDK wiring.
- Provider-specific validation for inbound events.
- Normalization into `UnifiedMessage`.
- Send/reply implementation that preserves provider-native threading.
- Health checks and setup docs.
- Unit tests and at least one integration-style fixture.

Core should not need to know whether a message came from email, Discord, fax, or an alien uplink. Core should know only tenancy, agent ownership, message shape, idempotency, event publication, and authorization.

## Adapter Modes

| Mode | Use when | Examples |
|---|---|---|
| `provision` | AgentComms creates or owns the communication identity | Email local part, SMS number, Telegram bot token, push endpoint |
| `bridge` | AgentComms connects to an existing external account/workspace | Slack OAuth workspace, Discord guild bot, WhatsApp Business account |

Adapters may support one or both modes. If a provider requires human setup in its console, the adapter should make that explicit through docs, SSM secret requirements, and actionable health checks.

## Message Normalization Rules

Every adapter should map inbound events into `UnifiedMessage` consistently:

- Use stable provider-native IDs for `external_id` where available.
- Preserve threading in `thread_key`.
- Put sender and recipient addresses into normalized `Party` objects.
- Store provider details in `channel_native`, not in new core fields.
- Set `is_dm=true` only for direct messages and explicit mentions.
- Keep ambient room traffic out of the unified inbox and expose it through native surfaces.
- Make ingestion idempotent. Replayed webhooks must not duplicate messages.

## Native Surfaces

Some channels are not naturally inbox-shaped. Slack, Discord, Matrix, and Telegram have workspaces, guilds, rooms, topics, channels, and DMs. Adapters should expose those through:

- `list_native_containers`
- `list_native_messages`
- `send_to_native_target`

The unified inbox is for messages that demand the agent's attention. Native surfaces are for context, monitoring, and intentional room interaction.

## Runtime Work Needed

The current core works for synchronous API handlers and provider webhooks. To scale into a real hub, the next infrastructure tranche should add:

- Durable outbound outbox with retries, backoff, and dead-letter handling per channel.
- Inbound idempotency table keyed by provider event ID.
- Event consumer framework for webhooks, analytics, audit logs, and async agents.
- Adapter health registry exposed through `agentcomms status`.
- Provider rate-limit adapters with clear per-channel quotas.
- Secret schema validation for adapter setup.
- Contract tests that every adapter can run locally.

## OSS Adapter Package Shape

External adapters should be publishable outside this repo:

```text
agentcomms-adapter-discord/
  pyproject.toml
  agentcomms_adapter_discord/
    __init__.py
    adapter.py
    normalize.py
    signing.py
  tests/
  docs/
  manifest.toml
```

Package metadata should expose:

```toml
[project.entry-points."agentcomms.adapters"]
discord = "agentcomms_adapter_discord.adapter:DiscordAdapter"
```

The in-repo registry already checks that entry point group.

See [adapter-authoring.md](./adapter-authoring.md) and [`examples/adapter-template/`](../examples/adapter-template/) for the copyable implementation path.

## Priority Queue

| Priority | Adapter | Why |
|---|---|---|
| P0 | Discord | Natural agent/community channel; scaffold already exists |
| P0 | Generic webhook | Lets any system POST events into the hub before a full adapter exists |
| P1 | WhatsApp Business | High-value human channel; provider setup is the hard part |
| P1 | Matrix | Open federated chat aligns with OSS values |
| P1 | Voice | Phone agents need call events, transcripts, and outbound call initiation |
| P2 | Fax | Still appears in healthcare, legal, government, and finance workflows |
| P2 | Postal mail | Useful for compliance notices and physical-world workflows |
| P2 | Signal | Valuable but difficult due to ecosystem constraints |
| P3 | IRC, XMPP, ActivityPub | Good community adapters once the external package path is polished |

## Contribution Bar

A new adapter PR should include:

- Normalization tests with real-looking provider fixtures.
- Signature/auth validation tests.
- Send/reply tests with provider clients mocked.
- Docs for setup, secrets, scopes, webhook URLs, rate limits, and failure modes.
- CDK wiring if the channel requires AWS resources.
- A health check that fails with actionable setup errors.

The best first templates today are `adapters/telegram/` for simple bot-style channels and `adapters/slack/` for bridge/OAuth channels.
