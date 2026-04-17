# AgentComms — Pivot Design Spec

**Status:** Draft for approval
**Date:** 2026-04-17
**Authors:** John Cunningham + Claude (brainstorming session)
**Supersedes:** FreeMail / VictoryMail current architecture for all forward work
**Successor documents:** Implementation plan (to be produced by `superpowers:writing-plans`)

---

## 0. Context and strategic framing

### The market shift

The "email for AI agents" category is commoditizing faster than anticipated. Cloudflare ships free agent email. AgentMail.to continues to execute. A growing cohort of lightweight competitors offers similar narrow-scope inbox APIs. The pivot thesis is that narrow email-only positioning is no longer a defensible wedge.

### The pivot

Reposition from **"API-first email platform for AI agents"** to **the hub service for all agent communication** — email, SMS, Slack, Telegram, Discord, WhatsApp, mobile push, and eventually postal mail, fax, and voice — plus the identity-layer primitives (agents, personas, secret vault) these channels serve.

### Why this is actually a small leap

The current FreeMail repo already contains partially-built:
- `lambdas/sms/` + `lambdas/sms_processor/` — AWS End User Messaging for SMS
- `lambdas/vault/` — TOTP and secret vault
- `lambdas/personas/` — identity personas
- `lambdas/push/` — SNS Mobile Push

The current `docs/roadmap.md` already contains the line *"FreeMail is evolving from 'email for AI agents' to the complete identity and communications layer for AI agents."* This spec formalizes and accelerates that direction.

### The differentiator Cloudflare cannot replicate

AgentComms is an open-source, AWS-native, multi-channel hub where **the user's own coding agent can deploy the system end-to-end into the user's own AWS account in ~20 minutes, unattended**. Cloudflare cannot put their infrastructure in your cloud. Most alternatives cannot either. This self-deploy story is the headline differentiator in all marketing.

### Summary of locked decisions

| Decision | Choice |
|---|---|
| Identity model per channel | **Hybrid** — A-mode (provision) or B-mode (bridge via OAuth) per channel |
| Primary abstraction | **Agent-centric unified inbox**, DMs + mentions only; channel-native surfaces separate |
| License | **FSL-1.1-Apache-2.0** (source-available, per-file Apache 2.0 after 2 years) |
| v0.1 scope | Email + SMS + Push + Slack + Telegram + adapter SDK |
| Name & domain | **AgentComms** / `agentcomms.dev` |
| Self-deploy promise | `agentcomms bootstrap` runnable by a coding agent, <25 min to working hub |
| Feature gating | **None** (FSL precludes it); hosted tiers are usage/quota/operational-value only |

---

## 1. Product & architecture overview

### 1.1 What AgentComms is

AgentComms is a source-available hub that gives AI agents a first-class identity across every channel humans and other agents use. When a developer spins up a new agent, one API call provisions that agent an email address, a phone number for SMS, a Slack bot identity, a Telegram bot, and a push notification target — all routing into a single unified inbox the agent reads from.

- **Canonical hosted service:** `agentcomms.dev`, run by Victory on AWS account 732770059798, us-east-1 initially. Victory is the only party licensed to sell it as a hosted service.
- **Anyone can:** pull the code, self-host, modify, use for personal or internal-company purposes, offer it free.
- **Nobody else can:** operate AgentComms as a paid hosted service competing with `agentcomms.dev`.
- **Primary object:** `Agent`. Everything else is scoped under an agent.
- **Primary surface:** `agent.messages` — DMs and @mentions from every channel merged into one timeline. Channel-native activity lives under `agent.slack.*`, `agent.discord.*`, etc.

### 1.2 Hybrid identity model

Per channel, the deployer picks:
- **A-mode (Provision):** the hub creates the agent's identity on the channel. Email address at a platform domain, phone number via AWS End User Messaging, Telegram bot registered with BotFather, push SNS Platform Application + Platform Endpoints managed by the hub. (Push is inherently asymmetric — the "address" is a per-device endpoint registered through the hub; there's no meaningful B-mode for push.)
- **B-mode (Bridge):** the hub connects to the user's existing account. Slack OAuth into the user's workspace; Discord bot added to the user's guild; WhatsApp Business Account linked to the user's Meta business.

Channels with no natural "existing account" for the agent to bridge to (email, SMS, postal, fax, voice) are A-only. Chat platforms (Slack, Discord, Telegram, WhatsApp) support both; the user picks per deployment.

### 1.3 Unified inbox semantics (X1)

A single `Agent` has one unified inbox. The unified inbox contains **only direct-addressed messages**: emails to the agent's address, SMS to its number, Slack DMs, Slack channel messages that @mention the bot, Telegram DMs, Telegram group @mentions, Discord DMs, Discord guild @mentions, push notifications delivered to the agent.

Non-DM channel activity (Slack workspace channel chatter, Discord guild traffic the bot is merely present for, Telegram group traffic the bot is silently in) is accessible via **channel-native sub-surfaces** (`agent.slack.workspaces.{id}.channels.{id}.messages`) but does not pollute the unified inbox.

**Cross-channel thread fusion is explicitly not attempted at the data layer.** If a user emails the agent and then follows up on Slack, those stay as two separate threads. The agent's reasoning layer can decide they're conceptually the same conversation.

### 1.4 High-level architecture

```
    ┌─── SDKs / MCP / REST clients ───┐
    │                                 │
    ▼                                 ▼
 ┌──────────────────────────────────────┐
 │   API Gateway + Lambda (Hub API)     │
 └──────┬───────────────┬──────────┬────┘
        │               │          │
  ┌─────▼─────┐    ┌────▼────┐  ┌──▼──────────────┐
  │ DynamoDB  │    │ Kinesis │  │ Channel Adapter  │
  │ single    │    │ events  │  │ Runtime (Lambda) │
  │ table     │    │         │  └──┬────┬────┬───┬─┘
  └───────────┘    └────┬────┘     │    │    │   │
                        │         SES  SMS  Slack Telegram
                   ┌────┴────┐   (email)(AWS)(OAuth)(bot)
                   │ Webhook │               │        │
                   │  + WS   │               │        │
                   │ fan-out │           workspace  Telegram
                   └─────────┘            OAuth      Bot API
```

### 1.5 Core design commitments

