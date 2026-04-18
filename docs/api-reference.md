# API Reference

Base URL: `https://api.victorymail.dev/v1`

All request and response bodies use JSON (`Content-Type: application/json`).

---

## Authentication

FreeMail supports two authentication methods:

### API Key (recommended for programmatic access)

Pass your API key in the `x-api-key` header:

```bash
curl https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_YOUR_KEY"
```

Or as a Bearer token in the `Authorization` header:

```bash
curl https://api.victorymail.dev/v1/inboxes \
  -H "Authorization: Bearer am_live_YOUR_KEY"
```

API keys have three scope levels:

| Scope | Access |
|-------|--------|
| `org` | Full access to all resources in the organization |
| `pod` | Access scoped to a specific pod and its inboxes |
| `inbox` | Access to a single inbox only |

### JWT (Console / Browser)

For the developer console, authenticate via `POST /console/login` to get a JWT token, then pass it as a Bearer token:

```bash
curl https://api.victorymail.dev/v1/organizations/me \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

## Pagination

All list endpoints support cursor-based pagination with these query parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 25 | Items per page (1-100) |
| `page_token` | string | -- | Opaque cursor from a previous response |
| `order` | string | `desc` | Sort order: `asc` or `desc` |

Paginated responses include:

```json
{
  "data": [...],
  "next_page_token": "eyJ...",
  "has_more": true
}
```

To fetch the next page, pass `next_page_token` as the `page_token` query parameter. When `has_more` is `false`, there are no more results.

---

## Error Responses

All errors follow this format:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Inbox not found"
  }
}
```

### Error Codes

| HTTP Status | Code | Description |
|-------------|------|-------------|
| 400 | `BAD_REQUEST` | Invalid request body or parameters |
| 401 | `UNAUTHORIZED` | Missing or invalid credentials |
| 404 | `NOT_FOUND` | Resource not found |
| 408 | `TIMEOUT` | Wait/poll timed out with no matching message |
| 409 | `CONFLICT` | Resource already exists |
| 429 | `RATE_LIMITED` | Too many requests |

---

## Rate Limiting

Rate limits are enforced per API key at three levels:

1. **API Gateway** -- per-key requests per second and monthly quota
2. **Application-level** -- per-endpoint limits (e.g., 100 sends/minute per inbox)
3. **WAF** -- 10,000 requests per 5 minutes per IP

When rate limited, the API returns HTTP 429. Check the `Retry-After` header for when to retry.

---

## Agent Signup (No Auth Required)

### POST /agent/signup

Send a verification code to an email address to start account creation.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Email address to sign up with |

```bash
curl -X POST https://api.victorymail.dev/v1/agent/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com"}'
```

**Response (201):**

```json
{
  "message": "Verification code sent",
  "email": "admin@example.com"
}
```

### POST /agent/verify

Verify the OTP code and create an organization with an initial API key.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Email used during signup |
| `code` | string | Yes | 6-digit verification code |

```bash
curl -X POST https://api.victorymail.dev/v1/agent/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "code": "482917"}'
```

**Response (201):**

```json
{
  "organization": {
    "id": "01HXYZ1234567890ABCDEFGHJK",
    "name": "admin",
    "email": "admin@example.com",
    "tier": "free",
    "status": "active"
  },
  "api_key": {
    "id": "01HXYZ1234567890ABCDEFGHJL",
    "key": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL...",
    "key_prefix": "am_live_7kB3",
    "scope": "org"
  }
}
```

---

## Console Auth (No Auth Required)

### POST /console/signup

Create a console account with email and password.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Email address |
| `password` | string | Yes | Password |
| `name` | string | No | Display name (defaults to email prefix) |

```bash
curl -X POST https://api.victorymail.dev/v1/console/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "securepass123", "name": "Admin"}'
```

**Response (201):**

```json
{
  "message": "Account created. Check your email to verify.",
  "org_id": "01HXYZ1234567890ABCDEFGHJK",
  "api_key": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL..."
}
```

### POST /console/login

Authenticate and receive JWT tokens.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Email address |
| `password` | string | Yes | Password |

```bash
curl -X POST https://api.victorymail.dev/v1/console/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "securepass123"}'
```

**Response (200):**

```json
{
  "id_token": "eyJhbGciOi...",
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "expires_in": 3600
}
```

### POST /console/refresh

Refresh an expired access token.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `refresh_token` | string | Yes | Refresh token from login |

```bash
curl -X POST https://api.victorymail.dev/v1/console/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJhbGciOi..."}'
```

**Response (200):**

```json
{
  "id_token": "eyJhbGciOi...",
  "access_token": "eyJhbGciOi...",
  "expires_in": 3600
}
```

### GET /console/me

Get the authenticated user's organization profile. Requires JWT authentication.

```bash
curl https://api.victorymail.dev/v1/console/me \
  -H "Authorization: Bearer eyJhbGciOi..."
```

**Response (200):**

```json
{
  "org_id": "01HXYZ1234567890ABCDEFGHJK",
  "name": "Admin",
  "email": "admin@example.com",
  "tier": "free"
}
```

---

## Organizations

### GET /organizations/me

Get the current organization's details.

