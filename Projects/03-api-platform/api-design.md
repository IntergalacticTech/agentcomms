# API Design

Complete specification of the AgentMail REST API, including every endpoint, request/response shape, pagination model, error handling, and query parameters.

---

## Base URL

```
https://api.agentmail.aws/v1/
```

All endpoints are relative to this base URL. HTTPS is required; plain HTTP requests are rejected at the CloudFront layer.

---

## Authentication

Every request must include an API key via one of two mechanisms:

```
x-api-key: am_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

or

```
Authorization: Bearer am_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Both headers are checked in order. If both are present, `x-api-key` takes precedence. See [Authentication](./authentication.md) for full details on key format, scoping, and the authorizer flow.

---

## Common Conventions

### Content Type

All request and response bodies are `application/json` unless otherwise noted. Binary endpoints (attachment download, raw email) return `application/octet-stream` or `message/rfc822`.

### IDs

All resource IDs are ULIDs (Universally Unique Lexicographically Sortable Identifiers), which are 26-character Crockford Base32 strings. Example: `01HXYZ1234567890ABCDEFGHJK`. ULIDs encode creation time in their prefix, enabling natural chronological sorting.

### Timestamps

All timestamps are ISO 8601 in UTC: `2026-04-10T14:32:00.000Z`. The API accepts and returns this format exclusively.

### Pagination

All list endpoints use cursor-based pagination:

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | integer | Maximum items to return. Default: 25. Max: 100. |
| `page_token` | string | Opaque cursor from a previous response's `next_page_token`. |

Response:

```json
{
  "data": [ ... ],
  "next_page_token": "eyJzayI6IklOQk9YIzAxSFhZWi4uLiJ9",
  "has_more": true
}
```

The `page_token` is a Base64-encoded JSON object containing the DynamoDB `ExclusiveStartKey`. It is opaque to clients and must not be constructed manually.

### Common Query Parameters

These parameters are available on list endpoints where applicable:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ascending` | boolean | `false` | Sort order. Default is descending (newest first). |
| `before` | string (ISO 8601) | - | Return items created before this timestamp. |
| `after` | string (ISO 8601) | - | Return items created after this timestamp. |
| `include_spam` | boolean | `false` | Include messages flagged as spam. |
| `include_blocked` | boolean | `false` | Include messages from blocked senders. |
| `include_trash` | boolean | `false` | Include soft-deleted / trashed items. |

### Error Response Format

All errors follow a consistent structure:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Inbox 01HXYZ1234567890ABCDEFGHJK not found."
  }
}
```

Standard error codes:

| HTTP Status | Error Code | Description |
|------------|------------|-------------|
| 400 | `INVALID_REQUEST` | Malformed request body or invalid parameters |
| 400 | `VALIDATION_ERROR` | Request body fails schema validation |
| 401 | `UNAUTHORIZED` | Missing or invalid API key |
| 403 | `FORBIDDEN` | API key lacks permission for this resource |
| 403 | `SCOPE_VIOLATION` | API key scope does not include this resource |
| 404 | `RESOURCE_NOT_FOUND` | Requested resource does not exist |
| 409 | `CONFLICT` | Resource already exists or state conflict |
| 422 | `UNPROCESSABLE_ENTITY` | Semantically invalid request (e.g., sending to invalid email) |
| 429 | `RATE_LIMITED` | Rate limit exceeded |
| 500 | `INTERNAL_ERROR` | Unexpected server error |
| 503 | `SERVICE_UNAVAILABLE` | Temporary service issue, retry with backoff |

### Rate Limiting Headers