1. **All channels normalize to one `UnifiedMessage` shape** in DynamoDB with a `channel` discriminator and an opaque `channel_native` blob for channel-specific fields. This is the unification point for the X1 inbox.
2. **Adapters are plugins.** Each channel is a self-contained module implementing a `ChannelAdapter` contract. The hub doesn't know Slack-isms; the Slack adapter does.
3. **Kinesis is the single event bus**, partitioned by `agent_id`, so webhooks and WebSocket subscribers see a coherent per-agent stream regardless of channel.
4. **AWS-native where AWS has a service** (SES, End User Messaging v2, SNS Mobile Push, Bedrock). Vendor-native where AWS doesn't (Slack/Discord/Telegram adapters call their APIs directly from Lambda — no non-AWS infra introduced).
5. **No proprietary server-side code.** Everything in the hosted service is also in the repo. Differentiators are operational: AWS production settings, SES reputation, commercial support, managed scaling, and being the only legally-sellable hosted instance.
6. **One-command agent-deployable on AWS.** A coding agent with AWS credentials and a domain can clone the repo and have a working AgentComms instance running in its user's AWS account end-to-end, unattended, in ~20 minutes. The repo's root-level `AGENT.md` is written for coding agents; the `agentcomms bootstrap` CLI emits machine-parseable NDJSON status; every phase is idempotent; every failure has a recognition pattern and an exit code.

The **canonical hosted `agentcomms.dev` is deployed from the exact same CDK app the public uses,** parameterized by config. There is no separate "prod" codepath. The only things Victory has that self-hosters don't are (a) the production AWS account, (b) the platform domain pool, (c) the Stripe account, (d) SES production quota and reputation, and (e) the legal right to sell it hosted.

---

## 2. Data model and the `UnifiedMessage` shape

### 2.1 Entity hierarchy

```
Organization (tenant boundary, 1-to-1 with a hosted account or 1-per-install self-hosted)
 └── Agent                                 ← primary object
      ├── ApiKey[]                          ← scoped to the agent
      ├── Channel[]                         ← one per (channel_type × mode) pairing
      │    ├── email ── address, domain, DKIM tokens, status
      │    ├── sms ──── E.164 number, 10DLC brand/campaign state
      │    ├── slack ── workspace OAuth grant, bot_user_id
      │    ├── telegram ── bot_username, token_ref
      │    ├── discord ── application_id, bot_id
      │    └── push ──── SNS platform app + endpoint ARNs
      ├── Webhook[]                         ← per-channel or all-channel
      └── Message[]                         ← unified across channels
Domain (org-scoped; email adapter specific; unchanged from current)
```

`Pod` and `Inbox` from the current FreeMail model are retired. `Inbox` was a channel-specific concept; its closest counterpart is `Channel`. `Pod` was an organizational grouping that never pulled its weight — grouping is handled via agent metadata tags.

### 2.2 DynamoDB single-table schema (table: `agentcomms`)

| Entity | PK | SK | Notes |
|---|---|---|---|
| Organization | `ORG#{org_id}` | `META` | plan, quotas, settings |
| Agent | `ORG#{org_id}` | `AGT#{agent_id}` | name, metadata, created_at |
| API Key | `ORG#{org_id}` | `APIKEY#{key_hash}` | scope: org/agent/channel, tier |
| Channel | `AGT#{agent_id}` | `CHAN#{channel}#{channel_id}` | mode, status, channel-native config |
| **Message** | `AGT#{agent_id}` | `MSG#{timestamp_ms}#{msg_id}` | **all channels, interleaved by time** |
| Thread | `AGT#{agent_id}` | `THR#{channel}#{native_thread_id}` | per-channel; no cross-channel fusion |
| Draft | `AGT#{agent_id}` | `DRF#{channel}#{draft_id}` | per-channel |
| Webhook | `AGT#{agent_id}` | `WHK#{webhook_id}` | channel filter, event filter |
| Domain | `ORG#{org_id}` | `DOM#{domain_id}` | email adapter scoped |
| Attachment | `MSG#{msg_id}` | `ATT#{att_id}` | S3-backed |

**Critical design move:** all channels write messages under `PK=AGT#{agent_id}`. A single `Query(PK=AGT#{agent_id}, SK begins_with MSG#)` returns a chronologically-ordered stream of everything — the unified inbox is literally one query.

### 2.3 Global Secondary Indexes

| GSI | PK | SK | Purpose |
|---|---|---|---|
| GSI1 | `APIKEY#{key_hash}` | `ORG#{org_id}` | Auth hot path |
| GSI2 | `ADDR#{channel}#{address}` | `CHAN#{channel_id}` | **Inbound routing:** email address, phone number, Slack user ID, Telegram chat_id → channel → agent |
| GSI3 | `AGT_DM#{agent_id}` (sparse) | `MSG#{ts}#{msg_id}` | **Unified inbox for X1 — only items with `is_dm=true` project here.** Non-DM channel traffic physically cannot appear. |
| GSI4 | `CHAN#{channel_id}` | `MSG#{ts}#{msg_id}` | Channel-native listings |
| GSI5 | `THR#{thread_key}` | `MSG#{ts}#{msg_id}` | Thread listing |
| GSI6 | `EXTID#{channel}#{external_id}` | `MSG#{msg_id}` | Idempotency + external-ID cross-ref |
| GSI7 | `DOMAIN#{domain_name}` | `ORG#{org_id}` | Domain ownership |

### 2.4 `UnifiedMessage` item shape

```json
{
  "PK": "AGT#agt_01H...",
  "SK": "MSG#1744906800000#msg_01H...",
  "message_id": "msg_01H...",
  "agent_id": "agt_01H...",
  "org_id":   "org_01H...",
  "channel_id": "chan_01H...",
  "channel":    "email | sms | slack | discord | telegram | push",
  "direction":  "inbound | outbound",
  "status":     "received | queued | sent | delivered | bounced | failed | rejected",

  "from": { "address": "alice@example.com", "display_name": "Alice", "platform_user_id": "U123" },
  "to":   [ { "address": "agent@agentcomms.dev", "display_name": "MyAgent", "platform_user_id": "U456" } ],
  "subject":    "…",
  "body_text":  "…",
  "body_html":  "…",
  "body_s3_key": "org/…/msg/…/body",
  "attachments": [ { "attachment_id", "filename", "content_type", "size", "s3_key" } ],

  "thread_key": "thr_01H...",
  "is_dm":      true,
  "received_at": "2026-04-17T14:30:00Z",

  "channel_native": {
    // email:    { "message_id_header": "<...>", "in_reply_to": "<...>", "references": ["<...>"],
    //             "spf_pass": true, "dkim_pass": true, "dmarc_pass": true }
    // slack:    { "team_id": "T...", "channel_id": "C...", "ts": "1744906800.000100",
    //             "is_mention": true, "blocks": [...] }
    // discord:  { "guild_id": "...", "channel_id": "...", "message_reference": {...} }
    // telegram: { "chat_id": 123, "update_id": 456, "entities": [...] }
    // sms:      { "message_segments": 2, "carrier_id": "..." }
    // push:     { "platform": "apns|fcm", "endpoint_arn": "..." }
  },

  "gsi2_pk": "ADDR#email#agent@agentcomms.dev",
  "gsi3_pk": "AGT_DM#agt_01H...",
  "gsi4_pk": "CHAN#chan_01H...",
  "gsi5_pk": "THR#thr_01H...",
  "gsi6_pk": "EXTID#slack#T123:1744906800.000100",

  "created_at": "…",
  "updated_at": "…"
}
```

