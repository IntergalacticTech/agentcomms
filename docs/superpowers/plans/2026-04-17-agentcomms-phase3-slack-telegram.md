# AgentComms Phase 3: Slack + Telegram Adapters — Implementation Plan

> **Fidelity note:** B-fidelity (file layouts + key design decisions + commit boundaries). Follow the Phase 1 TDD rhythm; expand task-level detail before execution if desired.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Spec:** `docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md`
**Predecessors:** Phases 1 & 2 complete and merged.

**Goal:** Add Slack and Telegram as greenfield adapters — the two new channels that validate the adapter SDK against platforms with OAuth (Slack) and native hierarchy (Slack workspaces/channels, Telegram chats). At Phase 3 exit, all 5 v0.1 channels are live and the unified inbox shows cross-channel DMs interleaved.

**Architecture:** Slack = B-mode primary (OAuth into user's workspace) + A-mode limited (one deployer-created Slack app, agents become distinct bot-users under it). Telegram = A-mode only (each agent gets its own BotFather-created bot). Both channels introduce API Gateway webhook routes (`/webhooks/slack/events`, `/webhooks/slack/oauth/callback`, `/webhooks/telegram/{token_hash}`).

**Tech Stack:** Same as Phase 1/2 + `slack_sdk` (Python) + custom Telegram Bot API client (no third-party lib; the API is small enough).

---

## File structure (created in Phase 3)

```
adapters/slack/
├── manifest.toml
├── adapter.py                # SlackAdapter(ChannelAdapter)
├── normalize.py              # Slack Events API payload → UnifiedMessage
├── ingest.py                 # API Gateway Lambda for /webhooks/slack/events
├── oauth.py                  # API Gateway Lambda for /webhooks/slack/oauth/callback
├── outbound.py               # SQS Lambda for outbound sends
├── stack.py                  # cdk/lib/adapters/slack-adapter-stack.ts
├── signing.py                # Slack request signature verification
├── native.py                 # workspaces/channels/DMs native-sub-surface queries
└── tests/
    ├── test_signing.py
    ├── test_normalize.py
    ├── test_oauth.py
    ├── test_adapter.py
    └── fixtures/
        ├── event_dm.json
        ├── event_channel_mention.json
        ├── event_channel_noise.json         # bot is present but NOT addressed
        └── oauth_callback.json

adapters/telegram/
├── manifest.toml
├── adapter.py                # TelegramAdapter(ChannelAdapter)
├── normalize.py              # Telegram Update → UnifiedMessage
├── ingest.py                 # API Gateway Lambda for /webhooks/telegram/{token_hash}
├── outbound.py               # SQS Lambda for outbound sends
├── stack.py                  # cdk/lib/adapters/telegram-adapter-stack.ts
├── bot_client.py             # thin Telegram Bot API HTTP client (requests lib)
├── native.py                 # chats native-sub-surface queries
└── tests/

core/api/
├── slack_native_handler.py   # /v1/agents/{id}/slack/* route dispatcher
├── telegram_native_handler.py # /v1/agents/{id}/telegram/* route dispatcher
```

---

## Task 1: Slack — signing verification + OAuth flow

**Pre-read:** Slack docs on Events API signing (https://api.slack.com/authentication/verifying-requests-from-slack) and OAuth v2 (https://api.slack.com/authentication/oauth-v2).

### Task 1a: `adapters/slack/signing.py`
- Function `verify_slack_request(signing_secret, timestamp, body, signature) -> bool`.
- Rejects timestamps older than 5 minutes (replay protection).
- HMAC-SHA256 over `v0:{timestamp}:{body}`.
- **Commit:** `feat(phase3): slack request signing verification`

### Task 1b: OAuth start and callback
- `SlackAdapter.bridge_start(agent, config={"return_url": ...})` returns `BridgeStart(oauth_url, state)`. State is a signed nonce containing `org_id`+`agent_id`+`expires_at` — stored in a short-lived DynamoDB item (`PK=OAUTH#{state}`) with 10-min TTL.
- `adapters/slack/oauth.py` handler for `GET /webhooks/slack/oauth/callback?code=...&state=...`: exchange code via `oauth.v2.access`, store workspace credentials (bot token, team_id, bot_user_id) in SSM at `/agentcomms/{env}/adapters/slack/workspaces/{team_id}` (SecureString), update the Channel record to `active` with `config={team_id, bot_user_id}`.
- **Commit:** `feat(phase3): slack OAuth bridge flow with state validation + SSM credential storage`

### Task 1c: `SlackAdapter` contract — provision/teardown/health/ingest/send
- `provision()`: A-mode under Phase 3 is documented as "not supported in v0.1; use bridge mode." Raises `NotImplementedError` with a helpful message (preserving the spec's open-question #3 flag).
- `teardown(channel)`: revoke the bot token via `auth.revoke`, delete the SSM entry, no-op on Slack side.
- `health_check(channel)`: calls `auth.test` with stored token.
- `ingest(payload)`: parses Events API payload from Lambda input. Computes `is_dm`:
  - DM channel type (`D...`) → `is_dm=True`.
  - App mention event (`app_mention`) → `is_dm=True`.
  - Otherwise → `is_dm=False` (channel noise, accessible via native sub-surface).
  - `channel_native` keeps `{team_id, channel_id, ts, thread_ts, is_mention, blocks, event_type}`.
- `send(channel, message)`: `chat.postMessage`. If `message.to` is `"slack:T{team}:U{user}"`, call `conversations.open` first to get a DM channel, then post.
- Tests: event_dm fixture → `is_dm=True`, event_channel_noise fixture → `is_dm=False`, event_channel_mention → `is_dm=True`, send DM → 2 API calls (open+post), send to channel → 1 call.
- **Commit:** `feat(phase3): SlackAdapter — ingest, send, DM inference from event type`

### Task 1d: Native sub-surface `core/api/slack_native_handler.py`
Routes:
- `GET /v1/agents/{id}/slack/workspaces` — list Channels where `channel=slack`.
- `GET /v1/agents/{id}/slack/workspaces/{team_id}/channels` — `conversations.list` filtered to channels the bot is in.
- `GET /v1/agents/{id}/slack/workspaces/{team_id}/channels/{ch_id}/messages` — GSI4 query for non-DM messages + `conversations.history` backfill.
- `POST /v1/agents/{id}/slack/workspaces/{team_id}/channels/{ch_id}/messages` — `chat.postMessage` to that channel.
- `POST /v1/agents/{id}/slack/workspaces/{team_id}/users/{user_id}/messages` — `conversations.open` + `chat.postMessage`.

**Commit:** `feat(phase3): slack native sub-surface routes (workspaces, channels, DMs)`

---

## Task 2: Slack CDK stack

**File:** `cdk/lib/adapters/slack-adapter-stack.ts`

Creates:
- API Gateway routes on the existing AgentComms REST API: `POST /webhooks/slack/events`, `GET /webhooks/slack/oauth/callback`.
- Lambda for each route: `SlackEventsFn` → `adapters.slack.ingest.handler`, `SlackOAuthFn` → `adapters.slack.oauth.handler`.
- SQS queue `agentcomms-slack-outbound` + `SlackOutboundFn` → `adapters.slack.outbound.handler`.
- IAM: read access to `/agentcomms/{env}/adapters/slack/*` SSM parameters.
- Write access to `agentcomms` DynamoDB table and `agentcomms-events` Kinesis stream.

**Commit:** `feat(phase3): slack CDK stack (API Gateway webhooks, Lambdas, SQS)`

---

## Task 3: Telegram adapter — BotFather provision + webhook ingest + send

### Task 3a: `bot_client.py`
Tiny HTTP client for the Telegram Bot API using `requests`. Methods needed: `sendMessage`, `getMe`, `setWebhook`, `deleteWebhook`, `getChat`.
**Commit:** `feat(phase3): telegram Bot API client (thin requests wrapper)`

### Task 3b: `TelegramAdapter`
- `provision(agent, config={"bot_token": "..."})`:
  - Validates bot token via `getMe`.
  - Computes `token_hash = sha256(bot_token)` — the webhook URL path segment.
  - Calls `setWebhook` with URL `https://api.agentcomms.dev/webhooks/telegram/{token_hash}`.
  - Stores the bot token in SSM at `/agentcomms/{env}/adapters/telegram/tokens/{channel_id}` (SecureString).
  - Returns `channel_id` + `{bot_username, bot_user_id, token_hash}`.
- `teardown(channel)`: `deleteWebhook` + delete SSM entry.
- `health_check(channel)`: `getMe` with stored token.
- `ingest(payload)`: parses Telegram Update. DM inference:
  - `message.chat.type == "private"` → `is_dm=True`.
  - Group message mentioning the bot username or replying to a bot message → `is_dm=True`.
  - Otherwise → `is_dm=False`.
  - `channel_native` = `{chat_id, chat_type, update_id, entities, reply_to_message_id}`.
- `send(channel, message)`: `sendMessage`. If `message.to` is `"telegram:chat:{chat_id}"`, send to that chat. Supports `parse_mode=HTML` if `body_html` is provided.
- Tests: provision roundtrip, webhook URL includes token_hash, private chat → DM, group @mention → DM, group noise → not DM, send HTML formatting.
- **Commit:** `feat(phase3): TelegramAdapter — provision, webhook ingest, send`

### Task 3c: Native sub-surface `core/api/telegram_native_handler.py`
Routes:
- `GET /v1/agents/{id}/telegram/chats` — list Chat items the bot has seen (derived from `channel_native.chat_id` on past messages).
- `GET /v1/agents/{id}/telegram/chats/{chat_id}/messages` — GSI4 + filter where `channel_native.chat_id == {chat_id}`.
- `POST /v1/agents/{id}/telegram/chats/{chat_id}/messages`.
- **Commit:** `feat(phase3): telegram native sub-surface routes (chats)`

---

## Task 4: Telegram CDK stack

**File:** `cdk/lib/adapters/telegram-adapter-stack.ts`

Creates:
- API Gateway route `POST /webhooks/telegram/{token_hash}` with path-parameter validation.
- `TelegramIngestFn` → `adapters.telegram.ingest.handler`.
- SQS outbound queue + `TelegramOutboundFn`.
- IAM for SSM token parameters.

**Commit:** `feat(phase3): telegram CDK stack`

---

## Task 5: Unified inbox cross-channel integration test

**File:** `tests/e2e/test_cross_channel_inbox.py`

Scenario:
1. Create an agent with email, sms, slack (bridged to a mocked workspace), telegram.
2. Drop simulated inbound events for each channel: inbound email, inbound SMS, slack DM, telegram private message, slack channel noise (is_dm=False), telegram group noise (is_dm=False).
3. `GET /v1/agents/{id}/messages` → expect 4 messages (the 4 DMs), interleaved in descending timestamp order, NOT the 2 channel-noise items.
4. `GET /v1/agents/{id}/slack/workspaces/T123/channels/C456/messages` → expect the 1 slack noise item.
5. `GET /v1/agents/{id}/telegram/chats/-1234567/messages` → expect the 1 telegram noise item.

**Commit:** `test(phase3): cross-channel unified inbox + channel-native sub-surfaces`

---

## Task 6: Update one-shot provisioning to support new channels

**File:** modify `core/api/agents_handler.py` (`_provision_channels` function) to handle slack+telegram.

Ensure `POST /v1/agents { "provision": {"telegram": {"bot_token": "..."}}, "bridge": {"slack": {"return_url": "..."}}}` returns the expected mix of active + pending_oauth channels from Section 3.3 of the spec.

**Commit:** `feat(phase3): one-shot provisioning supports slack bridge + telegram provision`

---

## Task 7: Example adapter — scaffolded Discord

To validate the "copy telegram/ → adapters/discord/" narrative in Section 4.6 of the spec, scaffold `adapters/discord/` with only `manifest.toml` + stub `adapter.py` that raises `NotImplementedError`. This is **not** live — it's the template for a Phase 3.5 or community contribution.

**Commit:** `chore(phase3): scaffold adapters/discord/ as a template (not wired)`

---

## Phase 3 exit criteria

- [ ] All 5 v0.1 channels live: email, sms, push, slack, telegram
- [ ] Slack OAuth flow completes end-to-end against a real Slack app (staging)
- [ ] Telegram webhook receives real inbound messages from a real BotFather bot (staging)
- [ ] Unified inbox correctly shows cross-channel DMs only (cross-channel test passes)
- [ ] Channel-native sub-surfaces accessible for Slack workspaces/channels and Telegram chats
- [ ] No Phase 1 or Phase 2 tests regress
- [ ] `adapters/discord/` scaffold in place

---

*End Phase 3 plan. Estimated calendar: 3 weeks — Slack is more work than Telegram (OAuth, native surface with workspaces + channels + DMs, more test fixtures).*
