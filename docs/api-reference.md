# REST API Reference

Base URL:

```text
https://api.agentcomms.dev/v1
```

Self-hosted deployments should use the API URL emitted by `agentcomms bootstrap`.

## Authentication

Send an API key with either header:

```bash
Authorization: Bearer ak_live_YOUR_KEY
```

```bash
x-api-key: ak_live_YOUR_KEY
```

API keys are hashed before storage. Key scopes are `org`, `agent`, and `channel`.

## Errors

Errors use JSON:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "agent not found"
  }
}
```

## Agents

| Method | Path | Description |
|---|---|---|
| `GET` | `/agents` | List agents |
| `POST` | `/agents` | Create an agent and optionally provision/bridge channels |
| `GET` | `/agents/{agent_id}` | Get one agent |
| `PUT` | `/agents/{agent_id}` | Update `name` and/or `metadata` |
| `DELETE` | `/agents/{agent_id}` | Delete an agent |
| `POST` | `/agents/{agent_id}/provision` | Provision additional channels |

Create:

```bash
curl -sS -X POST https://api.agentcomms.dev/v1/agents \
  -H "Authorization: Bearer ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "InvoiceBot",
    "metadata": {"owner": "finance"},
    "provision": {
      "email": {"local_part": "invoice", "domain": "example.com"},
      "telegram": {"bot_token": "..."}
    },
    "bridge": {
      "slack": {"return_url": "https://example.com/slack/callback"}
    }
  }'