```bash
curl https://api.victorymail.dev/v1/organizations/me \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "id": "01HXYZ1234567890ABCDEFGHJK",
  "name": "Acme Corp",
  "email": "admin@acme.com",
  "tier": "free",
  "status": "active",
  "settings": {},
  "quotas": {
    "max_inboxes": 5,
    "max_messages_per_day": 1000,
    "max_api_keys": 5,
    "max_pods": 3,
    "max_domains": 1,
    "max_webhooks": 5
  },
  "usage": {
    "inboxes": 2,
    "api_keys": 1,
    "pods": 0,
    "domains": 0
  },
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```

---

## API Keys

### GET /api-keys

List all API keys for the organization. The full key value is never returned -- only the prefix.

**Query Parameters:** `limit`, `page_token`, `order`

```bash
curl https://api.victorymail.dev/v1/api-keys \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGHJL",
      "name": "Default API Key",
      "key_prefix": "am_live_7kB3",
      "scope": "org",
      "scope_resource_id": "01HXYZ1234567890ABCDEFGHJK",
      "status": "active",
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T10:00:00Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

### POST /api-keys

Create a new API key. The plaintext key is returned only once in the response.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Human-readable name for the key |
| `scope` | string | Yes | One of: `org`, `pod`, `inbox` |
| `scope_resource_id` | string | Conditional | Required when scope is `pod` or `inbox`. The ID of the pod or inbox. |

```bash
curl -X POST https://api.victorymail.dev/v1/api-keys \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Worker Key", "scope": "pod", "scope_resource_id": "01HXYZ..."}'
```

**Response (201):**

```json
{
  "id": "01HXYZ1234567890ABCDEFGHJQ",
  "name": "Worker Key",
  "key": "am_live_4tU7wP0qS3xY6zA9bC2dE5fG8hJ1kM...",
  "key_prefix": "am_live_4tU7",
  "scope": "pod",
  "scope_resource_id": "01HXYZ...",
  "status": "active",
  "created_at": "2025-01-15T10:30:00Z"
}
```

### DELETE /api-keys/{id}

Revoke an API key. The key immediately stops working.

```bash
curl -X DELETE https://api.victorymail.dev/v1/api-keys/01HXYZ1234567890ABCDEFGHJQ \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response:** 204 No Content

---

## Pods

Pods are logical groupings of inboxes. Use them to organize inboxes by project, team, or workflow.

### GET /pods

List all pods.

**Query Parameters:** `limit`, `page_token`, `order`

```bash
curl https://api.victorymail.dev/v1/pods \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGHJR",
      "name": "Customer Outreach",
      "org_id": "01HXYZ1234567890ABCDEFGHJK",
      "inbox_count": 5,
      "status": "active",
      "settings": {},
      "created_at": "2025-01-15T10:30:00Z",
      "updated_at": "2025-01-15T10:30:00Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

### POST /pods

Create a new pod.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Pod name |
| `settings` | object | No | Arbitrary settings |

```bash
curl -X POST https://api.victorymail.dev/v1/pods \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Customer Outreach"}'
```

**Response (201):**

```json
{
  "id": "01HXYZ1234567890ABCDEFGHJR",
  "name": "Customer Outreach",
  "org_id": "01HXYZ1234567890ABCDEFGHJK",
  "inbox_count": 0,
  "status": "active",
  "settings": {},
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

### GET /pods/{id}

Get a single pod.

```bash
curl https://api.victorymail.dev/v1/pods/01HXYZ1234567890ABCDEFGHJR \
  -H "x-api-key: am_live_YOUR_KEY"
```

### DELETE /pods/{id}

Delete a pod. Fails if the pod contains any inboxes.

```bash
curl -X DELETE https://api.victorymail.dev/v1/pods/01HXYZ1234567890ABCDEFGHJR \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response:** 204 No Content

---

## Inboxes

### GET /inboxes

List all inboxes. Optionally filter by pod.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pod_id` | string | Filter by pod ID |
| `limit` | integer | Items per page (1-100, default 25) |
| `page_token` | string | Pagination cursor |
| `order` | string | `asc` or `desc` |

```bash
curl https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGHJM",
      "org_id": "01HXYZ1234567890ABCDEFGHJK",
      "pod_id": "default",
      "email": "a7k3m9pq2rx5@victorymail.dev",
      "display_name": "Signup Bot",
      "status": "active",
      "message_count": 12,
      "unread_count": 3,
      "settings": {},
      "forwarding": {},
      "created_at": "2025-01-15T10:30:00Z",
      "updated_at": "2025-01-15T10:30:00Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

### POST /inboxes

Create a new inbox. If no `email` is supplied, a random address is generated on the platform domain you choose via the `domain` field (defaulting to `victorymail.dev`).

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `domain` | string | No | Platform domain to generate the address on. One of `victorymail.dev`, `karmascale.net`, `karmascale.org`. Defaults to `victorymail.dev`. Ignored when `email` is provided. |
| `email` | string | No | Desired email address. Must be on a platform domain or on a custom domain you have verified. |
| `display_name` | string | No | Display name for the inbox |
| `pod_id` | string | No | Pod to associate with (defaults to `default`) |
| `settings` | object | No | Inbox settings |
| `forwarding` | object | No | Forwarding configuration |

Email addresses are unique **per domain** — `agent@victorymail.dev` and `agent@karmascale.net` are separate inboxes and may belong to different accounts.

```bash
# Random address on victorymail.dev (default)
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "Signup Bot"}'