Every response includes rate limiting headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1712764800
```

When rate limited (429), the response also includes:

```
Retry-After: 3
```

See [Rate Limiting](./rate-limiting.md) for the full architecture.

---

## Endpoints

### Agent (Sign-Up and Verification)

#### POST /agent/signup

Create a new agent account. Sends a one-time verification code to the provided email.

**Request:**

```json
{
  "email": "admin@example.com",
  "org_name": "Acme Corp"
}
```

**Response (201 Created):**

```json
{
  "message": "Verification code sent to admin@example.com",
  "email": "admin@example.com",
  "expires_at": "2026-04-11T14:32:00.000Z"
}
```

#### POST /agent/verify

Verify the OTP code and complete account creation. Returns the organization and initial API key.

**Request:**

```json
{
  "email": "admin@example.com",
  "code": "482917"
}
```

**Response (200 OK):**

```json
{
  "organization": {
    "id": "01HXYZ1234567890ABCDEFGHJK",
    "name": "Acme Corp",
    "email": "admin@example.com",
    "tier": "free",
    "created_at": "2026-04-10T14:32:00.000Z"
  },
  "api_key": {
    "id": "01HXYZ1234567890ABCDEFGHJL",
    "key": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL",
    "name": "Default Key",
    "scope": "org",
    "created_at": "2026-04-10T14:32:00.000Z"
  }
}
```

The `key` field is shown only once at creation time. It is never returned again.

---

### Organizations

#### GET /organizations/me

Return the organization associated with the current API key.

**Response (200 OK):**

```json
{
  "id": "01HXYZ1234567890ABCDEFGHJK",
  "name": "Acme Corp",
  "email": "admin@example.com",
  "tier": "pro",
  "status": "active",
  "settings": {
    "default_domain": "mail.acme.com",
    "webhook_secret": "whsec_xxxxxxxxxxxxxxxx",
    "retention_days": 365,
    "ai_categorization_enabled": true,
    "max_attachment_size_mb": 25
  },
  "quotas": {
    "max_inboxes": 100000,
    "max_messages_per_day": 100000,
    "max_api_keys": 50,
    "max_pods": 100,
    "max_domains": 20,
    "max_webhooks": 50
  },
  "usage": {
    "inboxes": 1247,
    "messages_today": 8432,
    "api_keys": 3,
    "pods": 2,
    "domains": 1
  },
  "created_at": "2026-01-15T09:00:00.000Z",
  "updated_at": "2026-04-10T12:00:00.000Z"
}
```

---

### API Keys

#### GET /api-keys

List all API keys for the organization. The `key` field is never returned -- only metadata.

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGHJL",
      "name": "Production Key",
      "prefix": "am_live_7kB3",
      "scope": "org",
      "scope_resource_id": null,
      "last_used_at": "2026-04-10T14:00:00.000Z",
      "created_at": "2026-01-15T09:00:00.000Z"
    },
    {
      "id": "01HXYZ1234567890ABCDEFGHJM",
      "name": "Inbox-Scoped Key",
      "prefix": "am_live_9xR2",
      "scope": "inbox",
      "scope_resource_id": "01HXYZ1234567890ABCDEFGHJA",
      "last_used_at": "2026-04-09T22:15:00.000Z",
      "created_at": "2026-03-01T10:30:00.000Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

#### POST /api-keys

Create a new API key. The plaintext key is returned only in this response.

**Request:**

```json
{
  "name": "Worker Key",
  "scope": "pod",
  "scope_resource_id": "01HXYZ1234567890ABCDEFGHJP"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Human-readable name for the key |
| `scope` | string | yes | One of: `org`, `pod`, `inbox` |
| `scope_resource_id` | string | conditional | Required when scope is `pod` or `inbox`. The resource ID to scope to. |

**Response (201 Created):**

```json
{
  "id": "01HXYZ1234567890ABCDEFGHJN",
  "key": "am_live_4tU7wP0qS3xY6zA9bC2dE5fG8hJ1kM",
  "name": "Worker Key",
  "prefix": "am_live_4tU7",
  "scope": "pod",
  "scope_resource_id": "01HXYZ1234567890ABCDEFGHJP",
  "created_at": "2026-04-10T14:32:00.000Z"
}
```

#### DELETE /api-keys/{id}

Revoke an API key immediately. Cached authorizations expire within 5 minutes.

**Response (204 No Content)**

---

### Pods

Pods are logical groupings of inboxes for organizational and access-control purposes. An organization can have multiple pods (e.g., one per project, one per customer).

#### GET /pods

List all pods in the organization.

**Query Parameters:** `limit`, `page_token`, `ascending`

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGHJP",
      "name": "Customer Outreach",
      "description": "Inboxes for customer outreach agents",
      "inbox_count": 342,
      "settings": {
        "default_domain": "outreach.acme.com",
        "ai_categorization_enabled": true,
        "retention_days": 180
      },
      "created_at": "2026-02-01T10:00:00.000Z",
      "updated_at": "2026-04-08T16:45:00.000Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

#### GET /pods/{id}

Get a single pod by ID.

**Response (200 OK):** Same shape as individual item in the list above.

#### POST /pods

Create a new pod.

**Request:**

```json
{
  "name": "Customer Outreach",
  "description": "Inboxes for customer outreach agents",
  "settings": {
    "default_domain": "outreach.acme.com",
    "ai_categorization_enabled": true,
    "retention_days": 180
  }
}
```

**Response (201 Created):** Full pod object.

#### DELETE /pods/{id}

Delete a pod. Fails if the pod contains any inboxes.

**Response (204 No Content)**

---

### Inboxes

#### GET /inboxes

List all inboxes in the organization. Can be filtered by pod.

**Query Parameters:** `limit`, `page_token`, `ascending`, `pod_id`, `domain`, `status`

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGHJA",
      "email": "agent-47@mail.acme.com",
      "display_name": "Support Agent 47",
      "pod_id": "01HXYZ1234567890ABCDEFGHJP",
      "status": "active",
      "message_count": 1847,
      "unread_count": 12,
      "settings": {
        "auto_reply_enabled": false,
        "categorization_enabled": true,
        "spam_filter_level": "normal",
        "retention_days": 180
      },
      "forwarding": {
        "enabled": false,
        "address": null
      },
      "created_at": "2026-03-01T08:00:00.000Z",
      "updated_at": "2026-04-10T14:00:00.000Z"
    }
  ],
  "next_page_token": "eyJzayI6IklOQk9YIzAxSFhZWi4uLiJ9",
  "has_more": true
}
```

#### GET /inboxes/{id}

Get a single inbox by ID.

**Response (200 OK):** Same shape as individual item in the list above.

#### POST /inboxes

Create a new inbox. The email address is either auto-generated or explicitly specified.

**Request:**

```json
{
  "email": "agent-47@mail.acme.com",
  "display_name": "Support Agent 47",
  "pod_id": "01HXYZ1234567890ABCDEFGHJP",
  "settings": {
    "auto_reply_enabled": false,
    "categorization_enabled": true,
    "spam_filter_level": "normal"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | no | Desired email address. If omitted, a random address is generated on the org's default domain. |
| `display_name` | string | no | Display name for outbound messages |
| `pod_id` | string | no | Pod to assign this inbox to. If omitted, goes to the default pod. |
| `settings` | object | no | Inbox-level settings (merged with pod and org defaults) |

**Response (201 Created):** Full inbox object.

#### PATCH /inboxes/{id}

Update inbox properties. Supports partial updates.

**Request:**

```json
{
  "display_name": "Support Agent 47 (Updated)",
  "settings": {
    "auto_reply_enabled": true,
    "auto_reply_body": "I'll get back to you shortly."
  }
}
```

**Response (200 OK):** Full updated inbox object.

#### DELETE /inboxes/{id}

Delete an inbox and all its messages. This is a soft delete -- the inbox enters `deleted` status and is permanently purged after the retention period.

**Response (204 No Content)**

---

### Messages

#### GET /inboxes/{id}/messages

List messages in an inbox.

**Query Parameters:** `limit`, `page_token`, `ascending`, `before`, `after`, `include_spam`, `include_blocked`, `include_trash`, `thread_id`, `category`, `is_read`

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGM01",
      "thread_id": "01HXYZ1234567890ABCDEFGT01",
      "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
      "direction": "inbound",
      "from": {
        "name": "Jane Doe",
        "address": "jane@example.com"
      },
      "to": [
        { "name": "Support Agent 47", "address": "agent-47@mail.acme.com" }
      ],
      "cc": [],
      "bcc": [],
      "reply_to": [],
      "subject": "Question about pricing",
      "snippet": "Hi, I was wondering about your enterprise pricing...",
      "body_text": "Hi, I was wondering about your enterprise pricing. Could you send me details?",
      "body_html": "<p>Hi, I was wondering about your enterprise pricing. Could you send me details?</p>",
      "is_read": false,
      "is_starred": false,
      "is_spam": false,
      "is_trash": false,
      "labels": ["inquiry"],
      "category": "sales",
      "attachments": [
        {
          "id": "01HXYZ1234567890ABCDEFGA01",
          "filename": "requirements.pdf",
          "content_type": "application/pdf",
          "size": 245760
        }
      ],
      "headers": {
        "message-id": "<abc123@example.com>",
        "in-reply-to": null,
        "references": null
      },
      "ses_message_id": null,
      "received_at": "2026-04-10T14:30:00.000Z",
      "created_at": "2026-04-10T14:30:00.000Z"
    }
  ],
  "next_page_token": "eyJzayI6Ik1TRyMwMUhYWVouLi4ifQ==",
  "has_more": true
}
```

#### GET /inboxes/{id}/messages/{mid}

Get a single message by ID.

**Response (200 OK):** Same shape as individual item in the list above.

#### POST /inboxes/{id}/messages

Send a new message (compose a new email).

**Request:**

```json
{
  "to": [
    { "name": "Jane Doe", "address": "jane@example.com" }
  ],
  "cc": [],
  "bcc": [],
  "reply_to": [],
  "subject": "Re: Your inquiry",
  "body_text": "Thanks for reaching out. Here are the details...",
  "body_html": "<p>Thanks for reaching out. Here are the details...</p>",
  "attachments": [
    {
      "filename": "pricing.pdf",
      "content_type": "application/pdf",
      "content_base64": "JVBERi0xLjQK..."
    }
  ],
  "headers": {
    "X-Custom-Header": "custom-value"
  },
  "send_at": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | array | yes | List of recipients with `name` (optional) and `address` |
| `cc` | array | no | Carbon copy recipients |
| `bcc` | array | no | Blind carbon copy recipients |
| `reply_to` | array | no | Reply-to addresses |
| `subject` | string | yes | Email subject |
| `body_text` | string | conditional | Plain text body. At least one of `body_text` or `body_html` required. |
| `body_html` | string | conditional | HTML body |
| `attachments` | array | no | File attachments (inline base64 or references to uploaded files) |
| `headers` | object | no | Custom SMTP headers |
| `send_at` | string | no | ISO 8601 timestamp for scheduled send. If null, sends immediately. |

**Response (201 Created):** Full message object with `ses_message_id` populated.

#### POST /inboxes/{id}/messages/{mid}/reply

Reply to a message. The `to`, `subject`, and `in-reply-to`/`references` headers are auto-populated from the original.

**Request:**

```json
{
  "body_text": "Thanks, I'll look into this.",
  "body_html": "<p>Thanks, I'll look into this.</p>",
  "attachments": []
}
```

**Response (201 Created):** Full message object for the sent reply.

#### POST /inboxes/{id}/messages/{mid}/reply-all

Reply-all to a message. Same as reply, but all original recipients are included.

**Request:** Same shape as reply.

**Response (201 Created):** Full message object for the sent reply.

#### POST /inboxes/{id}/messages/{mid}/forward

Forward a message to new recipients.

**Request:**

```json
{
  "to": [
    { "address": "manager@example.com" }
  ],
  "body_text": "FYI -- see below.",
  "body_html": "<p>FYI -- see below.</p>"
}
```

**Response (201 Created):** Full message object for the forwarded message.

#### PATCH /inboxes/{id}/messages/{mid}

Update message metadata (read status, labels, starred, trash).

**Request:**

```json
{
  "is_read": true,
  "is_starred": true,
  "labels": ["important", "sales"]
}
```

**Response (200 OK):** Full updated message object.

#### GET /inboxes/{id}/messages/{mid}/attachments/{aid}

Download a message attachment. Returns binary data with appropriate `Content-Type` and `Content-Disposition` headers.

**Response (200 OK):**

```
Content-Type: application/pdf
Content-Disposition: attachment; filename="requirements.pdf"
Content-Length: 245760

<binary data>
```

The response is a redirect (302) to a pre-signed S3 URL with a 15-minute expiry.

#### GET /inboxes/{id}/messages/{mid}/raw

Download the raw RFC 2822 email source (complete MIME message).

**Response (200 OK):**

```
Content-Type: message/rfc822

<raw email source>
```

---

### Threads

#### GET /inboxes/{id}/threads

List threads in an inbox.

**Query Parameters:** `limit`, `page_token`, `ascending`, `before`, `after`, `include_spam`, `include_trash`, `category`, `is_read`

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGT01",
      "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
      "subject": "Question about pricing",
      "snippet": "Thanks, I'll look into this.",
      "message_count": 3,
      "unread_count": 1,
      "participants": [
        { "name": "Jane Doe", "address": "jane@example.com" },
        { "name": "Support Agent 47", "address": "agent-47@mail.acme.com" }
      ],
      "labels": ["sales", "inquiry"],
      "category": "sales",
      "is_read": false,
      "is_starred": false,
      "is_trash": false,
      "last_message_at": "2026-04-10T14:35:00.000Z",
      "created_at": "2026-04-10T14:30:00.000Z",
      "updated_at": "2026-04-10T14:35:00.000Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

#### GET /inboxes/{id}/threads/{tid}

Get a single thread by ID, including all messages in the thread.

**Response (200 OK):**

```json
{
  "id": "01HXYZ1234567890ABCDEFGT01",
  "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
  "subject": "Question about pricing",
  "snippet": "Thanks, I'll look into this.",
  "message_count": 3,
  "unread_count": 1,
  "participants": [
    { "name": "Jane Doe", "address": "jane@example.com" },
    { "name": "Support Agent 47", "address": "agent-47@mail.acme.com" }
  ],
  "labels": ["sales", "inquiry"],
  "category": "sales",
  "is_read": false,
  "is_starred": false,
  "is_trash": false,
  "messages": [
    { "...full message object..." }
  ],
  "last_message_at": "2026-04-10T14:35:00.000Z",
  "created_at": "2026-04-10T14:30:00.000Z",
  "updated_at": "2026-04-10T14:35:00.000Z"
}
```

#### PATCH /inboxes/{id}/threads/{tid}

Update thread metadata (read status, labels, starred, trash).

**Request:**

```json
{
  "is_read": true,
  "labels": ["resolved"]
}
```

**Response (200 OK):** Full updated thread object (without messages array).

#### DELETE /inboxes/{id}/threads/{tid}

Soft-delete a thread and all its messages (move to trash).

**Response (204 No Content)**

---

### Drafts

#### GET /inboxes/{id}/drafts

List all drafts in an inbox.

**Query Parameters:** `limit`, `page_token`, `ascending`

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGD01",
      "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
      "thread_id": null,
      "in_reply_to_message_id": null,
      "to": [
        { "name": "Jane Doe", "address": "jane@example.com" }
      ],
      "cc": [],
      "bcc": [],
      "subject": "Follow-up on our conversation",
      "body_text": "Hi Jane, just following up...",
      "body_html": "<p>Hi Jane, just following up...</p>",
      "attachments": [],
      "created_at": "2026-04-10T14:00:00.000Z",
      "updated_at": "2026-04-10T14:20:00.000Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

#### GET /inboxes/{id}/drafts/{did}

Get a single draft by ID.

**Response (200 OK):** Same shape as individual item in the list above.

#### POST /inboxes/{id}/drafts

Create a new draft.

**Request:**

```json
{
  "to": [
    { "name": "Jane Doe", "address": "jane@example.com" }
  ],
  "subject": "Follow-up",
  "body_text": "Draft content...",
  "body_html": "<p>Draft content...</p>",
  "thread_id": null,
  "in_reply_to_message_id": null
}
```

**Response (201 Created):** Full draft object.

#### PATCH /inboxes/{id}/drafts/{did}

Update a draft. Supports partial updates.

**Request:**

```json
{
  "body_text": "Updated draft content...",
  "body_html": "<p>Updated draft content...</p>"
}
```

**Response (200 OK):** Full updated draft object.

#### DELETE /inboxes/{id}/drafts/{did}

Permanently delete a draft.

**Response (204 No Content)**

#### POST /inboxes/{id}/drafts/{did}/send

Send a draft. The draft is converted to a sent message and deleted.

**Request (optional body):**

```json
{
  "send_at": null
}
```

**Response (200 OK):** Full message object for the sent message.

---

### Domains

#### GET /domains

List all custom domains for the organization.

**Query Parameters:** `limit`, `page_token`

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGDD1",
      "domain": "mail.acme.com",
      "status": "verified",
      "mx_verified": true,
      "spf_verified": true,
      "dkim_verified": true,
      "dmarc_verified": true,
      "dns_records": {
        "mx": {
          "type": "MX",
          "name": "mail.acme.com",
          "value": "10 inbound-smtp.us-east-1.amazonaws.com",
          "verified": true
        },
        "spf": {
          "type": "TXT",
          "name": "mail.acme.com",
          "value": "v=spf1 include:amazonses.com ~all",
          "verified": true
        },
        "dkim": [
          {
            "type": "CNAME",
            "name": "s1._domainkey.mail.acme.com",
            "value": "s1.dkim.agentmail.aws",
            "verified": true
          },
          {
            "type": "CNAME",
            "name": "s2._domainkey.mail.acme.com",
            "value": "s2.dkim.agentmail.aws",
            "verified": true
          },
          {
            "type": "CNAME",
            "name": "s3._domainkey.mail.acme.com",
            "value": "s3.dkim.agentmail.aws",
            "verified": true
          }
        ],
        "dmarc": {
          "type": "TXT",
          "name": "_dmarc.mail.acme.com",
          "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc@agentmail.aws",
          "verified": true
        }
      },
      "created_at": "2026-02-01T10:00:00.000Z",
      "verified_at": "2026-02-01T10:30:00.000Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

#### GET /domains/{id}

Get a single domain by ID.

**Response (200 OK):** Same shape as individual item in the list above.

#### POST /domains

Register a new custom domain. Returns DNS records that must be configured.

**Request:**

```json
{
  "domain": "mail.acme.com"
}
```

**Response (201 Created):** Full domain object with `status: "pending"` and all DNS records to configure.

#### PATCH /domains/{id}

Update domain settings.

**Request:**

```json
{
  "catch_all_inbox_id": "01HXYZ1234567890ABCDEFGHJA"
}
```

**Response (200 OK):** Full updated domain object.

#### DELETE /domains/{id}

Remove a custom domain. Inboxes on this domain continue to exist but can no longer send or receive email until reassigned.

**Response (204 No Content)**

#### POST /domains/{id}/verify

Trigger re-verification of DNS records for a domain.

**Response (200 OK):**

```json
{
  "id": "01HXYZ1234567890ABCDEFGDD1",
  "domain": "mail.acme.com",
  "status": "verifying",
  "mx_verified": true,
  "spf_verified": true,
  "dkim_verified": false,
  "dmarc_verified": true
}
```

#### GET /domains/{id}/zone-file

Export a BIND-format zone file for the domain's required DNS records.

**Response (200 OK):**

```
Content-Type: text/dns

; AgentMail DNS records for mail.acme.com
; Generated: 2026-04-10T14:32:00Z

mail.acme.com.    IN MX  10 inbound-smtp.us-east-1.amazonaws.com.
mail.acme.com.    IN TXT "v=spf1 include:amazonses.com ~all"
s1._domainkey.mail.acme.com. IN CNAME s1.dkim.agentmail.aws.
s2._domainkey.mail.acme.com. IN CNAME s2.dkim.agentmail.aws.
s3._domainkey.mail.acme.com. IN CNAME s3.dkim.agentmail.aws.
_dmarc.mail.acme.com. IN TXT "v=DMARC1; p=quarantine; rua=mailto:dmarc@agentmail.aws"
```

---

### Webhooks

#### GET /webhooks

List all webhooks for the organization.

**Query Parameters:** `limit`, `page_token`

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGW01",
      "url": "https://api.example.com/webhooks/agentmail",
      "events": [
        "message.received",
        "message.sent",
        "message.bounced",
        "inbox.created"
      ],
      "status": "active",
      "secret": "whsec_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "filter": {
        "pod_ids": ["01HXYZ1234567890ABCDEFGHJP"],
        "inbox_ids": []
      },
      "delivery_stats": {
        "total_delivered": 14523,
        "total_failed": 12,
        "last_delivered_at": "2026-04-10T14:30:00.000Z",
        "last_failed_at": "2026-04-09T03:12:00.000Z"
      },
      "created_at": "2026-02-15T10:00:00.000Z",
      "updated_at": "2026-04-10T14:30:00.000Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

