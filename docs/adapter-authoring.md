# Adapter Authoring Guide

AgentComms adapters make a communication medium look like the same small set of core operations: provision or bridge a channel, validate inbound events, normalize messages, send replies, expose native surfaces when the medium is not inbox-shaped, and report health.

The core should not know whether a message came from email, Discord, Matrix, fax, radio, postal mail, or an experimental transport. The adapter owns provider details; core owns tenancy, authorization, persistence, indexes, events, and API shape.

## Channel Slugs

Every adapter declares a `channel_name`. Built-in names include `email`, `sms`, `push`, `slack`, `telegram`, `discord`, `whatsapp`, `postal`, `fax`, and `voice`.

External adapters may use any safe slug that matches:

```text
[a-z][a-z0-9_-]{0,62}
```

Examples: `matrix`, `activitypub`, `smoke_signal`, `alien-transmission`.

This slug is persisted on `Channel`, `UnifiedMessage`, `Thread`, and `Draft` records and appears in DynamoDB key segments, API filters, SDK responses, and webhook payloads. Treat it as stable public API once an adapter ships.

## Package Shape

External adapter packages register themselves through Python entry points:

```text
agentcomms-adapter-example/
  pyproject.toml
  agentcomms_adapter_example/
    __init__.py
    adapter.py
    normalize.py
    signing.py
  tests/
  docs/
```

```toml
[project.entry-points."agentcomms.adapters"]
example = "agentcomms_adapter_example.adapter:ExampleAdapter"
```

When the package is installed in the AgentComms runtime, `core.adapters.registry.load_registry()` discovers it and exposes it by `channel_name`.

In-repo adapters use `adapters/<channel>/manifest.toml` instead. Use the in-repo form when the adapter is maintained with the hub and needs CDK wiring shipped here. Use the external package form when the adapter can be developed, released, and versioned independently.

## Adapter Contract

Implement `core.adapters.base.ChannelAdapter`:

```python
class ExampleAdapter(ChannelAdapter):
    channel_name = "example"
    supports_modes = ["provision", "bridge"]

    def provision(self, *, agent, config): ...
    def bridge_start(self, *, agent, config): ...
    def bridge_complete(self, *, channel, callback_params): ...
    def teardown(self, *, channel): ...
    def health_check(self, *, channel): ...
    def ingest(self, *, payload): ...
    def send(self, *, channel, message): ...
```

`provision` is for identities AgentComms creates or owns, such as an email address, phone number, Telegram bot webhook, or provider-side inbox.

`bridge` is for connecting an existing outside workspace or account, such as Slack OAuth, Discord guild install, WhatsApp Business, or a customer-managed webhook endpoint.

Adapters may support one mode or both. Return explicit errors for unsupported modes rather than silently doing partial setup.

## Persistence Boundary

Adapters should not write DynamoDB rows directly during normal message flow. They return:

- `ProvisionResult` or `BridgeResult` for channel lifecycle.
- `UnifiedMessage` or `None` from inbound ingestion.
- `SendResult` from outbound sends.
- Optional native containers and native messages for channel-specific surfaces.

Core writes `Channel`, `UnifiedMessage`, `Thread`, `Draft`, and event records. This keeps tenant isolation and API behavior consistent across every adapter.

Provider credentials belong in AWS SSM Parameter Store or the channel `config` only when safe to return through the API. Never put access tokens, signing secrets, private keys, or webhook shared secrets into API-visible `config`.

## Inbound Rules

Inbound adapters should:

- Verify provider signatures before parsing message content.
- Drop non-message events by returning `None`.
- Use a stable provider event or message ID as `external_id` for idempotency.
- Preserve native IDs, thread IDs, timestamps, rooms, teams, guilds, users, and raw event hints in `channel_native`.
- Put human-readable text in `body_text`.
- Use `body_html` only when the provider has meaningful HTML.
- Put the provider conversation, room, email thread, call ID, or equivalent into `thread_key`.
- Set `is_dm=true` only for direct messages, explicit mentions, or events the agent must treat as addressed to it.

Ambient room traffic should stay out of the unified inbox. Expose it through native surfaces.

## Outbound Rules

Outbound adapters receive an `OutboundMessage` and a persisted `Channel`.

Adapters should:

- Resolve `message.to` in the provider-native way.
- Preserve `message.thread_key` when the provider supports replies.
- Honor `message.channel_native_overrides` for reply metadata such as `in_reply_to`, `references`, channel IDs, chat IDs, or room IDs.
- Return provider message IDs in `SendResult.channel_native_id`.
- Return `status="failed"` with a useful `error` when the provider rejects the send.

Core records the outbound message after the adapter returns.

## Native Surfaces

For workspace-shaped systems, implement:

- `list_native_containers`
- `list_native_messages`
- `send_to_native_target`

Examples are Slack channels, Discord guild channels, Matrix rooms, Telegram groups, IRC channels, and forum threads. These APIs let agents inspect and act in a provider-native space without flooding the unified inbox.

## Testing Checklist

A serious adapter PR or package should include:

- Unit tests for provisioning config validation.
- Signature/auth validation tests with accepted and rejected fixtures.
- Normalization tests for direct messages, mentions, ambient traffic, edits, deletes, attachments, and provider retries.
- Send and reply tests with the provider client mocked.
- Health-check tests for missing credentials and reachable credentials.
- At least one fixture based on a real provider payload with secrets redacted.
- Documentation for setup, webhook URLs, scopes, permissions, rate limits, retries, and teardown behavior.

Start from [`examples/adapter-template/`](../examples/adapter-template/) for the external package path.