# Random address on a specific platform domain
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "Signup Bot", "domain": "karmascale.net"}'

# Specific address on a specific domain
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "support@karmascale.org", "display_name": "Support Bot"}'
```

**Response (201):** Returns the inbox object.

### GET /inboxes/{id}

Get a single inbox by ID.

```bash
curl https://api.victorymail.dev/v1/inboxes/01HXYZ1234567890ABCDEFGHJM \
  -H "x-api-key: am_live_YOUR_KEY"
```

### PATCH /inboxes/{id}

Update an inbox.

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `display_name` | string | New display name |
| `settings` | object | Updated settings |
| `forwarding` | object | Updated forwarding config |

```bash
curl -X PATCH https://api.victorymail.dev/v1/inboxes/01HXYZ1234567890ABCDEFGHJM \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "Updated Bot Name"}'
```

### DELETE /inboxes/{id}

Soft-delete an inbox.

```bash
curl -X DELETE https://api.victorymail.dev/v1/inboxes/01HXYZ1234567890ABCDEFGHJM \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response:** 204 No Content

---

## Messages

### GET /inboxes/{id}/messages

List messages in an inbox. Returns summary fields (no body content).

**Query Parameters:** `limit`, `page_token`, `order`

```bash
curl https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "data": [
    {
      "id": "01HXYZ...",
      "thread_id": "01HXYZ...",
      "inbox_id": "01HXYZ...",
      "direction": "inbound",
      "from_addr": {"name": "Alice Example", "address": "alice@example.com"},
      "to": [{"name": "", "address": "agent@victorymail.dev"}],
      "cc": [],
      "subject": "Re: Hello!",
      "snippet": "Thanks for reaching out...",
      "is_read": false,
      "is_starred": false,
      "is_spam": false,
      "is_trash": false,
      "labels": [],
      "category": "inbox",
      "has_attachments": false,
      "attachment_count": 0,
      "received_at": "2026-04-13T11:00:00Z",
      "created_at": "2026-04-13T11:00:00Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

> **Note on recipient shape:** `from_addr`, `to`, `cc`, `bcc`, and `reply_to` are all **Recipient objects** with `{"name": string, "address": string}`. Both inbound and outbound messages use this canonical shape. When sending a message you may pass a bare email string for `to`/`cc`/`bcc` and the platform will promote it to a Recipient.

### GET /inboxes/{id}/messages/{mid}

Get a single message with full body content.

```bash
curl https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages/MESSAGE_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):** Returns the full message detail including `body_text`, `body_html`, `bcc`, `headers`, `status`, etc.

### POST /inboxes/{id}/messages

Send a new message from the inbox.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | array | Yes | Recipients. Each item is `{"address": "...", "name": "..."}` or a plain string. |
| `cc` | array | No | CC recipients |
| `bcc` | array | No | BCC recipients |
| `reply_to` | string | No | Reply-to address |
| `subject` | string | Yes | Email subject |
| `body_text` | string | Conditional | Plain text body. At least one of `body_text` or `body_html` is required. |
| `body_html` | string | Conditional | HTML body |
| `labels` | array | No | Labels to apply |
| `category` | string | No | Message category |
| `headers` | object | No | Custom email headers |

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": [{"address": "user@example.com", "name": "User"}],
    "subject": "Hello!",
    "body_text": "Plain text body",
    "body_html": "<p>HTML body</p>"
  }'
```

**Response (201):** Returns the message detail.

### PATCH /inboxes/{id}/messages/{mid}

Update message metadata (read status, star, labels).

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `is_read` | boolean | Mark as read/unread |
| `is_starred` | boolean | Star/unstar |
| `is_trash` | boolean | Move to/from trash |
| `labels` | array | Set labels |

```bash
curl -X PATCH https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages/MESSAGE_ID \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"is_read": true, "is_starred": true}'
```

### POST /inboxes/{id}/messages/{mid}/reply

Reply to a message. Automatically sets `Re:` subject prefix and continues the thread.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `body_text` | string | Conditional | Reply body (text). At least one body field required. |
| `body_html` | string | Conditional | Reply body (HTML) |
| `to` | array | No | Override recipients (defaults to original sender) |

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages/MESSAGE_ID/reply \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"body_text": "Thanks for your message!"}'
```

**Response (201):** Returns the reply message detail.

### POST /inboxes/{id}/messages/{mid}/reply-all

Reply to all recipients. Same as reply but includes all original `to` and `cc` recipients.

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages/MESSAGE_ID/reply-all \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"body_text": "Thanks everyone!"}'
```

### POST /inboxes/{id}/messages/{mid}/forward

Forward a message to new recipients. Creates a new thread.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | array | Yes | Forward recipients |
| `body_text` | string | No | Additional text (original body is included automatically) |
| `body_html` | string | No | Additional HTML |

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages/MESSAGE_ID/forward \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to": [{"address": "colleague@example.com"}]}'
```

**Response (201):** Returns the forwarded message detail.

---

## Threads

### GET /inboxes/{id}/threads

List threads in an inbox.