Available webhook events:

| Event | Description |
|-------|-------------|
| `message.received` | New inbound message received |
| `message.sent` | Outbound message sent successfully |
| `message.bounced` | Outbound message bounced |
| `message.complained` | Recipient marked message as spam |
| `message.delayed` | Message delivery delayed |
| `inbox.created` | New inbox created |
| `inbox.deleted` | Inbox deleted |
| `domain.verified` | Domain verification completed |
| `domain.failed` | Domain verification failed |
| `subscription.updated` | Subscription tier changed |

#### GET /webhooks/{id}

Get a single webhook by ID.

**Response (200 OK):** Same shape as individual item in the list above.

#### POST /webhooks

Create a new webhook endpoint.

**Request:**

```json
{
  "url": "https://api.example.com/webhooks/agentmail",
  "events": ["message.received", "message.sent"],
  "filter": {
    "pod_ids": ["01HXYZ1234567890ABCDEFGHJP"]
  }
}
```

**Response (201 Created):** Full webhook object including the `secret` for signature verification.

#### PATCH /webhooks/{id}

Update a webhook.

**Request:**

```json
{
  "events": ["message.received", "message.sent", "message.bounced"],
  "status": "active"
}
```

**Response (200 OK):** Full updated webhook object.

#### DELETE /webhooks/{id}