**Design rationale for `channel_native`:** pretending Slack Block Kit and email HTML are the same thing is how you end up with a lossy API nobody wants to use. The hub normalizes *enough* for the unified feed (sender, recipient, text, direction, thread, timestamp, `is_dm`), and preserves native fidelity in an opaque blob that channel-specific SDKs can decode.

### 2.5 S3 storage layout

- `agentcomms-raw-inbound/{org_id}/{agent_id}/{channel}/{msg_id}` — raw vendor payloads (MIME for email, SQS body for SMS, webhook JSON for Slack/Discord/Telegram)
- `agentcomms-bodies/{org_id}/{msg_id}/body.{txt|html}` — large bodies (>4KB)
- `agentcomms-attachments/{org_id}/{msg_id}/{att_id}/{filename}` — attachments

Lifecycle policies follow the current FreeMail tiering (Standard → IA → Glacier), configurable per org.

### 2.6 Threading semantics

Per-channel, populated by the adapter:
- **Email:** RFC In-Reply-To / References chain.
- **Slack:** `thread_ts` → `thread_key`.
- **Discord:** `message_reference.message_id` → `thread_key`.
- **Telegram:** `reply_to_message_id` → `thread_key`.
- **SMS, push:** no native threading; one message = one thread.
- **Cross-channel fusion NOT attempted.** Timeline interleaving in the unified inbox is the user-visible fusion.

---

## 3. Agent-facing REST API surface

### 3.1 Design principles

1. **Agent-scoped URLs.** Every channel operation lives under `/v1/agents/{agent_id}/…`. No top-level `/v1/messages` or `/v1/slack`.
2. **One-shot provision.** `POST /v1/agents` can create the agent AND set up N channels in a single call.
3. **Unified inbox is the default view; channel-native surfaces are explicit.**
4. **Channel paths mirror that channel's native model.** Slack → workspaces/channels; Discord → guilds/channels; Telegram → chats.
5. **"auto" channel on send.** `POST /v1/agents/{id}/messages` with `{to, body}` infers the channel from the `to` format. Explicit override via `channel: "sms"`.

### 3.2 Full endpoint surface

```
# Org (tenant boundary — mostly hosted-only surface)
POST   /v1/signup
GET    /v1/org
GET    /v1/org/usage
POST   /v1/api-keys               { scope: org|agent_id|channel_id, name }
GET    /v1/api-keys
DELETE /v1/api-keys/{id}

# Agents — the primary surface
POST   /v1/agents                 # one-shot create + provision + bridge
GET    /v1/agents
GET    /v1/agents/{id}
PATCH  /v1/agents/{id}
DELETE /v1/agents/{id}
POST   /v1/agents/{id}/provision  # add channels to an existing agent

# Unified inbox (X1)
GET    /v1/agents/{id}/messages
GET    /v1/agents/{id}/messages/{msg_id}
POST   /v1/agents/{id}/messages              # send; channel: "auto" | explicit
POST   /v1/agents/{id}/messages/{msg_id}/reply
POST   /v1/agents/{id}/messages/{msg_id}/read
POST   /v1/agents/{id}/wait
POST   /v1/agents/{id}/extract-otp

# Threads, drafts, webhooks
GET    /v1/agents/{id}/threads
GET    /v1/agents/{id}/threads/{thread_id}
GET    /v1/agents/{id}/drafts                POST /…  PATCH /…/{id}  DELETE /…/{id}
GET    /v1/agents/{id}/webhooks              POST /…  PATCH /…/{id}  DELETE /…/{id}

# Channels — generic CRUD
GET    /v1/agents/{id}/channels
POST   /v1/agents/{id}/channels
GET    /v1/agents/{id}/channels/{channel_id}
PATCH  /v1/agents/{id}/channels/{channel_id}
DELETE /v1/agents/{id}/channels/{channel_id}

# Channel-native sub-surfaces (NON-DM activity)
# Email
GET  /v1/agents/{id}/email/messages/{msg_id}/raw
POST /v1/agents/{id}/email/messages/{msg_id}/forward
# Slack
GET  /v1/agents/{id}/slack/workspaces
GET  /v1/agents/{id}/slack/workspaces/{team_id}/channels
GET  /v1/agents/{id}/slack/workspaces/{team_id}/channels/{ch_id}/messages
POST /v1/agents/{id}/slack/workspaces/{team_id}/channels/{ch_id}/messages
POST /v1/agents/{id}/slack/workspaces/{team_id}/users/{user_id}/messages
# Discord
GET  /v1/agents/{id}/discord/guilds
GET  /v1/agents/{id}/discord/guilds/{g_id}/channels
GET  /v1/agents/{id}/discord/guilds/{g_id}/channels/{ch_id}/messages
POST /v1/agents/{id}/discord/guilds/{g_id}/channels/{ch_id}/messages
POST /v1/agents/{id}/discord/users/{user_id}/messages
# Telegram
GET  /v1/agents/{id}/telegram/chats
GET  /v1/agents/{id}/telegram/chats/{chat_id}/messages
POST /v1/agents/{id}/telegram/chats/{chat_id}/messages
# Push
POST /v1/agents/{id}/push/devices
POST /v1/agents/{id}/push/send

# Org-scoped resources (not agent-scoped)
GET/POST/DELETE /v1/domains/{…}
GET/POST/DELETE /v1/vault/{…}
GET/POST/DELETE /v1/personas/{…}

# AI (available to all; metered on hosted, uses deployer's Bedrock on self-host)
POST /v1/agents/{id}/ai/categorize
POST /v1/agents/{id}/ai/extract
POST /v1/agents/{id}/ai/summarize
POST /v1/agents/{id}/ai/search
```

### 3.3 One-shot provisioning call