**Query Parameters:** `limit`, `page_token`, `order`

```bash
curl https://api.victorymail.dev/v1/inboxes/INBOX_ID/threads \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "data": [
    {
      "id": "01HXYZ...",
      "inbox_id": "01HXYZ...",
      "subject": "Project Update",
      "snippet": "Here's the latest...",
      "message_count": 3,
      "is_read": true,
      "is_starred": false,
      "is_trash": false,
      "labels": [],
      "last_message_at": "2025-01-15T11:30:00Z",
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T11:30:00Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

### GET /inboxes/{id}/threads/{tid}

Get a thread with all its messages embedded.

```bash
curl https://api.victorymail.dev/v1/inboxes/INBOX_ID/threads/THREAD_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):** Returns the thread object with a `messages` array containing all messages in the thread.

### PATCH /inboxes/{id}/threads/{tid}

Update thread metadata.

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `is_read` | boolean | Mark thread as read/unread |
| `is_starred` | boolean | Star/unstar |
| `is_trash` | boolean | Move to/from trash |
| `labels` | array | Set labels |

```bash
curl -X PATCH https://api.victorymail.dev/v1/inboxes/INBOX_ID/threads/THREAD_ID \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"is_read": true}'
```

### DELETE /inboxes/{id}/threads/{tid}

Soft-delete a thread (moves to trash).

```bash
curl -X DELETE https://api.victorymail.dev/v1/inboxes/INBOX_ID/threads/THREAD_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):** Returns the updated thread with `is_trash: true`.

---

## Drafts

### GET /inboxes/{id}/drafts

List drafts in an inbox.

**Query Parameters:** `limit`, `page_token`, `order`

```bash
curl https://api.victorymail.dev/v1/inboxes/INBOX_ID/drafts \
  -H "x-api-key: am_live_YOUR_KEY"
```

### POST /inboxes/{id}/drafts

Create a new draft.

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `to` | array | Recipients |
| `cc` | array | CC recipients |
| `bcc` | array | BCC recipients |
| `subject` | string | Subject line |
| `body_text` | string | Plain text body |
| `body_html` | string | HTML body |
| `attachments` | array | Attachment references |
| `thread_id` | string | Thread to associate with |
| `in_reply_to_message_id` | string | Message this draft replies to |

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/drafts \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": [{"address": "user@example.com"}],
    "subject": "Draft email",
    "body_text": "Work in progress..."
  }'
```

**Response (201):** Returns the draft object.

### GET /inboxes/{id}/drafts/{did}

Get a single draft.

```bash
curl https://api.victorymail.dev/v1/inboxes/INBOX_ID/drafts/DRAFT_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

### PATCH /inboxes/{id}/drafts/{did}

Update a draft. Same fields as create.

```bash
curl -X PATCH https://api.victorymail.dev/v1/inboxes/INBOX_ID/drafts/DRAFT_ID \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"subject": "Updated subject"}'
```

### DELETE /inboxes/{id}/drafts/{did}

Permanently delete a draft.

```bash
curl -X DELETE https://api.victorymail.dev/v1/inboxes/INBOX_ID/drafts/DRAFT_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response:** 204 No Content

### POST /inboxes/{id}/drafts/{did}/send

Convert a draft into a sent message and delete the draft.

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/drafts/DRAFT_ID/send \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (201):** Returns the sent message detail.

---

## Attachments

### GET /inboxes/{id}/messages/{mid}/attachments

List all attachments for a message.

```bash
curl https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages/MESSAGE_ID/attachments \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "data": [
    {
      "id": "01HXYZ...",
      "filename": "requirements.pdf",
      "content_type": "application/pdf",
      "size": 245760,
      "is_inline": false,
      "content_id": "",
      "created_at": "2025-01-15T11:00:00Z"
    }
  ]
}
```

### GET /inboxes/{id}/messages/{mid}/attachments/{aid}

Download an attachment. Returns a 302 redirect to a pre-signed S3 URL (15-minute expiry).

```bash
curl -L https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages/MESSAGE_ID/attachments/ATTACHMENT_ID \
  -H "x-api-key: am_live_YOUR_KEY" \
  -o attachment.pdf
```

---

## Wait / Extract OTP

These endpoints use long-polling to wait for incoming messages.

### POST /inboxes/{id}/wait

Wait for a message matching the provided filters. Blocks for up to 25 seconds.

**Request Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timeout` | integer | 25 | Seconds to wait (max 25) |
| `filter.from` | string | -- | Sender address substring match |
| `filter.subject_contains` | string | -- | Subject substring match |
| `filter.after` | string (ISO 8601) | -- | Only messages created after this timestamp |
| `filter.is_read` | boolean | -- | Filter by read status |

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/wait \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "timeout": 25,
    "filter": {
      "from": "noreply@service.com",
      "subject_contains": "verification"
    }
  }'
```

**Response (200):** Returns the full message detail (including body) of the first matching message.

**Response (408):** Timeout -- no matching message arrived.

```json
{
  "error": {
    "code": "TIMEOUT",
    "message": "No matching message received within timeout period."
  }
}
```

### POST /inboxes/{id}/extract-otp

