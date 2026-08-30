# Platform Review

Status: review updated on 2026-08-29 after the Apache-2.0 OSS cleanup and API/SDK contract pass.

## Executive Summary

AgentComms is now pointed in the right direction for an open-source AI communications hub. The strongest assets are the agent-centric domain model, the `UnifiedMessage` abstraction, the adapter contract, and the deployable AWS CDK stack. The repository is no longer blocked by a restrictive license, hard-coded maintainer AWS account, missing API key routes, or stale SDK/MCP contracts for the main agent/message flows.

The next serious work is less about product copy and more about production architecture: durable async delivery, adapter package contracts, provider abstraction, deeper console operations, and a clean split between legacy migration material and current public docs.

## Resolved In This Pass

- Switched repository licensing to Apache-2.0 and removed the separate commercial license template.
- Replaced public restrictive-license copy in the README, license explainer, landing page, launch drafts, and key planning docs.
- Added API key management handlers and CDK routes for `GET/POST /v1/api-keys` and `DELETE /v1/api-keys/{key_id}`.
- Fixed core message routes so clients can get by stable `message_id`, reply, mark read, and delete without timestamp knowledge.
- Aligned SDK/MCP/CLI payloads with current handlers for messages, wait/OTP, vault, domains, AI, Slack, Telegram, push, and API keys.
- Parameterized the CDK app account/region through context and environment instead of pinning deployments to one account.
- Fixed the TOKEN authorizer Lambda to parse method/path from `methodArn`.
- Fixed inbound email raw-MIME lookup to respect the SES `inbound/` S3 prefix.
- Replaced stale public docs for quickstart, SDKs, MCP, architecture, API reference, BYOC, billing, and roadmap.
- Updated the console's default API URL and primary Agents, Messages, API Keys, and Domains views to the current route and response shapes.

## Remaining High-Priority Risks

### 1. Durable Async Delivery

Outbound sends are still too synchronous for a hub that will cover unreliable providers. Every adapter needs a durable outbox contract with idempotency keys, retries, backoff, status transitions, and dead-letter visibility.

Recommendation:

- Add an `outbox` entity and worker path keyed by org, agent, channel, and message.
- Define adapter retry categories: permanent, transient, rate-limited, provider-auth, and user-action-required.
- Expose delivery status consistently through messages, webhooks, and `agentcomms status`.

### 2. Adapter Contract Testing

The `ChannelAdapter` interface is good, but there is no shared compliance test suite that adapter authors can run.

Recommendation:

- Create adapter contract tests for `provision`, `ingest`, `send`, `health_check`, native surfaces, and idempotency.
- Publish provider fixture conventions under `docs/adapters/`.
- Make Discord the first adapter to pass the new contract suite.

### 3. External Adapter Compatibility

`core.adapters.registry` supports Python entry points in `agentcomms.adapters`, and `examples/adapter-template/` now gives external adapter authors a working starting point. The next issue is compatibility discipline: adapter packages need a clear contract for which hub versions they support.

Recommendation:

- Publish an adapter contract version and require packages to declare compatibility.
- Add a shared adapter compliance suite for lifecycle, ingest, send, health, native surfaces, and idempotency.
- Keep core repo adapters as reference implementations, not the only supported extension path.

### 4. Provider Abstraction Beyond AWS

The domain model can outlive AWS, but runtime code still uses direct AWS clients in several handlers/adapters.

Recommendation:

- Formalize provider interfaces for table, blob, events, queues, secrets, email, SMS, push, and AI.
- Move direct `boto3` access behind provider modules where practical.
- Treat Azure as a provider port after the AWS provider boundary is clean.

### 5. Console Operations Depth

The console is back on the current API surface, but OSS users still need better operational visibility into native surfaces, adapter health, and provider setup errors.

Recommendation:

- Rebuild console navigation around Agents, Channels, Messages, Native Surfaces, API Keys, Domains, Vault, Webhooks, and Adapter Health.
- Avoid making provider setup a hidden docs-only workflow; surface missing SSM secrets and provider permissions in UI.

### 6. Legacy Material

Migration scripts and pre-pivot design docs still intentionally mention FreeMail/VictoryMail. That is fine for historical context, but current docs should remain agent-centric.

Recommendation:

- Move old docs into `docs/legacy/` after the cutover window closes.
- Keep `MIGRATION.md` and tools docs for operators.
- Add a top-level note to any preserved historical doc that points to the current quickstart and architecture.

## OSS Contribution Priorities

1. Discord adapter implementation.
2. Generic webhook adapter.
3. Adapter compliance test harness.
4. Durable outbox and inbound idempotency.
5. Adapter version compatibility policy.
6. Console adapter-health and provider-setup views.
7. Dependency license inventory refresh in `NOTICE`.

## Strategic Direction

AgentComms should stay strict at the center and weird at the edges. Core owns tenancy, auth, normalized persistence, event publication, and dispatch. Adapters own every provider quirk, from Slack threads to WhatsApp templates to fax delivery receipts to any future transport that can be represented as an event and a reply target.