```http
POST /v1/agents
{
  "name": "InvoiceBot",
  "metadata": { "customer": "acme" },
  "provision": {
    "email":    { "local_part": "invoice-bot", "domain": "agentcomms.dev" },
    "sms":      { "country": "US" },
    "push":     true,
    "telegram": true
  },
  "bridge": {
    "slack": { "return_url": "https://app.example.com/callback" }
  }
}

→ 201 Created
{
  "agent_id":  "agt_01HXYZ...",
  "api_key":   "ak_live_…",
  "channels": [
    { "channel": "email",    "channel_id": "chan_em_…", "status": "active",
      "details": { "address": "invoice-bot@agentcomms.dev", "dkim_verified": true } },
    { "channel": "sms",      "channel_id": "chan_sm_…", "status": "provisioning",
      "details": { "phone_e164": "+15551234567", "ten_dlc_status": "pending_brand_registration" } },
    { "channel": "push",     "channel_id": "chan_ps_…", "status": "active",
      "details": { "platform_application_arns": { "apns": "arn:…", "fcm": "arn:…" } } },
    { "channel": "telegram", "channel_id": "chan_tg_…", "status": "active",
      "details": { "bot_username": "InvoiceBot_0xyz_bot" } },
    { "channel": "slack",    "channel_id": "chan_sl_…", "status": "pending_oauth",
      "details": { "oauth_url": "https://slack.com/oauth/v2/authorize?client_id=…&state=…" } }
  ]
}
```

A coding agent handling this response sees exactly what's immediately usable and what requires a human's next action (click the Slack link, wait for 10DLC brand registration).

The returned `api_key` is an agent-scoped key auto-created at agent-creation time — a convenience for the one-call flow. Separate keys at broader (org) or narrower (single-channel) scopes are created via `POST /v1/api-keys`.

### 3.4 Unified inbox query

```http
GET /v1/agents/agt_01HXYZ/messages?since=2026-04-17T00:00:00Z&channels=email,slack,sms&limit=50

→ 200 OK
{
  "messages": [
    {
      "message_id": "msg_01H…",
      "channel": "email",
      "direction": "inbound",
      "is_dm": true,
      "from": { "address": "alice@example.com" },
      "subject": "March invoice",
      "body_text": "…",
      "thread_key": "thr_01H…",
      "received_at": "2026-04-17T09:12:03Z",
      "channel_native": { "message_id_header": "<…>", "dmarc_pass": true }
    },
    {
      "message_id": "msg_01H…",
      "channel": "slack",
      "direction": "inbound",
      "is_dm": true,
      "from": { "platform_user_id": "U123", "address": "slack:T456:U123" },
      "body_text": "hey did you see the email?",
      "thread_key": "thr_01H…",
      "received_at": "2026-04-17T09:14:17Z",
      "channel_native": { "team_id": "T456", "channel_id": "D789", "ts": "…" }
    }
  ],
  "next_cursor": "eyJ…"
}
```

`is_dm=true` is enforced by GSI3 — non-DM traffic physically cannot appear.

### 3.5 Send with channel inference

```http
POST /v1/agents/agt_01HXYZ/messages
{
  "to": "alice@example.com",             # format inferred: email
  "body": "Here's the updated invoice."
}

# Slack DM
POST … { "to": "slack:T456:U123", "body": "same thing on slack" }

# SMS
POST … { "to": "+15551234567",    "body": "same thing on sms" }

# Explicit
POST … { "channel": "email", "to": { "address": "alice@example.com" }, "body_text": "…" }
```

The address-format router is implemented in `core/router/` (not in any adapter). Uses a strict regex table. Fails loud on ambiguous input rather than guessing.

### 3.6 Webhooks

```http
POST /v1/agents/agt_01HXYZ/webhooks
{
  "url": "https://example.com/hook",
  "events": ["message.received", "message.delivered", "channel.status_changed"],
  "channels": ["*"],            # or ["email","slack"]
  "secret": "…"
}
```

All events use the normalized `UnifiedMessage` shape. No webhook ever delivers a vendor-native payload that looks fundamentally different from another channel's. Channel fidelity stays in `channel_native`.

---

## 4. Channel Adapter SDK contract

### 4.1 The `ChannelAdapter` Python interface

```python
# core/adapters/base.py

from abc import ABC, abstractmethod
from typing import Literal
from pydantic import BaseModel

class Agent(BaseModel):             agent_id: str; org_id: str; name: str; metadata: dict
class Channel(BaseModel):           channel_id: str; channel: str; agent_id: str; mode: str; config: dict; status: str
class IngestPayload(BaseModel):     source: str; headers: dict; body: bytes | dict; path_params: dict
class UnifiedMessage(BaseModel):    ...  # shape from Section 2
class OutboundMessage(BaseModel):   to: str | dict; body_text: str; body_html: str | None = None; attachments: list = []; thread_key: str | None = None; channel_native_overrides: dict = {}
class SendResult(BaseModel):        channel_native_id: str; status: str; error: str | None = None
class NativeContainer(BaseModel):   id: str; name: str; type: str; metadata: dict
class ProvisionResult(BaseModel):   status: str; channel_id: str; details: dict
class BridgeStart(BaseModel):       oauth_url: str; state: str; instructions: str
class BridgeResult(BaseModel):      status: str; channel_id: str; details: dict
class HealthStatus(BaseModel):      ok: bool; last_success_at: str; error: str | None = None


class ChannelAdapter(ABC):
    """Every channel adapter implements this."""

    channel_name: str
    supports_modes: list[Literal["provision", "bridge"]]

    # ── Lifecycle ─────────────────────────────────────────────────
    @abstractmethod
    def provision(self, *, agent: Agent, config: dict) -> ProvisionResult: ...

    def bridge_start(self, *, agent: Agent, config: dict) -> BridgeStart:
        raise NotImplementedError(f"{self.channel_name} does not support bridge mode")

    def bridge_complete(self, *, channel: Channel, callback_params: dict) -> BridgeResult:
        raise NotImplementedError

    @abstractmethod
    def teardown(self, *, channel: Channel) -> None: ...

    @abstractmethod
    def health_check(self, *, channel: Channel) -> HealthStatus: ...

    # ── Messaging ─────────────────────────────────────────────────
    @abstractmethod
    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None:
        """Inbound. MUST:
          1. Verify signature / authenticity
          2. Parse vendor payload
          3. Resolve target channel via GSI2
          4. Compute `is_dm` honestly (true ONLY for DMs and explicit mentions)
          5. Populate `channel_native`
          6. Normalize body into body_text (always) and body_html (optional)
          7. Resolve/assign thread_key
        Return None to drop."""

    @abstractmethod
    def send(self, *, channel: Channel, message: OutboundMessage) -> SendResult:
        """Outbound. Adapter renders body to channel-native format and calls vendor API."""

    # ── Native sub-surfaces (optional) ────────────────────────────
    def list_native_containers(self, *, channel: Channel) -> list[NativeContainer]:
        return []

    def list_native_messages(self, *, channel: Channel, container_id: str, **filters) -> list[UnifiedMessage]:
        return []

    def send_to_native_target(self, *, channel: Channel, target: dict, message: OutboundMessage) -> SendResult:
        return self.send(channel=channel, message=message)

    # ── CDK wiring (deploy time) ──────────────────────────────────
    def cdk_wiring(self, *, stack, context) -> None:
        """Adapter creates its own AWS resources: SES receipt rules, SNS topics,
        API Gateway webhook routes, Lambda functions, IAM grants.
        Hub core never hardcodes a channel's AWS resources."""
```