Wait for a matching message, then extract an OTP/verification code from the body. Supports 4-8 digit numeric codes, dash-separated codes (e.g., `123-456`), and 6-10 character alphanumeric codes.

**Request Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timeout` | integer | 25 | Seconds to wait (max 25) |
| `sender` | string | -- | Filter by sender address substring |
| `subject_contains` | string | -- | Filter by subject substring |
| `after` | string (ISO 8601) | -- | Only messages after this timestamp |

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/extract-otp \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sender": "noreply@service.com", "timeout": 25}'
```

**Response (200):**

```json
{
  "code": "482917",
  "message_id": "01HXYZ...",
  "from": "noreply@service.com",
  "subject": "Your verification code"
}
```

When no code can be extracted, `code` is `null` and `body_text` is included for manual inspection.

---

## Domains

See the [Custom Domains guide](custom-domains.md) for a full walkthrough.

### GET /domains

List all registered domains.

**Query Parameters:** `limit`, `page_token`, `order`

```bash
curl https://api.victorymail.dev/v1/domains \
  -H "x-api-key: am_live_YOUR_KEY"
```

### POST /domains

Register a custom domain. Returns the DNS records you need to configure.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `domain` | string | Yes | Domain name (e.g., `mail.acme.com`) |

```bash
curl -X POST https://api.victorymail.dev/v1/domains \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"domain": "mail.acme.com"}'
```

**Response (201):**

```json
{
  "id": "01HXYZ...",
  "domain": "mail.acme.com",
  "status": "pending",
  "mx_verified": false,
  "spf_verified": false,
  "dkim_verified": false,
  "dmarc_verified": false,
  "dns_records": {
    "mx": {"type": "MX", "name": "mail.acme.com", "value": "10 inbound-smtp.us-east-1.amazonaws.com", "ttl": 3600},
    "spf": {"type": "TXT", "name": "mail.acme.com", "value": "v=spf1 include:amazonses.com ~all", "ttl": 3600},
    "dkim": [
      {"type": "CNAME", "name": "s1._domainkey.mail.acme.com", "value": "s1.dkim.victorymail.dev", "ttl": 3600},
      {"type": "CNAME", "name": "s2._domainkey.mail.acme.com", "value": "s2.dkim.victorymail.dev", "ttl": 3600},
      {"type": "CNAME", "name": "s3._domainkey.mail.acme.com", "value": "s3.dkim.victorymail.dev", "ttl": 3600}
    ],
    "dmarc": {"type": "TXT", "name": "_dmarc.mail.acme.com", "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc@victorymail.dev", "ttl": 3600}
  },
  "catch_all_inbox_id": "",
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

### GET /domains/{id}

Get domain details and verification status.

```bash
curl https://api.victorymail.dev/v1/domains/DOMAIN_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

### PATCH /domains/{id}

Update domain settings.

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `catch_all_inbox_id` | string | Inbox ID to receive all unmatched emails for this domain |

```bash
curl -X PATCH https://api.victorymail.dev/v1/domains/DOMAIN_ID \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"catch_all_inbox_id": "01HXYZ..."}'
```

### DELETE /domains/{id}

Delete a domain registration.

```bash
curl -X DELETE https://api.victorymail.dev/v1/domains/DOMAIN_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response:** 204 No Content

### POST /domains/{id}/verify

Trigger DNS verification for a domain. The system will check that all required DNS records are configured correctly.

```bash
curl -X POST https://api.victorymail.dev/v1/domains/DOMAIN_ID/verify \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):** Returns the domain with updated status (`verifying`).

### GET /domains/{id}/zone-file

Export a BIND-format zone file containing all required DNS records. Useful for importing into your DNS provider.

```bash
curl https://api.victorymail.dev/v1/domains/DOMAIN_ID/zone-file \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200, Content-Type: text/dns):**

```
; Zone file for mail.acme.com
; Generated by FreeMail
$ORIGIN mail.acme.com.
$TTL 3600

mail.acme.com.    3600    IN    MX    10 inbound-smtp.us-east-1.amazonaws.com

mail.acme.com.    3600    IN    TXT    "v=spf1 include:amazonses.com ~all"

s1._domainkey.mail.acme.com.    3600    IN    CNAME    s1.dkim.victorymail.dev.
s2._domainkey.mail.acme.com.    3600    IN    CNAME    s2.dkim.victorymail.dev.
s3._domainkey.mail.acme.com.    3600    IN    CNAME    s3.dkim.victorymail.dev.

_dmarc.mail.acme.com.    3600    IN    TXT    "v=DMARC1; p=quarantine; rua=mailto:dmarc@victorymail.dev"
```

---

## Webhooks

See the [Webhooks guide](webhooks.md) for full setup instructions.

### GET /webhooks

List all webhooks.

**Query Parameters:** `limit`, `page_token`, `order`

```bash
curl https://api.victorymail.dev/v1/webhooks \
  -H "x-api-key: am_live_YOUR_KEY"
```

### POST /webhooks

Create a webhook endpoint.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | HTTPS URL to deliver events to |
| `events` | array | Yes | List of event types to subscribe to |
| `filter` | object | No | Optional filters (`pod_ids`, `inbox_ids`) |

```bash
curl -X POST https://api.victorymail.dev/v1/webhooks \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://api.example.com/webhooks/freemail",
    "events": ["message.received", "message.sent"]
  }'