Delete a webhook.

**Response (204 No Content)**

---

### Lists

Mailing lists / distribution lists for broadcasting to multiple external addresses.

#### GET /lists

List all mailing lists for the organization.

**Query Parameters:** `limit`, `page_token`

**Response (200 OK):**

```json
{
  "data": [
    {
      "id": "01HXYZ1234567890ABCDEFGL01",
      "name": "Product Updates",
      "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
      "member_count": 4521,
      "created_at": "2026-03-01T10:00:00.000Z",
      "updated_at": "2026-04-10T12:00:00.000Z"
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

#### GET /lists/{id}

Get a single list by ID, including members.

**Query Parameters:** `limit`, `page_token` (for paginating members)

**Response (200 OK):**

```json
{
  "id": "01HXYZ1234567890ABCDEFGL01",
  "name": "Product Updates",
  "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
  "member_count": 4521,
  "members": [
    {
      "address": "subscriber1@example.com",
      "name": "Subscriber One",
      "subscribed_at": "2026-03-15T09:00:00.000Z"
    }
  ],
  "next_page_token": "eyJzayI6IkxJU1QjMDFIWFlaLi4uIn0=",
  "has_more": true,
  "created_at": "2026-03-01T10:00:00.000Z",
  "updated_at": "2026-04-10T12:00:00.000Z"
}
```

#### POST /lists

Create a new mailing list.

**Request:**

```json
{
  "name": "Product Updates",
  "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
  "members": [
    { "address": "subscriber1@example.com", "name": "Subscriber One" },
    { "address": "subscriber2@example.com", "name": "Subscriber Two" }
  ]
}
```

**Response (201 Created):** Full list object.

#### DELETE /lists/{id}

Delete a mailing list.

**Response (204 No Content)**

---

### Metrics

#### POST /metrics/query

Query usage metrics for the organization. Supports flexible time-range and grouping.

**Request:**

```json
{
  "metric": "messages_sent",
  "period": "day",
  "start": "2026-04-01T00:00:00.000Z",
  "end": "2026-04-10T23:59:59.000Z",
  "group_by": "inbox_id",
  "filters": {
    "pod_id": "01HXYZ1234567890ABCDEFGHJP"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metric` | string | yes | One of: `messages_sent`, `messages_received`, `messages_bounced`, `api_calls`, `ai_tokens_used`, `storage_bytes` |
| `period` | string | yes | Aggregation period: `hour`, `day`, `week`, `month` |
| `start` | string | yes | Start of time range (ISO 8601) |
| `end` | string | yes | End of time range (ISO 8601) |
| `group_by` | string | no | Group results by: `inbox_id`, `pod_id`, `domain`, `category` |
| `filters` | object | no | Filter by `pod_id`, `inbox_id`, `domain` |

**Response (200 OK):**

```json
{
  "metric": "messages_sent",
  "period": "day",
  "start": "2026-04-01T00:00:00.000Z",
  "end": "2026-04-10T23:59:59.000Z",
  "data_points": [
    {
      "timestamp": "2026-04-01T00:00:00.000Z",
      "value": 1247,
      "groups": {
        "01HXYZ1234567890ABCDEFGHJA": 823,
        "01HXYZ1234567890ABCDEFGHJB": 424
      }
    },
    {
      "timestamp": "2026-04-02T00:00:00.000Z",
      "value": 1389,
      "groups": {
        "01HXYZ1234567890ABCDEFGHJA": 901,
        "01HXYZ1234567890ABCDEFGHJB": 488
      }
    }
  ]
}
```

---

### Search

#### POST /search

Full-text and semantic search across messages in the organization. Powered by OpenSearch Serverless.

**Request:**

```json
{
  "query": "enterprise pricing proposal",
  "mode": "semantic",
  "inbox_ids": ["01HXYZ1234567890ABCDEFGHJA"],
  "pod_ids": [],
  "date_range": {
    "start": "2026-01-01T00:00:00.000Z",
    "end": "2026-04-10T23:59:59.000Z"
  },
  "from": "jane@example.com",
  "has_attachments": true,
  "category": "sales",
  "limit": 20,
  "page_token": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | Search query text |
| `mode` | string | no | `keyword` (default), `semantic`, or `hybrid` |
| `inbox_ids` | array | no | Restrict to specific inboxes |
| `pod_ids` | array | no | Restrict to specific pods |
| `date_range` | object | no | Filter by date range |
| `from` | string | no | Filter by sender address |
| `to` | string | no | Filter by recipient address |
| `has_attachments` | boolean | no | Filter for messages with attachments |
| `category` | string | no | Filter by AI-assigned category |
| `limit` | integer | no | Max results (default 20, max 100) |
| `page_token` | string | no | Pagination cursor |

**Response (200 OK):**

```json
{
  "results": [
    {
      "message_id": "01HXYZ1234567890ABCDEFGM01",
      "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
      "thread_id": "01HXYZ1234567890ABCDEFGT01",
      "subject": "Enterprise Pricing Proposal",
      "snippet": "...attached the enterprise pricing proposal as discussed...",
      "from": { "name": "Jane Doe", "address": "jane@example.com" },
      "received_at": "2026-03-15T10:00:00.000Z",
      "score": 0.94,
      "highlights": [
        "...attached the <em>enterprise pricing proposal</em> as discussed..."
      ]
    }
  ],
  "total_count": 1,
  "next_page_token": null,
  "has_more": false
}
```

---

### WebSocket

#### WSS /ws

Real-time event stream over WebSocket. After connecting, the client must authenticate by sending an auth frame.

**Connection URL:**

```
wss://ws.agentmail.aws/v1/ws
```

**Authentication frame (client sends):**

```json
{
  "action": "auth",
  "api_key": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL"
}
```

**Auth success (server sends):**

```json
{
  "type": "auth_success",
  "org_id": "01HXYZ1234567890ABCDEFGHJK",
  "connection_id": "abc123def456"
}
```

**Subscribe to events:**

```json
{
  "action": "subscribe",
  "channels": [
    "inbox:01HXYZ1234567890ABCDEFGHJA",
    "pod:01HXYZ1234567890ABCDEFGHJP",
    "org:01HXYZ1234567890ABCDEFGHJK"
  ]
}
```

**Event frame (server sends):**

```json
{
  "type": "event",
  "channel": "inbox:01HXYZ1234567890ABCDEFGHJA",
  "event": "message.received",
  "data": {
    "message_id": "01HXYZ1234567890ABCDEFGM01",
    "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
    "thread_id": "01HXYZ1234567890ABCDEFGT01",
    "from": { "name": "Jane Doe", "address": "jane@example.com" },
    "subject": "Quick question",
    "snippet": "Hey, I had a quick question about..."
  },
  "timestamp": "2026-04-10T14:35:00.000Z"
}
```

**Heartbeat:** The server sends a ping frame every 30 seconds. Clients must respond with a pong within 10 seconds or the connection is closed.

**Unsubscribe:**

```json
{
  "action": "unsubscribe",
  "channels": ["inbox:01HXYZ1234567890ABCDEFGHJA"]
}
```

---

## Endpoint Summary Table

| Method | Path | Description |
|--------|------|-------------|
| POST | `/agent/signup` | Create a new agent account |
| POST | `/agent/verify` | Verify OTP and complete sign-up |
| GET | `/organizations/me` | Get current organization |
| GET | `/api-keys` | List API keys |
| POST | `/api-keys` | Create an API key |
| DELETE | `/api-keys/{id}` | Revoke an API key |
| GET | `/pods` | List pods |
| GET | `/pods/{id}` | Get a pod |
| POST | `/pods` | Create a pod |
| DELETE | `/pods/{id}` | Delete a pod |
| GET | `/inboxes` | List inboxes |
| GET | `/inboxes/{id}` | Get an inbox |
| POST | `/inboxes` | Create an inbox |
| PATCH | `/inboxes/{id}` | Update an inbox |
| DELETE | `/inboxes/{id}` | Delete an inbox |
| GET | `/inboxes/{id}/messages` | List messages |
| GET | `/inboxes/{id}/messages/{mid}` | Get a message |
| POST | `/inboxes/{id}/messages` | Send a message |
| POST | `/inboxes/{id}/messages/{mid}/reply` | Reply to a message |
| POST | `/inboxes/{id}/messages/{mid}/reply-all` | Reply-all to a message |
| POST | `/inboxes/{id}/messages/{mid}/forward` | Forward a message |
| PATCH | `/inboxes/{id}/messages/{mid}` | Update message metadata |
| GET | `/inboxes/{id}/messages/{mid}/attachments/{aid}` | Download attachment |
| GET | `/inboxes/{id}/messages/{mid}/raw` | Download raw email |
| GET | `/inboxes/{id}/threads` | List threads |
| GET | `/inboxes/{id}/threads/{tid}` | Get a thread |
| PATCH | `/inboxes/{id}/threads/{tid}` | Update thread metadata |
| DELETE | `/inboxes/{id}/threads/{tid}` | Delete a thread |
| GET | `/inboxes/{id}/drafts` | List drafts |
| GET | `/inboxes/{id}/drafts/{did}` | Get a draft |
| POST | `/inboxes/{id}/drafts` | Create a draft |
| PATCH | `/inboxes/{id}/drafts/{did}` | Update a draft |
| DELETE | `/inboxes/{id}/drafts/{did}` | Delete a draft |
| POST | `/inboxes/{id}/drafts/{did}/send` | Send a draft |
| GET | `/domains` | List domains |
| GET | `/domains/{id}` | Get a domain |
| POST | `/domains` | Register a domain |
| PATCH | `/domains/{id}` | Update domain settings |
| DELETE | `/domains/{id}` | Remove a domain |
| POST | `/domains/{id}/verify` | Trigger domain verification |
| GET | `/domains/{id}/zone-file` | Export zone file |
| GET | `/webhooks` | List webhooks |
| GET | `/webhooks/{id}` | Get a webhook |
| POST | `/webhooks` | Create a webhook |
| PATCH | `/webhooks/{id}` | Update a webhook |
| DELETE | `/webhooks/{id}` | Delete a webhook |
| GET | `/lists` | List mailing lists |
| GET | `/lists/{id}` | Get a mailing list |
| POST | `/lists` | Create a mailing list |
| DELETE | `/lists/{id}` | Delete a mailing list |
| POST | `/metrics/query` | Query usage metrics |
| POST | `/search` | Search messages |
| WSS | `/ws` | Real-time WebSocket |