### 4.2 What is NOT in an adapter's concerns

- **Storage.** The hub core writes the `UnifiedMessage` to DynamoDB, uploads bodies/attachments to S3, populates GSIs.
- **Event publishing.** The hub core publishes to Kinesis after persistence.
- **Auth for the REST API.** API keys, authorizer, scope checks — all hub core.
- **Rate limiting at the API edge.** Hub core.
- **Webhook delivery to customers.** Hub core.

### 4.3 Adapter registration

Monorepo adapters live under `adapters/{name}/` with a `manifest.toml`:

```toml
# adapters/slack/manifest.toml
[adapter]
channel = "slack"
class = "adapters.slack.adapter:SlackAdapter"
modes = ["bridge"]
cdk_stack = "adapters.slack.stack:SlackStack"
min_hub_version = "0.1"

[webhook_routes]
slack_events = { path = "/webhooks/slack/events", method = "POST" }
slack_oauth  = { path = "/webhooks/slack/oauth/callback", method = "GET" }

[ssm_secrets]
signing_secret = "SECURE"
client_id      = "PLAIN"
client_secret  = "SECURE"
```

At boot, `core/adapters/registry.py` scans `adapters/*/manifest.toml`, dynamically imports each adapter class, and registers it. Third-party adapters register via Python `entry_points`:

```toml
# third-party-adapter/pyproject.toml
[project.entry-points."agentcomms.adapters"]
discord = "agentcomms_discord.adapter:DiscordAdapter"
```

### 4.4 Inbound routing (every adapter follows this pattern)

```
vendor event → API Gateway /webhooks/{channel}  OR  SNS → Lambda
                            │
                            ▼
                  Lambda ingest_fn
                            │
                            ▼
                  adapter.ingest(payload)
                            │
                            ▼
                  UnifiedMessage | None
                            │
                            ▼
                  core.persist_and_publish():
                    - write to DynamoDB
                    - upload body/attachments to S3
                    - publish to Kinesis (partition key: agent_id)
                    - trigger webhook fan-out + WS dispatch
```

### 4.5 Uniform adapter directory layout

```
adapters/<channel>/
├── manifest.toml          # registration metadata
├── adapter.py             # ChannelAdapter subclass (public interface)
├── stack.py               # CDK stack fragment (cdk_wiring target)
├── ingest.py              # Lambda handler for inbound events
├── outbound.py            # Lambda handler / helper for async sends
├── oauth.py               # (bridge-mode only)
├── normalize.py           # vendor payload → UnifiedMessage
├── tests/                 # round-trip normalize+send test with recorded fixtures
└── README.md              # adapter-specific setup, credentials, limits
```

### 4.6 Adding a new channel

1. Copy `adapters/telegram/` to `adapters/{new_channel}/`.
2. Edit `manifest.toml` (channel name, webhook routes, modes).
3. Implement five required methods in `adapter.py`: `provision`, `teardown`, `health_check`, `ingest`, `send`.
4. Implement `list_native_containers` / `list_native_messages` if the channel has a hierarchy (workspaces, guilds, chats).
5. Wire signature verification in `normalize.py`.
6. `cdk deploy` picks up the new manifest automatically.

No core changes required.

---

## 5. OSS repo layout, bootstrap CLI, license mechanics

### 5.1 Repo layout

```
agentcomms/
├── LICENSE                           # FSL-1.1-Apache-2.0
├── LICENSE.commercial                # template for commercial hosted-use license
├── NOTICE                            # third-party attributions
├── README.md                         # landing-page mirror; first-read for humans
├── AGENT.md                          # ⭐ deployment guide for coding agents
├── CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md  CHANGELOG.md  MIGRATION.md
├── pyproject.toml                    # Python workspace root
├── package.json                      # TS workspace root (CDK, console, CLI, Node SDK)
│
├── core/                             # Python; hub-generic, channel-agnostic
│   ├── api/                          # Lambda handlers for /v1/agents/* routes
│   ├── data/                         # DynamoDB single-table models (Pydantic v2)
│   ├── events/                       # Kinesis publish, webhook fan-out, WS dispatch
│   ├── router/                       # address-format → channel inference
│   ├── auth/                         # authorizer Lambda, API key model
│   ├── ai/                           # Bedrock wrappers
│   ├── adapters/
│   │   ├── base.py                   # ChannelAdapter ABC
│   │   └── registry.py               # scans manifest.toml + entry_points
│   └── tests/
│
├── adapters/
│   ├── email/      ├── sms/          ├── push/
│   ├── slack/      └── telegram/
│
├── cdk/
│   ├── bin/app.ts
│   └── lib/
│       ├── config.ts
│       └── stacks/
│           ├── data-stack.ts
│           ├── api-stack.ts
│           ├── events-stack.ts
│           ├── adapters-stack.ts     # iterates adapters/*/manifest.toml, calls cdk_wiring
│           ├── bootstrap-stack.ts
│           └── observability-stack.ts
│
├── cli/                              # `agentcomms` CLI (TypeScript)
│   └── src/commands/
│       ├── bootstrap.ts  status.ts  doctor.ts
│       ├── channels.ts   keys.ts    agents.ts  destroy.ts
│
├── console/                          # React + Vite admin UI
├── sdks/
│   ├── python/                       # `agentcomms` Python SDK
│   └── node/                         # `@agentcomms/client`
├── mcp/                              # MCP server
│
├── docs/
│   ├── index.md  quickstart.md  self-host.md → AGENT.md
│   ├── api-reference.md  openapi.yaml  architecture.md
│   ├── licensing.md
│   ├── adapters/
│   │   ├── email.md sms.md slack.md telegram.md push.md
│   └── concepts/
│
├── examples/
│   ├── coding-agent-self-deploys/
│   ├── invoicing-agent/
│   └── slack-standup-bot/
│
└── .github/workflows/
    ├── test.yml
    ├── deploy-hosted.yml             # Victory-only; no-op on forks
    └── publish-sdks.yml
```