```

**Response (201):**

```json
{
  "id": "01HXYZ...",
  "url": "https://api.example.com/webhooks/freemail",
  "events": ["message.received", "message.sent"],
  "status": "active",
  "secret": "whsec_a1b2c3d4e5f6...",
  "filter": {},
  "delivery_stats": {
    "total": 0,
    "success": 0,
    "failed": 0,
    "last_delivered_at": null,
    "last_failed_at": null
  },
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

### GET /webhooks/{id}

Get a single webhook and its delivery stats.

```bash
curl https://api.victorymail.dev/v1/webhooks/WEBHOOK_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

### PATCH /webhooks/{id}

Update a webhook.

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | New delivery URL |
| `events` | array | Updated event subscriptions |
| `status` | string | `active` or `paused` |
| `filter` | object | Updated filters |

```bash
curl -X PATCH https://api.victorymail.dev/v1/webhooks/WEBHOOK_ID \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "paused"}'
```

### DELETE /webhooks/{id}

Delete a webhook.

```bash
curl -X DELETE https://api.victorymail.dev/v1/webhooks/WEBHOOK_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response:** 204 No Content

---

## Mailing Lists

### GET /lists

List all mailing lists.

**Query Parameters:** `limit`, `page_token`, `order`

```bash
curl https://api.victorymail.dev/v1/lists \
  -H "x-api-key: am_live_YOUR_KEY"
```

### POST /lists

Create a mailing list with optional initial members.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | List name |
| `inbox_id` | string | Yes | Inbox ID to send from |
| `members` | array | No | Initial members: `[{"address": "...", "name": "..."}]` |

```bash
curl -X POST https://api.victorymail.dev/v1/lists \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Product Updates",
    "inbox_id": "01HXYZ...",
    "members": [
      {"address": "user1@example.com", "name": "User One"},
      {"address": "user2@example.com", "name": "User Two"}
    ]
  }'
```

**Response (201):**

```json
{
  "id": "01HXYZ...",
  "name": "Product Updates",
  "inbox_id": "01HXYZ...",
  "member_count": 2,
  "members": [
    {"address": "user1@example.com", "name": "User One", "subscribed_at": "2025-01-15T10:30:00Z"},
    {"address": "user2@example.com", "name": "User Two", "subscribed_at": "2025-01-15T10:30:00Z"}
  ],
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

### GET /lists/{id}

Get a mailing list with paginated members.

**Query Parameters:** `limit`, `page_token`

```bash
curl https://api.victorymail.dev/v1/lists/LIST_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

### POST /lists/{id}/members

Add members to an existing list.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `members` | array | Yes | Members to add: `[{"address": "...", "name": "..."}]` |

```bash
curl -X POST https://api.victorymail.dev/v1/lists/LIST_ID/members \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"members": [{"address": "user3@example.com"}]}'
```

**Response (200):**

```json
{"added": 1}
```

### DELETE /lists/{id}/members/{email}

Remove a member from a list.

```bash
curl -X DELETE https://api.victorymail.dev/v1/lists/LIST_ID/members/user3@example.com \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response:** 204 No Content

### DELETE /lists/{id}

Delete a mailing list and all its members.

```bash
curl -X DELETE https://api.victorymail.dev/v1/lists/LIST_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response:** 204 No Content

---

## Billing

See the [Billing & Plans guide](billing.md) for details on tiers and quotas.

### GET /billing/status

Get the current billing status for your organization.

```bash
curl https://api.victorymail.dev/v1/billing/status \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "org_id": "01HXYZ...",
  "tier": "free",
  "billing_status": "none",
  "stripe_customer_id": null
}
```

### POST /billing/checkout

Create a Stripe Checkout session to upgrade to a paid tier.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tier` | string | No | Target tier: `starter` or `pro`. Defaults to `pro`. |

```bash
curl -X POST https://api.victorymail.dev/v1/billing/checkout \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tier": "starter"}'
```

**Response (200):**

```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/...",
  "tier": "starter"
}
```

Redirect the user to `checkout_url` to complete payment. On success the org's tier and quotas are updated via a Stripe webhook.

### POST /billing/portal

Create a Stripe Billing Portal session for managing an existing subscription.

```bash
curl -X POST https://api.victorymail.dev/v1/billing/portal \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "portal_url": "https://billing.stripe.com/p/session/..."
}
```

### POST /billing/webhook

Stripe webhook endpoint. **No authentication header required** — instead the handler verifies the `Stripe-Signature` header against a shared secret. You do not call this endpoint directly; it is registered with Stripe at `https://api.victorymail.dev/v1/billing/webhook` and receives `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, and `invoice.payment_failed` events.

---

## Search

### POST /search

Text search across messages in your organization. Matches case-insensitively against subject and snippet. Optionally filter by inbox, date range, or result count.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | No | Text to match against subject + snippet (case-insensitive substring) |
| `inbox_id` | string | No | Limit results to this inbox |
| `limit` | integer | No | Maximum results (1–100, default 25) |
| `after` | string | No | Only return messages with `created_at >= after` (ISO 8601) |
| `before` | string | No | Only return messages with `created_at <= before` (ISO 8601) |

