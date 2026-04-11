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

Create a new inbox. If no email address is specified, a random `@victorymail.dev` address is generated.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | No | Desired email address. Must be on a verified domain. |
| `display_name` | string | No | Display name for the inbox |
| `pod_id` | string | No | Pod to associate with (defaults to `default`) |
| `settings` | object | No | Inbox settings |
| `forwarding` | object | No | Forwarding configuration |

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "Signup Bot", "pod_id": "01HXYZ..."}'
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
      "from_addr": "sender@example.com",
      "to": ["agent@victorymail.dev"],
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
      "received_at": "2025-01-15T11:00:00Z",
      "created_at": "2025-01-15T11:00:00Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

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

Create a Stripe Checkout session to upgrade to the Pro tier.

```bash
curl -X POST https://api.victorymail.dev/v1/billing/checkout \
  -H "x-api-key: am_live_YOUR_KEY"
```

**Response (200):**

```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/..."
}
```

Redirect the user to `checkout_url` to complete payment.

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