### 5.2 `AGENT.md` — deployment guide for coding agents

Root-level. Written for coding agents (Claude Code, Cursor, Aider, Codex) rather than humans. Structured so an agent can read it top-to-bottom and act without human clarification.

**Sections:**
1. **TL;DR (3 lines).**
2. **Preconditions to verify before starting.** AWS credentials present; account ID; region has SES inbound (us-east-1 / us-west-2 / eu-west-1); Route 53 hosted zone exists; Node 20+ / Python 3.12+ / AWS CLI v2 / CDK v2 installed.
3. **Exact command sequence** with required env vars and expected NDJSON status lines.
4. **Exit-code contract:**
   - `0` = success
   - `1` = preflight failure (read `status` array, fix, retry)
   - `2` = AWS deploy failure (retriable after manual check)
   - `3` = SES verification timeout (DNS propagation)
   - `4` = smoke-test failure (deployment succeeded but round-trip didn't — needs human)
5. **Top-10 common failures** with grep patterns and one-line fixes.
6. **How to enable each channel after bootstrap.**
7. **Teardown.** `agentcomms destroy --yes` with a precise list of what it does and doesn't delete.

### 5.3 `agentcomms` CLI surface

```
agentcomms bootstrap
  --domain DOMAIN                   # required
  --region REGION                   # default us-east-1
  --admin-email EMAIL               # required
  --account ACCOUNT_ID              # optional; validated
  --profile PROFILE                 # optional
  --skip-channels CH1,CH2           # bootstrap deploys core + these channels omitted
  --non-interactive                 # required when invoked by a coding agent
  --json                            # NDJSON on stdout

agentcomms doctor
agentcomms status
agentcomms channels list
agentcomms channels enable <channel>
agentcomms channels disable <channel>
agentcomms keys create|list|revoke
agentcomms agents create|list|delete
agentcomms destroy
agentcomms version
```

### 5.4 Bootstrap phases (NDJSON-emitting)

1. **Preflight** — AWS creds, account, region, Route 53 zone, SES sandbox-or-prod, IAM scan, tool versions.
2. **CDK bootstrap** — `npx cdk bootstrap` if not already.
3. **Deploy** — `npx cdk deploy --all --require-approval never --context config=…`.
4. **SES identity + DKIM** — create Easy DKIM identity, write DKIM/SPF/DMARC into Route 53, poll until SUCCESS (15-min timeout).
5. **Seed** — first Org, first admin API key (stored in SSM, echoed once).
6. **Smoke test** — create test agent, send real email to `--admin-email`, wait for delivery confirmation.
7. **Report** — NDJSON final line with api_url, console_url, admin_email, admin_api_key, next-steps.

Example status stream:
```ndjson
{"phase":"preflight","status":"ok","msg":"Route 53 zone Z123 found for acmebot.com"}
{"phase":"deploy","status":"running","stack":"DataStack","progress":0.3}
{"phase":"ses","status":"waiting","msg":"DKIM verification pending (1 of 3)"}
{"phase":"done","status":"ok","api_url":"https://api.acmebot.com","api_key":"ak_live_..."}
```

### 5.5 SSM Parameter Store layout

```
/agentcomms/{env}/core/
  jwt_secret                         (SecureString)
  bootstrap_admin_key                (SecureString, revoke after first login)

/agentcomms/{env}/adapters/{channel}/{key}
  /agentcomms/prod/adapters/slack/signing_secret           (SecureString)
  /agentcomms/prod/adapters/slack/client_id                (String)
  /agentcomms/prod/adapters/slack/client_secret            (SecureString)
  /agentcomms/prod/adapters/telegram/bot_token             (SecureString)
  /agentcomms/prod/adapters/sms/end_user_messaging_arn     (String)
  /agentcomms/prod/adapters/sms/ten_dlc_brand_id           (String)
```

Every adapter's `manifest.toml` declares which SSM keys it needs. `agentcomms channels enable <channel>` walks the user/agent through populating them.

### 5.6 License mechanics

**`LICENSE` (FSL-1.1-Apache-2.0):**
- **Licensor:** Victory (exact legal entity name TBD; placeholder throughout repo until confirmed).
- **Software:** AgentComms.
- **Competing Use definition:** "any offering that is substantially similar to the Licensor's commercial hosted AgentComms service." Allowed: internal use, personal projects, running for your own agents, modifying freely, redistributing modifications under FSL, running in your own AWS account at any scale. Disallowed: hosting it as a paid service for third parties.
- **Change Date:** 2 years from the date of each commit (per-file).
- **Change License:** Apache 2.0.

**Per-file header:**
```
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
```

**`LICENSE.commercial`:** template Victory grants on request (email `commercial@agentcomms.dev`). Overrides the Competing Use clause under negotiated terms.

**What Victory can do that nobody else can:**
1. Operate `agentcomms.dev` as a paid hosted service.
2. Grant commercial licenses.
3. Relicense future code (new versions only; published FSL code stays FSL/Apache per its Change Date).

**`docs/licensing.md`:** plain-English explainer of what users can and cannot do, how to get a commercial license, when code becomes Apache 2.0.

---

## 6. Migration plan (FreeMail → AgentComms)

### 6.1 Approach

Clean-break migration with a dual-run window. Old victorymail/FreeMail API gets sunset on a ~90-day clock. No permanent compat-shim layer.

### 6.2 Resource mapping

| Current | Destination | Notes |
|---|---|---|
| `victorymail.dev` hosted service | `agentcomms.dev` hosted service | New CDK stacks, same AWS account (732770059798) |
| `api.victorymail.dev` | `api.agentcomms.dev` + 301 redirect during sunset | `Deprecation` / `Sunset` headers |
| `console.victorymail.dev` | `console.agentcomms.dev` | Rebuilt console; old URL redirects |
| `freemail` Python SDK | `agentcomms` Python SDK (v1.0.0) | Old package final release re-exports + `DeprecationWarning` |
| `@freemail/client` Node SDK | `@agentcomms/client` Node SDK (v1.0.0) | Same shim pattern |
| MCP server | Rebuilt against new API | New tool names |
| `victorymail` DynamoDB table | `agentcomms` DynamoDB table (new schema) | One-shot migration script, idempotent |
| `victorymail-raw-email` S3 | `agentcomms-raw-inbound` S3 | Copy during migration; old bucket → Glacier Deep → delete after 1 yr |
| `victorymail-bodies` S3 | `agentcomms-bodies` S3 | Same |
| `victorymail-attachments` S3 | `agentcomms-attachments` S3 | Same |
| SES identity `victorymail.dev` | **Kept** as platform domain-pool entry | Old addresses keep working through new hub |
| SES identities `karmascale.net` / `.org` | **Kept** as platform pool | No change |
| Stripe products | Rewired per Section 7 | Grandfathered 6 mo for existing paid |
| BYOC-with-license-server | **Retired**; replaced by `agentcomms bootstrap` | Redundant under FSL |
| AWS Marketplace BYOC listing | Replaced by SaaS Subscriptions for `agentcomms.dev` | Different product, v0.3 |
| `lambdas/sms/`, `lambdas/sms_processor/` | `adapters/sms/` | Port |
| `lambdas/vault/` | `core/api/vault/` | Port (org-scoped feature) |
| `lambdas/personas/` | `core/api/personas/` | Port (org-scoped, links to agents) |
| `lambdas/push/` | `adapters/push/` | Port |

### 6.3 Data migration script

`tools/migrate_victorymail_to_agentcomms.py` — one-shot Python, same AWS account, both tables. Idempotent via `attribute_not_exists` conditions.

```
For each Org in victorymail table:
  copy META item (schema identical)
  copy API Keys (unchanged structure)

For each Inbox in victorymail table:
  create Agent item:
    agent_id = "agt_" + inbox_id[4:]
    name = inbox.display_name or inbox.address
    metadata = { "migrated_from_inbox": inbox_id }
  create Channel item (channel="email", mode="provision"):
    channel_id = "chan_em_" + inbox_id[4:]
    details = { address, domain_id }
  (Pods dropped; metadata.pod = pod_id kept as tag)

For each Message:
  rewrite as UnifiedMessage:
    PK = "AGT#" + agent_id_for_inbox(msg.inbox_id)
    SK = "MSG#" + msg.created_ts_ms + "#" + msg.msg_id
    channel = "email"
    is_dm = true
    channel_native = { message_id_header, in_reply_to, references, spf, dkim, dmarc }
    thread_key = thr_ mapping from old thread_id
    all GSI fields populated

For each Thread / Domain / Webhook / Draft / List / Attachment:
  structural port.

Emit NDJSON progress + final counts + sample spot-check reads.
```

Estimated runtime at current scale: under 10 minutes.

### 6.4 Timeline

| Week | Milestone |
|---|---|
| 1 | New `agentcomms-*` CDK stacks deployed, parallel to `victorymail-*`. Empty table. |
| 2 | Dry-run data migration in staging; spot-check reads. |
| 3 | Production data migration (2-hour announced window). DNS cut: `api.agentcomms.dev` and `console.agentcomms.dev` authoritative. `api.victorymail.dev` begins returning 301s with `Sunset` / `Deprecation` headers. SDK v1.0 published. Final `freemail` / `@freemail/client` deprecation release. |
| 4 | Launch blog post + README + landing page. Repo goes public. |
| 4–12 | Dual-run. Old URL works (with warnings); new URL authoritative. |
| 13 (≈90 days) | `api.victorymail.dev` returns 410. Old SDK packages emit import-time error. Old `victorymail-*` stacks kept dark for one more month, then destroyed after final backup. |

### 6.5 API breaking changes (not shimmed)

- `inbox_id` → `agent_id` + `channel_id`.
- `pod_id` dropped; agents have `metadata.pod` tag instead.
- Webhook payload shape → `UnifiedMessage`.
- API key prefix `fm_` → `ak_live_` / `ak_test_`.

### 6.6 Customer communications

- **Personal email** to each current paying Stripe customer, ~10 days before Week-3 cutover:
  - Why the pivot; what changes for them
  - Stripe plan grandfathered at current price for 6 months; every paid feature on new platform + all new channels included at no extra charge during that window
  - New API docs, SDK package names, endpoint URLs
  - Offer: 30-min migration call with a Victory engineer
- **Blog post** at `agentcomms.dev/blog/pivot` at Week-3 cutover.
- **`MIGRATION.md`** at repo root with before/after diff for every endpoint + SDK call.
- **GitHub notice** on old `IntergalacticTech/FreeMail.ai` repo redirecting to `IntergalacticTech/agentcomms`.

### 6.7 What is NOT preserved

- No API-compat shim layer.
- No dual-SDK maintenance beyond the 90-day deprecation window.
- No `pod` abstraction.

### 6.8 Rollback

- Before Week 3 cutover: trivially reversible by keeping old stacks running and flipping DNS.
- Within 24 hours of Week 3: script is idempotent and additive; flip DNS back; any new agentcomms traffic in that window needs reverse-mirroring.
- After Week 4: non-reversible without data loss. Committed.

---

## 7. v0.1 scope + hosted-service pricing + launch artifacts

### 7.1 v0.1 deliverables

**Hub core:** DynamoDB single-table (new schema), API Gateway REST + WebSocket, authorizer, Kinesis event bus, webhook fan-out, WS dispatch, address-format router, wait / extract-otp (channel-agnostic), AI features (optional, deployer's Bedrock), vault (org-scoped), personas (org-scoped).

**Channels (5):**

| Channel | Modes | Scope in v0.1 | Deferred to v0.2+ |
|---|---|---|---|
| Email | Provision | SES send/receive, DKIM/SPF/DMARC, custom domains, attachments, MIME, threading, quoted-reply stripping | IMAP/SMTP bridges |
| SMS | Provision | AWS End User Messaging v2, 10DLC brand registration in bootstrap, inbound/outbound SMS, OTP extraction | Voice OTP fallback, non-US carrier registration |
| Push | Provision | SNS Mobile Push (APNs + FCM), device registration, send | Rich payload templates |
| Slack | Bridge (B) + limited Provision (A) | Events API webhook, OAuth install flow, DM + @mention → unified inbox, workspace/channel native surface, `chat.postMessage` | Socket Mode, Slack Connect, interactivity |
| Telegram | Provision (A) | Bot API webhook, DM and group @mention → unified inbox, chat native surface, `sendMessage` | Business API, payments, inline queries |

**Tooling:** `agentcomms` CLI, `AGENT.md`, bootstrap CLI with NDJSON, CDK app with config-driven deploy, `docs/adapters/{channel}.md`.

**Client libraries:** Python SDK v1.0.0, Node SDK v1.0.0, MCP server rebuilt, OpenAPI 3.1 spec regenerated.

**Web:** rebuilt console, landing page at `agentcomms.dev`, `docs.agentcomms.dev` Docusaurus site.

**Examples:** `coding-agent-self-deploys/`, `invoicing-agent/`, `slack-standup-bot/`.

### 7.2 Explicitly deferred

| Item | Why | Target |
|---|---|---|
| Discord adapter | Template-able from Telegram, 3–5 days | v0.2 (Week +2) |
| WhatsApp adapter | Meta Business onboarding ~2wk | v0.3 |
| Postal mail adapter | Lob/PostGrid integration ~1wk | v0.3 |
| Fax adapter | Phaxio/Twilio Fax ~1wk | v0.3 |
| Voice OTP | End User Messaging Voice | v0.2 |
| Semantic search | OpenSearch Serverless + embedding backfill | v0.3 |
| Multi-region | Active-passive eu-west-1 | v0.4 |
| Marketplace SaaS listing | Needs hosted tier model validation | v0.3 |
| SOC 2 | 6-mo audit window | v0.5 |

### 7.3 Hosted-service pricing

Under FSL there is zero code-level differentiator between hosted and self-hosted. Hosted customers pay for **operational value only:**
1. Managed AWS infra
2. Warmed SES reputation, dedicated IP pools
3. Platform domain pool (`@agentcomms.dev` addresses)
4. Pre-registered 10DLC brand for US SMS
5. Pre-registered Slack/Discord/Telegram OAuth apps
6. Uptime SLA + on-call
7. Commercial support

**Tiered quotas + metered overage:**

| Tier | $/mo | Agents | Email/mo | SMS/mo | Push/mo | Notes |
|---|---|---|---|---|---|---|
| Free | $0 | 3 | 1,000 | 100 | 10,000 | Shared SES IP, community support, BYO Slack/Telegram bot tokens |
| Developer | $19 | 10 | 10,000 | 1,000 | 100,000 | Hosted Slack/Telegram apps, community Discord + email support |
| Team | $99 | 100 | 100,000 | 10,000 | 1M | Shared dedicated SES IP, 99.5% SLA |
| Business | $499 | 1,000 | 1M | 100K | unlimited | Dedicated SES IP, dedicated 10DLC number, 99.9% SLA |
| Enterprise | Custom | custom | custom | custom | custom | SSO, audit, commercial license option |

**Metered overage (passthrough + 50% margin):**
- Email: $0.00015 / message
- SMS OTP (inbound): $0.01 / receive
- SMS (outbound): $0.015 / send
- Push: $0.0000004 / notification
- AI operations: $0.002 (Haiku-class) or $0.015 (Sonnet-class)

**Existing-customer migration under this pricing:**
- Free tier → new Free.
- Starter $5 → new Free with 6-mo Developer-tier complimentary credit.
- Pro $25 → new Developer tier at $19 price, grandfathered 6 months then normal.

### 7.4 AWS Marketplace (v0.3)

- **Retire** the old BYOC-with-license-server listing.
- **Publish** `agentcomms.dev` as a SaaS Subscription with Team/Business/Enterprise tiers. 3% Marketplace fee. Post-v0.1 after 8+ weeks of hosted-tier validation.

### 7.5 Launch communications

| When | Artifact | Audience |
|---|---|---|
| Week 3 | Private email to current paying customers | Existing Stripe |
| Week 3 | Repo public on GitHub | Everyone |
| Week 3 | Landing page live at `agentcomms.dev` | Everyone |
| Week 4 | Technical launch blog post | r/selfhosted, HN soft launch, LinkedIn |
| Week 4 | 3-min screencast: Claude Code reads AGENT.md and deploys AgentComms end-to-end | YouTube, X, HN |
| Week 5 | "Show HN: AgentComms — agent comms hub your coding agent deploys for you" | HN front page bid |
| Week 6 | Product Hunt launch | Product Hunt |
| Week 8 | First community adapter PR target | Dev-community health signal |
| Week 12 | `api.victorymail.dev` returns 410 | Existing customers |

### 7.6 Success criteria for v0.1

- A coding agent with AWS creds + a domain runs `agentcomms bootstrap` and reaches "working hub with all 5 channels operational" unattended, in ≤ 25 minutes, on a fresh AWS account, with >95% success rate (measured across 20 CI test runs).
- All 5 channels pass automated round-trip tests: provision → send → receive → extract → reply.
- All current-FreeMail functionality works on the new platform.
- Every current Stripe customer successfully migrated with zero data loss.
- OSS repo is clean enough that a developer not steeped in FreeMail can read it and contribute a new adapter in under 2 days.

---

## 8. Open questions (to resolve before implementation plan)

These do not block the spec but must be resolved during planning:

1. **Legal entity name** for the Licensor field in `LICENSE` and commercial license. Placeholder: "Victory". Needs exact legal name.
2. **SES account consolidation.** The `victorymail.dev` Route 53 zone lives in a separate AWS account (noted in `BUILD_PLAN.md`). Consolidating into 732770059798 or leaving as-is. Implementation plan must address.
3. **Slack A-mode (provision) scope.** Full A-mode means the hub creates a Slack app per agent (infeasible — requires manual Slack developer dashboard steps). "Limited A-mode" likely means: deployer creates one Slack app in their own Slack developer account, and agents provisioned on the hub become users in that app. The plan must specify.
4. **Admin user model on the hosted service.** Who administers `agentcomms.dev`? Same Cognito User Pool as today? Mapping existing FreeMail admin users to the new console?
5. **Non-FreeMail licenses in NOTICE.** Full audit of upstream dependency licenses before the FSL repo goes public.
6. **Rate limits at the hub-vendor boundary.** Per-vendor (SES 14/s; Slack tier limits; Telegram 30/s/chat). Each adapter needs a documented rate-limit plan.
7. **Outbound queue semantics.** Current `lambdas/outbound_worker/` uses SQS FIFO per-org. Preserve per-agent ordering guarantees? Or switch to per-channel queues?
8. **WebSocket authentication under the new scope model.** Current WS auth is by API key; new scope hierarchy (org/agent/channel) needs explicit rules.

---

*End of spec. Next step: `superpowers:writing-plans` to produce the phase-by-phase implementation plan from this spec.*