```bash
curl -X POST https://api.victorymail.dev/v1/search \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "verification", "limit": 10}'
```

**Response (200):**

```json
{
  "data": [
    {
      "id": "01HXYZ...",
      "inbox_id": "01HXYZ...",
      "thread_id": "01HXYZ...",
      "direction": "inbound",
      "from_addr": {"name": "", "address": "noreply@service.com"},
      "to": [{"name": "", "address": "agent@victorymail.dev"}],
      "subject": "Your verification code",
      "snippet": "Your code is 482917...",
      "is_read": false,
      "category": "inbox",
      "received_at": "2026-04-13T11:00:00Z",
      "created_at": "2026-04-13T11:00:00Z"
    }
  ],
  "total": 1
}
```

---

## AI Features

All AI endpoints require **Starter tier or above** (`starter`, `pro`, or `enterprise`). Free-tier calls return `403 FORBIDDEN`.

Powered by Amazon Bedrock Claude Haiku. Each call counts against your monthly AI quota.

### POST /ai/categorize

Classify a message into one of a set of categories.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `inbox_id` | string | Yes | Inbox containing the message |
| `message_id` | string | Yes | Message to categorize |
| `categories` | array[string] | Yes | Category labels to choose from |

```bash
curl -X POST https://api.victorymail.dev/v1/ai/categorize \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inbox_id": "01HXYZ...",
    "message_id": "01HXYZ...",
    "categories": ["transactional", "marketing", "support", "spam"]
  }'
```

**Response (200):**

```json
{"message_id": "01HXYZ...", "category": "transactional"}
```

The chosen category is also written back to the message record as its `category` field.

### POST /ai/extract

Extract structured fields from a message body using a JSON schema.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `inbox_id` | string | Yes | Inbox containing the message |
| `message_id` | string | Yes | Message to extract from |
| `schema` | object | Yes | JSON schema describing the fields to extract |

```bash
curl -X POST https://api.victorymail.dev/v1/ai/extract \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inbox_id": "01HXYZ...",
    "message_id": "01HXYZ...",
    "schema": {
      "order_id": "string",
      "total_amount": "number",
      "delivery_date": "date"
    }
  }'
```

**Response (200):**

```json
{
  "message_id": "01HXYZ...",
  "extracted": {
    "order_id": "ORD-4782",
    "total_amount": 49.99,
    "delivery_date": "2026-04-18"
  }
}
```

If the model returns invalid JSON, the raw text is included under the key `_raw` so the caller can fall back to regex parsing.

### POST /ai/summarize

Produce a 2–3 sentence summary of a message.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `inbox_id` | string | Yes | Inbox containing the message |
| `message_id` | string | Yes | Message to summarize |

```bash
curl -X POST https://api.victorymail.dev/v1/ai/summarize \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"inbox_id": "01HXYZ...", "message_id": "01HXYZ..."}'
```

**Response (200):**

```json
{
  "message_id": "01HXYZ...",
  "summary": "The customer is requesting a refund for order ORD-4782 shipped on April 2. They report the product arrived damaged and include photo attachments."
}
```

---

## Metrics

### POST /metrics/query

Query aggregate counters for your organization over a time range.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metric` | string | Yes | One of `messages_sent`, `messages_received`, `inboxes_created`, `api_calls` |
| `period` | string | No | Bucket size: `hour`, `day`, `week`, `month`. Default `day`. |
| `start` | string | No | ISO 8601 start of range |
| `end` | string | No | ISO 8601 end of range |
| `group_by` | string | No | Optional field to group results by (e.g. `inbox_id`, `category`) |

```bash
curl -X POST https://api.victorymail.dev/v1/metrics/query \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "metric": "messages_received",
    "period": "day",
    "start": "2026-04-01T00:00:00Z",
    "end": "2026-04-14T00:00:00Z"
  }'
```

**Response (200):**

```json
{
  "metric": "messages_received",
  "period": "day",
  "start": "2026-04-01T00:00:00Z",
  "end": "2026-04-14T00:00:00Z",
  "group_by": null,
  "data": [
    {"bucket": "2026-04-12", "count": 142},
    {"bucket": "2026-04-13", "count": 178}
  ]
}
```

### GET /metrics/usage

Current usage counters for the caller's organization against its quota.

```bash
curl https://api.victorymail.dev/v1/metrics/usage \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "inboxes": 3,
  "messages_today": 47,
  "api_keys": 2,
  "pods": 1,
  "domains": 0,
  "webhooks": 1,
  "tier": "free",
  "quotas": {
    "max_inboxes": 1,
    "max_messages_per_day": 50,
    "max_api_keys": 1,
    "max_pods": 1,
    "max_domains": 0,
    "max_webhooks": 1,
    "max_storage_mb": 100,
    "retention_days": 7,
    "ai_calls_per_month": 0
  }
}
```

---

## Secret Vault

KMS-encrypted secret storage tied to your organization. Each secret is encrypted with a per-org KMS CMK that is created automatically on first write. Ciphertext lives in a dedicated S3 bucket; metadata lives in DynamoDB. Requires **Starter tier or above** on the hosted platform (Free tier has `max_storage_mb: 100` and the handler will gate vault access by tier in a future release).

### POST /vault

Create a new secret.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | string | Yes | Human-readable label (e.g. `"github-pat"`) |
| `value` | string | Yes | Secret value to encrypt |
| `is_totp` | boolean | No | True if `value` is a base32 TOTP seed (RFC 6238). Enables `GET /vault/{id}/totp`. |
| `description` | string | No | Free-form description |
| `metadata` | object | No | Arbitrary JSON metadata |

```bash
curl -X POST https://api.victorymail.dev/v1/vault \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"label": "github-pat", "value": "ghp_..."}'
```

**Response (201):** Returns the secret metadata — never the value itself.

### GET /vault

List secrets in your org. Returns metadata only; to retrieve a value use `GET /vault/{id}?reveal=true`.

### GET /vault/{id}

Get secret metadata. Pass `?reveal=true` to additionally return the decrypted value in the `value` field. Every access updates the `last_accessed_at` timestamp.

```bash
curl "https://api.victorymail.dev/v1/vault/01HXYZ.../?reveal=true" \
  -H "x-api-key: am_live_YOUR_KEY"