```

Response:

```json
{
  "agent_id": "agt_...",
  "name": "InvoiceBot",
  "channels": [
    {
      "channel": "email",
      "channel_id": "chan_...",
      "status": "active",
      "details": {"address": "invoice@example.com"}
    }
  ]
}
```

## Channels

| Method | Path | Description |
|---|---|---|
| `GET` | `/agents/{agent_id}/channels` | List channels for an agent |
| `POST` | `/agents/{agent_id}/channels` | Provision or bridge a channel |
| `GET` | `/agents/{agent_id}/channels/{channel_id}` | Get channel details |
| `PATCH` | `/agents/{agent_id}/channels/{channel_id}` | Update channel `config` and/or `status` |
| `DELETE` | `/agents/{agent_id}/channels/{channel_id}` | Teardown and delete a channel |

Body:

```json
{
  "channel": "email",
  "mode": "provision",
  "config": {
    "local_part": "invoice",
    "domain": "example.com"
  }
}
```

Known channel values: `email`, `sms`, `push`, `slack`, `telegram`, `discord`, `whatsapp`, `postal`, `fax`, `voice`. External adapters may add any stable slug matching `[a-z][a-z0-9_-]{0,62}`, such as `matrix`, `smoke_signal`, or `alien-transmission`.

## Messages

| Method | Path | Description |
|---|---|---|
| `GET` | `/agents/{agent_id}/messages` | List unified inbox messages |
| `POST` | `/agents/{agent_id}/messages` | Send a message |
| `GET` | `/agents/{agent_id}/messages/{message_id}` | Get one message |
| `DELETE` | `/agents/{agent_id}/messages/{message_id}` | Delete one message |
| `POST` | `/agents/{agent_id}/messages/{message_id}/reply` | Reply using the original channel/thread context |
| `POST` | `/agents/{agent_id}/messages/{message_id}/read` | Mark a message as read |

List query parameters:

| Name | Description |
|---|---|
| `since` | ISO 8601 lower bound |
| `channels` | Comma-separated channel names |
| `limit` | Page size |
| `cursor` | Opaque pagination cursor |

Send body:

```json
{
  "to": "alice@example.com",
  "subject": "Status",
  "body": "Done.",
  "channel": "email",
  "thread_key": "thread_..."
}
```

`channel` is optional when the recipient address can be inferred.

Reply body:

```json
{
  "body": "Got it, processing.",
  "body_html": "<p>Got it, processing.</p>"
}
```

Message response shape:

```json
{
  "message_id": "msg_...",
  "agent_id": "agt_...",
  "channel_id": "chan_...",
  "channel": "email",
  "direction": "inbound",
  "status": "received",
  "from": {"address": "alice@example.com", "display_name": "Alice"},
  "to": [{"address": "invoice@example.com"}],
  "subject": "Question",
  "body_text": "Can you review this?",
  "thread_key": "thread_...",
  "is_dm": true,
  "labels": [],
  "received_at": "2026-08-29T18:00:00+00:00",
  "channel_native": {}
}
```

## Wait and OTP

| Method | Path | Description |
|---|---|---|
| `POST` | `/agents/{agent_id}/wait` | Long-poll for a matching message |
| `POST` | `/agents/{agent_id}/extract-otp` | Find a recent message and extract an OTP |

Wait body:

```json
{
  "timeout_sec": 25,
  "from": "noreply@example.com",
  "subject_contains": "verification",
  "channels": ["email", "sms"]
}
```

OTP body:

```json
{
  "max_age_sec": 300,
  "from": "noreply@example.com",
  "channels": ["email", "sms"]
}
```

Legacy aliases accepted by the handlers include `timeout`, `sender`, and a single `channel`.

## Threads and Drafts

| Method | Path | Description |
|---|---|---|
| `GET` | `/agents/{agent_id}/threads` | List threads |
| `GET` | `/agents/{agent_id}/threads/{thread_id}` | Get one thread |
| `GET` | `/agents/{agent_id}/drafts` | List drafts |
| `POST` | `/agents/{agent_id}/drafts` | Create a draft |
| `GET` | `/agents/{agent_id}/drafts/{draft_id}` | Get a draft |
| `PATCH` | `/agents/{agent_id}/drafts/{draft_id}` | Update a draft |
| `DELETE` | `/agents/{agent_id}/drafts/{draft_id}` | Delete a draft |

## Webhooks

| Method | Path | Description |
|---|---|---|
| `GET` | `/agents/{agent_id}/webhooks` | List webhooks |
| `POST` | `/agents/{agent_id}/webhooks` | Create a webhook |
| `GET` | `/agents/{agent_id}/webhooks/{webhook_id}` | Get one webhook |
| `PATCH` | `/agents/{agent_id}/webhooks/{webhook_id}` | Update a webhook |
| `DELETE` | `/agents/{agent_id}/webhooks/{webhook_id}` | Delete a webhook |

Create body:

```json
{
  "url": "https://example.com/hooks/agentcomms",
  "events": ["message.received", "message.sent"]
}
```

Webhook deliveries are signed with the webhook signing secret returned at creation time.

## API Keys

| Method | Path | Description |
|---|---|---|
| `GET` | `/api-keys` | List API keys for the org |
| `POST` | `/api-keys` | Create an API key |
| `DELETE` | `/api-keys/{key_id}` | Revoke an API key |

Create body:

```json
{
  "name": "invoice-agent",
  "scope": "agent",
  "agent_id": "agt_...",
  "expires_at": "2027-01-01T00:00:00+00:00"
}
```

Response includes the plaintext key exactly once:

```json
{
  "key_id": "key_...",
  "name": "invoice-agent",
  "scope": "agent",
  "agent_id": "agt_...",
  "channel_id": null,
  "key_prefix": "ak_live_...",
  "revoked": false,
  "expires_at": "2027-01-01T00:00:00+00:00",
  "created_at": "2026-08-29T18:00:00+00:00",
  "last_used_at": null,
  "key": "ak_live_..."
}
```

Only org-scoped callers can create, list, or revoke API keys. A caller cannot revoke the key currently authenticating the request.

## Vault

| Method | Path | Description |
|---|---|---|
| `GET` | `/vault` | List vault items |
| `POST` | `/vault` | Store a secret or TOTP seed |
| `GET` | `/vault/{vault_id}` | Get a vault item |
| `DELETE` | `/vault/{vault_id}` | Delete a vault item |
| `GET` | `/vault/{vault_id}/totp` | Generate the current TOTP code |

Create secret:

```json
{
  "label": "stripe_test_key",
  "type": "secret",
  "value": "sk_test_...",
  "tags": {"env": "dev"}
}
```

Create TOTP seed:

```json
{
  "label": "github_totp",
  "type": "totp",
  "seed": "JBSWY3DPEHPK3PXP"
}
```

## Personas and Domains

| Method | Path | Description |
|---|---|---|
| `GET` | `/personas` | List personas |
| `POST` | `/personas` | Create a persona |
| `GET` | `/personas/{persona_id}` | Get one persona |
| `PATCH` | `/personas/{persona_id}` | Update a persona |
| `DELETE` | `/personas/{persona_id}` | Delete a persona |
| `POST` | `/agents/{agent_id}/personas` | Associate a persona with an agent |
| `GET` | `/domains` | List domains |
| `POST` | `/domains` | Register a sending/receiving domain |
| `GET` | `/domains/{domain_id}` | Get one domain |
| `DELETE` | `/domains/{domain_id}` | Delete a domain |
| `POST` | `/domains/{domain_id}/verify` | Re-check DNS verification |
| `GET` | `/domains/{domain_id}/zone-file` | Render DNS records |

Domain create body:

```json
{
  "domain_name": "example.com"
}
```

## Native Channel Routes

Slack:

| Method | Path |
|---|---|
| `GET` | `/agents/{agent_id}/slack/workspaces` |
| `GET` | `/agents/{agent_id}/slack/workspaces/{team_id}/channels` |
| `GET` | `/agents/{agent_id}/slack/workspaces/{team_id}/channels/{channel_id}/messages` |
| `POST` | `/agents/{agent_id}/slack/workspaces/{team_id}/channels/{channel_id}/messages` |
| `POST` | `/agents/{agent_id}/slack/workspaces/{team_id}/users/{user_id}/messages` |

Telegram:

| Method | Path |
|---|---|
| `GET` | `/agents/{agent_id}/telegram/chats` |
| `GET` | `/agents/{agent_id}/telegram/chats/{chat_id}/messages` |
| `POST` | `/agents/{agent_id}/telegram/chats/{chat_id}/messages` |

Push:

| Method | Path |
|---|---|
| `GET` | `/agents/{agent_id}/push/devices` |
| `POST` | `/agents/{agent_id}/push/devices` |
| `DELETE` | `/agents/{agent_id}/push/devices/{device_id}` |
| `POST` | `/agents/{agent_id}/push/send` |

## AI

| Method | Path | Description |
|---|---|---|
| `POST` | `/agents/{agent_id}/ai/categorize` | Classify a message using labels |
| `POST` | `/agents/{agent_id}/ai/extract` | Extract structured data |
| `POST` | `/agents/{agent_id}/ai/summarize` | Summarize text, a message, or a thread |
| `POST` | `/agents/{agent_id}/ai/search` | Semantic search over messages |

Example extract body:

```json
{
  "message_id": "msg_...",
  "schema": {
    "invoice_number": "string",
    "amount_due": "number"
  }
}
```

Example summarize body:

```json
{
  "text": "Raw conversation text to summarize",
  "length": "short"
}
```

You can also summarize stored content with `message_id` or `thread_key`.
