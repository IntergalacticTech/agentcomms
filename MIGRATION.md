# FreeMail → AgentComms Migration Guide

> **TL;DR:** Change your base URL from `api.victorymail.dev` to
> `api.agentcomms.dev`, rename `inb_` → `agt_` in agent/inbox IDs, and update
> your SDK package. Everything else is backward-compatible for 90 days via HTTP
> 301 redirects.

This document is the authoritative field-by-field diff between FreeMail (legacy)
and AgentComms (new). It covers endpoint changes, payload shape changes, SDK
method renames, webhook format changes, authentication, and common migration
errors with their fixes.

**Last updated:** 2026-04-17
**Applies to:** All FreeMail accounts migrating on or after the pivot cutover date.

---

## Table of Contents

1. [Quick-start checklist](#1-quick-start-checklist)
2. [Endpoint changes](#2-endpoint-changes)
3. [Payload shape changes](#3-payload-shape-changes)
4. [SDK changes](#4-sdk-changes)
5. [Webhook payload changes](#5-webhook-payload-changes)
6. [Authentication changes](#6-authentication-changes)
7. [Error code changes](#7-error-code-changes)
8. [Common migration errors and fixes](#8-common-migration-errors-and-fixes)
9. [Deprecated and retired endpoints](#9-deprecated-and-retired-endpoints)
10. [Rollout timeline](#10-rollout-timeline)

---

## 1. Quick-start checklist

```
[ ] Update SDK: pip install -U agentcomms  /  npm i @agentcomms/client@latest
[ ] Change base URL: api.victorymail.dev → api.agentcomms.dev
[ ] Rename inb_ → agt_ in any hardcoded ID prefixes
[ ] Replace inbox_id → agent_id in API calls
[ ] Update Inbox resource references to Agent (SDK method names changed)
[ ] Update webhook handlers: inbox_id field → agent_id
[ ] (Optional) Adopt unified message payload for multi-channel support
```

---

## 2. Endpoint changes

### 2.1 Base URL

| Legacy | New |
|--------|-----|
| `https://api.victorymail.dev` | `https://api.agentcomms.dev` |

The legacy URL returns HTTP **301 Moved Permanently** with a `Location` header
for 90 days after the pivot cutover. After that it returns **410 Gone**.

---

### 2.2 Agents (formerly Inboxes)

| Legacy endpoint | New endpoint | Notes |
|----------------|--------------|-------|
| `GET /v1/inboxes` | `GET /v1/agents` | Response field `inboxes` → `agents` |
| `POST /v1/inboxes` | `POST /v1/agents` | Request body unchanged except field names (see §3.1) |
| `GET /v1/inboxes/{inbox_id}` | `GET /v1/agents/{agent_id}` | ID prefix `inb_` → `agt_` |
| `PATCH /v1/inboxes/{inbox_id}` | `PATCH /v1/agents/{agent_id}` | Body field names changed (see §3.1) |
| `DELETE /v1/inboxes/{inbox_id}` | `DELETE /v1/agents/{agent_id}` | Behaviour unchanged |

**ID prefix mapping:**

The numeric/random suffix is preserved. Only the prefix changes.

```
inb_abc123xyz  →  agt_abc123xyz
inb_00000001   →  agt_00000001
```

> **Important:** If your code constructs IDs manually (e.g. `"inb_" + someId`),
> update to `"agt_" + someId`. IDs received from the API do not need manual
> transformation — the redirect handles them for 90 days.

---

### 2.3 Messages

| Legacy endpoint | New endpoint | Notes |
|----------------|--------------|-------|
| `GET /v1/inboxes/{inbox_id}/messages` | `GET /v1/agents/{agent_id}/messages` | See §3.2 for payload diff |
| `GET /v1/inboxes/{inbox_id}/messages/{message_id}` | `GET /v1/agents/{agent_id}/messages/{message_id}` | — |
| `POST /v1/inboxes/{inbox_id}/send` | `POST /v1/agents/{agent_id}/messages` | Method unchanged (POST). See §3.2 |
| `DELETE /v1/inboxes/{inbox_id}/messages/{message_id}` | `DELETE /v1/agents/{agent_id}/messages/{message_id}` | — |

---

### 2.4 Threads

| Legacy endpoint | New endpoint | Notes |
|----------------|--------------|-------|
| `GET /v1/inboxes/{inbox_id}/threads` | `GET /v1/agents/{agent_id}/threads` | — |
| `GET /v1/inboxes/{inbox_id}/threads/{thread_id}` | `GET /v1/agents/{agent_id}/threads/{thread_id}` | — |

---

### 2.5 Wait / OTP

| Legacy endpoint | New endpoint | Notes |
|----------------|--------------|-------|
| `POST /v1/inboxes/{inbox_id}/wait` | `POST /v1/agents/{agent_id}/wait` | Timeout param unchanged |
| `POST /v1/inboxes/{inbox_id}/extract-otp` | `POST /v1/agents/{agent_id}/extract-otp` | — |

---

### 2.6 Webhooks

| Legacy endpoint | New endpoint | Notes |
|----------------|--------------|-------|
| `GET /v1/inboxes/{inbox_id}/webhooks` | `GET /v1/agents/{agent_id}/webhooks` | — |
| `POST /v1/inboxes/{inbox_id}/webhooks` | `POST /v1/agents/{agent_id}/webhooks` | Body unchanged |
| `DELETE /v1/inboxes/{inbox_id}/webhooks/{webhook_id}` | `DELETE /v1/agents/{agent_id}/webhooks/{webhook_id}` | — |

---

### 2.7 Drafts

| Legacy endpoint | New endpoint | Notes |
|----------------|--------------|-------|
| `GET /v1/inboxes/{inbox_id}/drafts` | `GET /v1/agents/{agent_id}/drafts` | — |
| `POST /v1/inboxes/{inbox_id}/drafts` | `POST /v1/agents/{agent_id}/drafts` | — |
| `PUT /v1/inboxes/{inbox_id}/drafts/{draft_id}` | `PUT /v1/agents/{agent_id}/drafts/{draft_id}` | — |
| `DELETE /v1/inboxes/{inbox_id}/drafts/{draft_id}` | `DELETE /v1/agents/{agent_id}/drafts/{draft_id}` | — |

---

### 2.8 Domains

| Legacy endpoint | New endpoint | Notes |
|----------------|--------------|-------|
| `GET /v1/domains` | `GET /v1/domains` | **Unchanged.** |
| `POST /v1/domains` | `POST /v1/domains` | **Unchanged.** |
| `GET /v1/domains/{domain_id}` | `GET /v1/domains/{domain_id}` | **Unchanged.** |
| `DELETE /v1/domains/{domain_id}` | `DELETE /v1/domains/{domain_id}` | **Unchanged.** |

Domains are org-scoped in both versions; no migration required.

---

### 2.9 New AgentComms-only endpoints

These endpoints are new in AgentComms and have no legacy equivalent.

| New endpoint | Description |
|-------------|-------------|
| `GET /v1/agents/{agent_id}/channels` | List channels attached to an agent |
| `POST /v1/agents/{agent_id}/channels` | Attach a channel (SMS, Slack, Telegram, etc.) |
| `GET /v1/agents/{agent_id}/channels/{channel_id}` | Get channel details |
| `DELETE /v1/agents/{agent_id}/channels/{channel_id}` | Remove a channel |
| `GET /v1/agents/{agent_id}/ai/extract` | AI extraction (previously `/v1/ai/extract`) |
| `POST /v1/agents/{agent_id}/ai/classify` | AI classification (previously `/v1/ai/classify`) |
| `GET /v1/personas` | List agent personas |
| `POST /v1/personas` | Create a persona |
| `GET /v1/vault/{agent_id}` | Retrieve secrets vault for an agent |
| `PUT /v1/vault/{agent_id}` | Store secrets |

---

## 3. Payload shape changes

### 3.1 Agent (formerly Inbox)

**GET /v1/inboxes → GET /v1/agents response**

```jsonc
// Legacy: Inbox object
{
  "inbox_id": "inb_abc123",
  "org_id": "org_xyz",
  "address": "bot@yourdomain.com",
  "display_name": "My Bot",
  "domain_id": "dom_01",
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}

// New: Agent object
{
  "agent_id": "agt_abc123",        // inb_ → agt_ prefix
  "org_id": "org_xyz",
  "display_name": "My Bot",
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z",
  // address and domain_id moved to Channel object:
  "channels": [
    {
      "channel_id": "chan_em_abc123",
      "channel_type": "email",
      "address": "bot@yourdomain.com",
      "domain_id": "dom_01",
      "status": "active"
    }
  ]
}
```

**Field mapping:**

| Legacy field | New field | Notes |
|-------------|-----------|-------|
| `inbox_id` | `agent_id` | Prefix `inb_` → `agt_` |
| `address` | `channels[0].address` | Moved to Channel sub-object |
| `domain_id` | `channels[0].domain_id` | Moved to Channel sub-object |
| `display_name` | `display_name` | Unchanged |
| `org_id` | `org_id` | Unchanged |
| `created_at` | `created_at` | Unchanged |
| `updated_at` | `updated_at` | Unchanged |

**POST /v1/agents (create agent) request body:**

```jsonc
// Legacy: POST /v1/inboxes
{
  "address": "bot@yourdomain.com",
  "display_name": "My Bot",
  "domain_id": "dom_01"
}

// New: POST /v1/agents
{
  "display_name": "My Bot",
  // address and domain_id are set by attaching an email channel:
  // POST /v1/agents/{agent_id}/channels
  // { "channel_type": "email", "address": "bot@yourdomain.com", "domain_id": "dom_01" }
}
```

> **Migration tip:** If you create agents in code, you now make two calls: one to
> create the agent, one to attach an email channel. The SDK handles this with a
> single `agents.create(display_name=..., email_address=..., domain_id=...)` call
> that wraps both.

---

### 3.2 Message (formerly Message, now UnifiedMessage)

**GET /v1/agents/{agent_id}/messages/{id} response**

```jsonc
// Legacy: Message object
{
  "message_id": "msg_xyz",
  "inbox_id": "inb_abc123",
  "org_id": "org_xyz",
  "direction": "inbound",
  "status": "received",
  "subject": "Hello",
  "body_text": "Plain text body",
  "body_html": "<p>HTML body</p>",
  "from_address": "alice@example.com",
  "to_addresses": ["bot@yourdomain.com"],
  "thread_id": "thr_01",
  "ses_message_id": "<abc@us-east-1.amazonses.com>",
  "in_reply_to": null,
  "references": [],
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}

// New: UnifiedMessage object
{
  "message_id": "msg_xyz",
  "agent_id": "agt_abc123",          // inbox_id → agent_id
  "org_id": "org_xyz",
  "channel_id": "chan_em_abc123",    // NEW: which channel received/sent this
  "channel_type": "email",          // NEW: "email" | "sms" | "slack" | "telegram"
  "direction": "inbound",
  "status": "received",
  "subject": "Hello",               // null for non-email channels
  "body_text": "Plain text body",
  "body_html": "<p>HTML body</p>",   // null for non-email channels
  "from_address": "alice@example.com",
  "to_addresses": ["bot@yourdomain.com"],
  "thread_id": "thr_01",
  "ses_message_id": "<abc@us-east-1.amazonses.com>",
  "in_reply_to": null,
  "references": [],
  "metadata": {},                    // NEW: channel-specific metadata
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

**Field mapping:**

| Legacy field | New field | Notes |
|-------------|-----------|-------|
| `inbox_id` | `agent_id` | Prefix `inb_` → `agt_` |
| *(absent)* | `channel_id` | New field; always present |
| *(absent)* | `channel_type` | New field; `"email"` for all migrated messages |
| *(absent)* | `metadata` | New field; empty object for email |
| All other fields | Same name | Unchanged |

---

### 3.3 Send message request body (formerly `/send`, now `POST /messages`)

```jsonc
// Legacy: POST /v1/inboxes/{inbox_id}/send
{
  "to": "alice@example.com",
  "subject": "Hello",
  "body_text": "Plain text",
  "body_html": "<p>HTML</p>",
  "reply_to_message_id": "msg_xyz"   // optional, for threading
}

// New: POST /v1/agents/{agent_id}/messages
{
  "to": "alice@example.com",
  "subject": "Hello",
  "body_text": "Plain text",
  "body_html": "<p>HTML</p>",
  "in_reply_to_message_id": "msg_xyz",  // renamed from reply_to_message_id
  "channel_type": "email"               // optional; defaults to "email"
}
```

**Field mapping:**

| Legacy field | New field | Notes |
|-------------|-----------|-------|
| `reply_to_message_id` | `in_reply_to_message_id` | Renamed |
| *(absent)* | `channel_type` | Optional; defaults to `"email"` |
| All other fields | Same name | Unchanged |

---

### 3.4 Thread

Thread objects are unchanged. The `inbox_id` field in thread metadata is
replaced by `agent_id`, but threads fetched via the new endpoint
(`/v1/agents/{agent_id}/threads`) never surface `inbox_id`.

---

### 3.5 Webhook

Webhook registration request body is unchanged. Only the registration endpoint
has moved (see §2.6).

---

## 4. SDK changes

### 4.1 Python SDK

**Install:**
```bash
# Old
pip install freemail

# New
pip install agentcomms
```

**Import:**
```python
# Old
from freemail import FreemailClient
from freemail.models import Inbox, Message

# New
from agentcomms import AgentCommsClient
from agentcomms.models import Agent, UnifiedMessage
```

**Client instantiation:**
```python
# Old
client = FreemailClient(api_key="fm_live_...")

# New
client = AgentCommsClient(api_key="ak_live_...")
# Note: existing fm_live_ keys continue to work; the key prefix is cosmetic
```

**Method name changes:**

| Legacy method | New method | Notes |
|--------------|------------|-------|
| `client.inboxes.list()` | `client.agents.list()` | Returns `Agent` objects |
| `client.inboxes.create(address=..., domain_id=...)` | `client.agents.create(display_name=..., email_address=..., domain_id=...)` | SDK creates agent + channel in one call |
| `client.inboxes.get(inbox_id)` | `client.agents.get(agent_id)` | — |
| `client.inboxes.update(inbox_id, ...)` | `client.agents.update(agent_id, ...)` | — |
| `client.inboxes.delete(inbox_id)` | `client.agents.delete(agent_id)` | — |
| `client.inboxes.send(inbox_id, to=..., subject=..., body_text=...)` | `client.agents.send(agent_id, to=..., subject=..., body_text=...)` | Identical call shape |
| `client.inboxes.wait(inbox_id, timeout=60)` | `client.agents.wait(agent_id, timeout=60)` | — |
| `client.inboxes.extract_otp(inbox_id)` | `client.agents.extract_otp(agent_id)` | — |
| `client.inboxes.messages.list(inbox_id)` | `client.agents.messages.list(agent_id)` | — |
| `client.inboxes.messages.get(inbox_id, message_id)` | `client.agents.messages.get(agent_id, message_id)` | — |
| `client.inboxes.webhooks.list(inbox_id)` | `client.agents.webhooks.list(agent_id)` | — |
| `client.inboxes.webhooks.create(inbox_id, url=...)` | `client.agents.webhooks.create(agent_id, url=...)` | — |

**Backward-compatibility shim:**

The `freemail` package (0.x) now imports from `agentcomms` and emits a
deprecation warning. The `FreemailClient` class is aliased to `AgentCommsClient`.
The `Inbox` model is aliased to `Agent`. You can continue using the old package
for up to 90 days — it will work but emit warnings to `stderr`.

---

### 4.2 Node.js SDK

**Install:**
```bash
# Old
npm install @freemail/client

# New
npm install @agentcomms/client
```

**Import:**
```typescript
// Old
import { FreemailClient } from '@freemail/client';
import { Inbox, Message } from '@freemail/client/types';

// New
import { AgentCommsClient } from '@agentcomms/client';
import { Agent, UnifiedMessage } from '@agentcomms/client/types';
```

**Method name changes (Node):**

| Legacy method | New method | Notes |
|--------------|------------|-------|
| `client.inboxes.list()` | `client.agents.list()` | — |
| `client.inboxes.create({ address, domainId })` | `client.agents.create({ displayName, emailAddress, domainId })` | — |
| `client.inboxes.get(inboxId)` | `client.agents.get(agentId)` | — |
| `client.inboxes.update(inboxId, patch)` | `client.agents.update(agentId, patch)` | — |
| `client.inboxes.delete(inboxId)` | `client.agents.delete(agentId)` | — |
| `client.inboxes.send(inboxId, { to, subject, bodyText })` | `client.agents.send(agentId, { to, subject, bodyText })` | — |
| `client.inboxes.wait(inboxId, { timeout })` | `client.agents.wait(agentId, { timeout })` | — |
| `client.inboxes.extractOtp(inboxId)` | `client.agents.extractOtp(agentId)` | — |
| `client.inboxes.messages.list(inboxId)` | `client.agents.messages.list(agentId)` | — |
| `client.inboxes.webhooks.create(inboxId, opts)` | `client.agents.webhooks.create(agentId, opts)` | — |

**Type renames:**

| Legacy type | New type |
|------------|----------|
| `Inbox` | `Agent` |
| `Message` | `UnifiedMessage` |
| `CreateInboxRequest` | `CreateAgentRequest` |
| `SendMessageRequest` | `SendMessageRequest` | *(unchanged)* |

---

## 5. Webhook payload changes

### 5.1 `message.received` event

```jsonc
// Legacy webhook payload
{
  "event": "message.received",
  "inbox_id": "inb_abc123",
  "org_id": "org_xyz",
  "message": {
    "message_id": "msg_xyz",
    "inbox_id": "inb_abc123",
    "direction": "inbound",
    "subject": "Hello",
    "body_text": "...",
    "from_address": "alice@example.com",
    "to_addresses": ["bot@yourdomain.com"],
    "created_at": "2026-01-01T00:00:00Z"
  },
  "timestamp": "2026-01-01T00:00:00Z"
}

// New webhook payload
{
  "event": "message.received",
  "agent_id": "agt_abc123",         // inbox_id → agent_id
  "org_id": "org_xyz",
  "message": {
    "message_id": "msg_xyz",
    "agent_id": "agt_abc123",       // inbox_id → agent_id
    "channel_id": "chan_em_abc123", // NEW
    "channel_type": "email",        // NEW
    "direction": "inbound",
    "subject": "Hello",
    "body_text": "...",
    "from_address": "alice@example.com",
    "to_addresses": ["bot@yourdomain.com"],
    "metadata": {},                 // NEW
    "created_at": "2026-01-01T00:00:00Z"
  },
  "timestamp": "2026-01-01T00:00:00Z"
}
```

**Summary of webhook payload field changes:**

| Legacy field | New field | Location |
|-------------|-----------|----------|
| `inbox_id` | `agent_id` | Top-level |
| `message.inbox_id` | `message.agent_id` | Nested |
| *(absent)* | `message.channel_id` | Nested |
| *(absent)* | `message.channel_type` | Nested |
| *(absent)* | `message.metadata` | Nested |

---

### 5.2 `message.sent` event

Same changes as `message.received` above — `inbox_id` → `agent_id`, plus new
`channel_id`, `channel_type`, `metadata` fields.

---

### 5.3 New webhook events (AgentComms only)

| Event | Description |
|-------|-------------|
| `channel.connected` | A new channel was attached to an agent |
| `channel.disconnected` | A channel was removed from an agent |
| `sms.received` | SMS message received on an SMS channel |
| `sms.sent` | SMS message sent |
| `push.delivered` | Push notification delivered |

---

### 5.4 Webhook verification

Webhook signatures are computed identically (HMAC-SHA256 of the raw body with
your webhook secret). No changes to verification logic.

---

## 6. Authentication changes

### 6.1 API key format

| Legacy | New | Notes |
|--------|-----|-------|
| `fm_live_...` prefix | `ak_live_...` prefix | Existing `fm_live_` keys continue to work; the prefix is cosmetic |
| `fm_test_...` prefix | `ak_test_...` prefix | Same — old keys still work |

**Header — unchanged:**
```
Authorization: Bearer fm_live_abc...
Authorization: Bearer ak_live_abc...
# Both work
```

### 6.2 Scopes

API key scopes are unchanged:
- `org` — full organisation access
- `inbox:{inbox_id}` / `agent:{agent_id}` — scoped to a single agent

Existing `inbox:{inb_xxx}` scoped keys are automatically valid for
`agent:{agt_xxx}` — the authoriser maps the legacy scope prefix.

---

## 7. Error code changes

Most error codes are unchanged. The following have been updated:

| Legacy error code | New error code | When returned |
|------------------|----------------|---------------|
| `inbox_not_found` | `agent_not_found` | 404 on agent operations |
| `inbox_limit_exceeded` | `agent_limit_exceeded` | 429 on agent creation |
| `pod_not_found` | *(removed)* | Pods are retired; endpoint returns 410 |

HTTP status codes for all existing errors are unchanged.

---

## 8. Common migration errors and fixes

### 8.1 `404 Not Found` on `/v1/inboxes/...` after 90-day sunset

**Symptom:** `HTTP 404` or `HTTP 410` from `api.victorymail.dev`

**Cause:** The 90-day redirect window has expired.

**Fix:**
1. Update your base URL to `https://api.agentcomms.dev`
2. Update `inb_` → `agt_` in any hardcoded inbox IDs
3. Install the new SDK: `pip install -U agentcomms` or `npm i @agentcomms/client@latest`

---

### 8.2 `410 Gone` on `/v1/pods/*`

**Symptom:** `HTTP 410 Gone` with body `"The /v1/pods endpoint has been retired"`

**Cause:** The Pods feature was retired as part of the AgentComms pivot.
Pods no longer have a direct equivalent in the new model.

**Fix:** Refactor pod-based workflows to use Agents directly. If you were using
pods to group inboxes, use the new Agent model — each agent is independently
addressable and supports multiple channels.

---

### 8.3 `410 Gone` on `/v1/ai/*`

**Symptom:** `HTTP 410 Gone` with body `"AI endpoints are now scoped to agents"`

**Cause:** Top-level `/v1/ai` endpoints were moved to be agent-scoped.

**Fix:**
```
/v1/ai/extract   →   /v1/agents/{agent_id}/ai/extract
/v1/ai/classify  →   /v1/agents/{agent_id}/ai/classify
```

---

### 8.4 Webhook handler receiving `inbox_id` = `null`

**Symptom:** Webhook payload arrives; `inbox_id` field is absent or null.

**Cause:** Your webhook handler is reading `inbox_id` from the new payload
where the field is now `agent_id`.

**Fix:**
```python
# Old handler
inbox_id = payload["inbox_id"]

# New handler (both old and new webhooks)
agent_id = payload.get("agent_id") or payload.get("inbox_id")
```

---

### 8.5 SDK `AttributeError: 'FreemailClient' object has no attribute 'inboxes'`

**Symptom:** After upgrading the SDK, old `client.inboxes` calls raise
`AttributeError`.

**Cause:** You imported `AgentCommsClient` but kept old code.

**Fix:**
```python
# If you upgraded to agentcomms but kept old method calls:
client.agents.list()          # not client.inboxes.list()
client.agents.get(agent_id)   # not client.inboxes.get(inbox_id)
# etc.

# Or: keep using the freemail package during transition — it's a shim:
from freemail import FreemailClient   # emits DeprecationWarning but works
```

---

### 8.6 `401 Unauthorized` after API key rotation

**Symptom:** After rotating to a new `ak_live_...` key, requests return 401.

**Cause:** The new SDK sends `Bearer ak_live_...` but your process may still
have an old key cached in the environment or secret manager.

**Fix:** Ensure `AGENTCOMMS_API_KEY` is set to the new key value and restart
the process that reads it.

---

### 8.7 `message.agent_id` is the old `inb_` format in webhook payload

**Symptom:** Webhook `message.agent_id` has value `inb_abc123` instead of
`agt_abc123`.

**Cause:** Webhook was registered before the migration and your handler is
receiving events from the legacy processing path.

**Fix:** After cutover, re-register webhooks via the new endpoint to ensure
they run on the AgentComms path. The `agent_id` in payloads from newly
registered webhooks will always use the `agt_` prefix.

---

### 8.8 `POST /v1/inboxes/{id}/send` returning 405 Method Not Allowed

**Symptom:** `HTTP 405` when posting to the legacy send endpoint.

**Cause:** The `/send` sub-resource no longer exists. Sending is now `POST
/v1/agents/{agent_id}/messages`.

**Fix:**
```
POST /v1/inboxes/{inbox_id}/send
  →
POST /v1/agents/{agent_id}/messages
```

The request body is identical except for the `reply_to_message_id` rename
(see §3.3).

---

## 9. Deprecated and retired endpoints

### 9.1 Deprecated (301 for 90 days, then 410)

All `/v1/inboxes/*` endpoints.

### 9.2 Retired (410 immediately, no redirect)

| Endpoint | Reason | Replacement |
|----------|--------|-------------|
| `GET /v1/pods` | Pods feature retired | None — use Agents directly |
| `GET /v1/pods/{id}` | Pods feature retired | None |
| `POST /v1/pods` | Pods feature retired | None |
| `DELETE /v1/pods/{id}` | Pods feature retired | None |
| `GET /v1/ai/extract` | Moved to agent scope | `GET /v1/agents/{id}/ai/extract` |
| `POST /v1/ai/classify` | Moved to agent scope | `POST /v1/agents/{id}/ai/classify` |
| `POST /v1/ai/generate` | Moved to agent scope | `POST /v1/agents/{id}/ai/generate` |

---

## 10. Rollout timeline

| Date | Event |
|------|-------|
| `<CUTOVER_DATE - 10d>` | Customer announcement email sent |
| `<CUTOVER_DATE>` | Cutover: `api.agentcomms.dev` is live and canonical |
| `<CUTOVER_DATE>` | `api.victorymail.dev` begins returning HTTP 301 redirects |
| `<CUTOVER_DATE + 90d>` | `api.victorymail.dev` switches from 301 to 410 Gone |
| `<CUTOVER_DATE + 97d>` | Old victorymail API Gateway stacks decommissioned |
| `<CUTOVER_DATE + 90d>` | `freemail` PyPI / npm packages marked deprecated |

**SDK package sunset timeline:**

| Package | Status | Retirement |
|---------|--------|------------|
| `freemail` (PyPI) | Redirects to `agentcomms` via shim | `<CUTOVER_DATE + 90d>` |
| `@freemail/client` (npm) | Redirects to `@agentcomms/client` via shim | `<CUTOVER_DATE + 90d>` |
| `agentcomms` (PyPI) | Active, supported | — |
| `@agentcomms/client` (npm) | Active, supported | — |

---

## Getting help

- **Migration guide:** This document and [docs.agentcomms.dev/migration](https://docs.agentcomms.dev/migration)
- **API reference:** [docs.agentcomms.dev/api](https://docs.agentcomms.dev/api)
- **Support:** support@agentcomms.dev
- **Community:** [community.agentcomms.dev](https://community.agentcomms.dev)
- **Book a migration call:** `<CALENDLY_LINK>`