```

### GET /vault/{id}/totp

Compute the current 6-digit TOTP code from a stored base32 seed. The seed itself never leaves the vault.

```bash
curl https://api.victorymail.dev/v1/vault/01HXYZ.../totp \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{"id": "01HXYZ...", "code": "482917", "period_seconds": 30}
```

Returns `400 BAD_REQUEST` if the secret is not flagged `is_totp=true`.

### DELETE /vault/{id}

Delete a secret. Removes the DynamoDB record and the ciphertext blob from S3. Returns **204**.

---

## Personas

Persistent identity profiles for AI agents. Each persona stores a consistent set of first/last name, DOB, address, phone, email, and free-form metadata so multi-turn interactions with external services present as the same synthetic user every time.

### POST /personas

Create a new persona. Either pass field values directly, or pass `"generate": true` to have Bedrock Claude Haiku produce a plausible synthetic identity.

**Request Body (manual):**

| Field | Type | Description |
|---|---|---|
| `label` | string | Display label |
| `first_name` | string | |
| `last_name` | string | |
| `date_of_birth` | string | `YYYY-MM-DD` |
| `address_line_1`, `address_line_2`, `city`, `state`, `postal_code`, `country` | string | Full address |
| `phone` | string | `+1XXXXXXXXXX` |
| `email` | string | |
| `occupation` | string | |
| `bio` | string | |
| `metadata` | object | Free-form |
| `inbox_id` | string | Optional link to an inbox |

**Request Body (generated):**

```json
{"generate": true, "hint": "Software engineer in her 30s based in Austin"}
```

```bash
curl -X POST https://api.victorymail.dev/v1/personas \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"generate": true, "hint": "Freelance designer in Portland"}'
```

**Response (201):** Full persona object.

### GET /personas

List personas in your org. Paginated.

### GET /personas/{id}

Get a single persona.

### PATCH /personas/{id}

Update any field.

### DELETE /personas/{id}

Delete. Returns **204**.

---

## Push Notifications

Mobile push delivery via Amazon SNS Mobile Push. Before push can be used you must register device tokens captured from your mobile app, then publish to the inbox's registered devices.

> **Note:** Push requires platform application ARNs (APNs for iOS, FCM for Android) to be configured on the backend. Until ops wires those up, `POST /inboxes/{id}/devices` returns `503 NOT_CONFIGURED`.

### POST /inboxes/{id}/devices

Register a device token.

**Request Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `platform` | string | Yes | `"apns"` or `"fcm"` |
| `token` | string | Yes | Device token from APNs / FCM registration |

**Response (201):** Returns a device record with the SNS endpoint ARN.

### GET /inboxes/{id}/devices

List registered devices for the inbox.

### DELETE /inboxes/{id}/devices/{did}

Unregister a device and delete its SNS endpoint.

### POST /inboxes/{id}/push

Send a push notification to every registered device on the inbox.

**Request Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `title` | string | One of title/message | Notification title |
| `message` | string | One of title/message | Notification body |
| `data` | object | No | Custom key/value data (strings) |

**Response (200):**

```json
{"sent": 2, "failed": 0}
```

---

## SMS

Inbound SMS capture (via AWS End User Messaging) and outbound SMS send. Mirrors the email model so an agent polling `/inboxes/{id}/wait?channel=sms` can capture OTP codes delivered by text.

> **Note:** SMS requires a registered 10DLC or toll-free phone number. Until ops completes 10DLC brand + campaign registration, `POST /inboxes/{id}/sms` returns `503 NOT_CONFIGURED`.

### POST /inboxes/{id}/sms

Send an outbound SMS from this inbox.

**Request Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `to` | string | Yes | E.164 phone number (e.g. `+14155551234`) |
| `body` | string | Yes | Message body (max 1600 chars for long messages) |

**Response (201):** Returns the message record with `channel: "sms"` and `direction: "outbound"`.

### Inbound SMS

Inbound SMS is delivered automatically to inboxes that have a phone number attached. Messages are stored with `channel: "sms"` and appear in the same `/inboxes/{id}/messages` listing as email (filter by `channel=sms` if supported by your client). The `wait_for_message` and `extract_otp` endpoints work across both email and SMS.
