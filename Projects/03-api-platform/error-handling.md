# Error Handling, Pagination, and Operational Patterns

Cross-cutting API concerns that apply to every AgentMail endpoint. This document covers the standard error envelope, the complete error code reference, cursor-based pagination, idempotency, request validation, versioning, rate limit headers, request/response conventions, webhook signature verification, and SDK error handling patterns.

---

## 1. Error Response Format

Every error response from the AgentMail API uses a consistent JSON envelope. Clients should always check for the presence of the top-level `error` key to determine whether a request succeeded or failed.

### Standard Error Envelope

```json
{
  "error": {
    "code": "quota_exceeded",
    "message": "Monthly email limit of 1,000 exceeded. Upgrade to Pro for 10,000 emails/month.",
    "type": "rate_limit",
    "param": "max_emails_per_month",
    "details": {
      "current": 1000,
      "limit": 1000,
      "resets_at": "2026-05-01T00:00:00Z"
    },
    "upgrade_url": "https://console.agentmail.aws/dashboard/usage",
    "request_id": "req_abc123",
    "documentation_url": "https://docs.agentmail.aws/errors/quota_exceeded"
  }
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|:--------:|-------------|
| `code` | string | Yes | Machine-readable error code (snake_case). Use this for programmatic error handling. |
| `message` | string | Yes | Human-readable description. May change without notice; do not match on this string. |
| `type` | string | Yes | Error category: `validation`, `auth`, `billing`, `email`, `resource`, `conflict`, `rate_limit`, `server`. |
| `param` | string | No | The specific parameter or field that caused the error, when applicable. |
| `details` | object | No | Additional structured data relevant to the error. Shape varies by error code. |
| `upgrade_url` | string | No | Present on billing/quota errors. Links to the console page where the user can upgrade. |
| `request_id` | string | Yes | Unique identifier for this request. Always include this when contacting support. Format: `req_` followed by a ULID. |
| `documentation_url` | string | Yes | Link to the documentation page for this specific error code. |

### Key Principles

1. **Stable codes, unstable messages.** The `code` field is a contract; the `message` field is advisory. SDK authors should switch on `code`, never on `message`.
2. **One error per response.** The API returns a single top-level error. For validation errors with multiple field failures, the individual failures are nested inside `details.errors` (see Section 5).
3. **No error on success.** Successful responses (2xx) never contain an `error` key. The absence of `error` is the canonical success signal.
4. **Request ID on every response.** The `request_id` is also returned in the `X-Request-Id` response header on both success and error responses.

---

## 2. Complete Error Code Reference

Every error code the API can return, organized by HTTP status. Each code is stable and will not be removed or renamed within a major API version.

### 400 Bad Request -- Validation Errors

| Code | Type | Message Template | When It Occurs |
|------|------|-----------------|----------------|
| `invalid_request` | validation | Request body failed schema validation. | The JSON body does not conform to the OpenAPI schema for this endpoint. Missing required fields, wrong types, unknown fields when `additionalProperties: false`. |
| `invalid_parameter` | validation | Query parameter `{param}` is invalid. | A query string parameter has an invalid value (e.g., `limit=abc`, `ascending=maybe`). |
| `missing_parameter` | validation | Required parameter `{param}` is missing. | A required query parameter or path parameter is absent. |
| `invalid_email_address` | validation | `{value}` is not a valid email address. | The `to`, `cc`, `bcc`, `from`, or `reply_to` field contains a string that does not pass RFC 5322 validation. |
| `message_too_large` | validation | Message size {size} exceeds the {limit} limit. | The combined size of the email body plus all attachments exceeds the maximum. Free tier: 10 MB. Pro and above: 25 MB. |
| `attachment_too_large` | validation | Attachment `{filename}` ({size}) exceeds the {limit} per-attachment limit. | A single attachment exceeds the per-file limit (10 MB on Free, 25 MB on paid tiers). |
| `too_many_recipients` | validation | {count} recipients exceeds the maximum of 50. | The combined count of `to` + `cc` + `bcc` addresses exceeds 50 per message. |

### 401 Unauthorized -- Authentication Errors

| Code | Type | Message Template | When It Occurs |
|------|------|-----------------|----------------|
| `authentication_required` | auth | No API key or JWT token was provided. Include an `x-api-key` or `Authorization: Bearer` header. | Neither `x-api-key` nor `Authorization` header is present, or both are empty. |
| `invalid_api_key` | auth | The provided API key is invalid or has been revoked. | The key does not match any active key in the system. This includes deleted keys and keys with typos. |
| `expired_token` | auth | The JWT token has expired. Request a new token from the auth endpoint. | The JWT `exp` claim is in the past. The token was valid but has aged out. |

### 403 Forbidden -- Authorization and Billing Errors

| Code | Type | Message Template | When It Occurs |
|------|------|-----------------|----------------|
| `insufficient_scope` | auth | This API key does not have the `{scope}` permission required to access `{resource}`. | The key's scope array does not include the permission needed for this operation. For example, a read-only key attempting a POST. |
| `feature_not_available` | billing | `{feature}` requires the {tier} tier or higher. Your current tier is {current_tier}. | The organization's pricing tier does not include the requested feature. Details include `feature`, `required_tier`, and `current_tier`. |
| `organization_disabled` | billing | This organization has been disabled. Contact support@agentmail.aws for assistance. | The organization is suspended due to non-payment, abuse, or manual deactivation by an admin. |
| `domain_not_verified` | email | Cannot send from `{domain}`. This domain has not been verified. | An attempt to send email from a domain that has not completed DNS verification (DKIM + SPF + return path). |

### 404 Not Found -- Resource Errors

| Code | Type | Message Template | When It Occurs |
|------|------|-----------------|----------------|
| `not_found` | resource | The requested resource does not exist. | Generic not-found for any resource type. Also returned when the resource exists but belongs to a different organization (to avoid leaking existence information). |
| `inbox_not_found` | resource | Inbox `{inbox_id}` does not exist. | The inbox ID in the URL path does not match any inbox owned by the authenticated organization. |
| `message_not_found` | resource | Message `{message_id}` does not exist. | The message ID in the URL path does not match any message in the specified inbox. |
| `thread_not_found` | resource | Thread `{thread_id}` does not exist. | The thread ID in the URL path does not match any thread in the specified inbox. |

### 409 Conflict

| Code | Type | Message Template | When It Occurs |
|------|------|-----------------|----------------|
| `already_exists` | conflict | A resource with this identifier already exists. | Attempting to create a resource with an ID or unique attribute (e.g., inbox address) that is already in use. Details include the conflicting field and value. |
| `domain_already_claimed` | conflict | The domain `{domain}` is already verified by another organization. | A domain verification attempt for a domain that another organization has already verified. Contact support if this is a domain ownership dispute. |

### 422 Unprocessable Entity

| Code | Type | Message Template | When It Occurs |
|------|------|-----------------|----------------|
| `unprocessable_entity` | validation | The request is syntactically valid but cannot be processed: {reason}. | The request passes schema validation but fails business logic checks. Examples: attempting to send a draft that has no recipients, attempting to reply to a message that does not exist in the thread, attempting to delete a domain that has active inboxes. |

### 429 Too Many Requests -- Rate Limit Errors

| Code | Type | Message Template | When It Occurs |
|------|------|-----------------|----------------|
| `rate_limited` | rate_limit | Too many requests. Retry after {retry_after} seconds. | The per-second or per-minute request rate has been exceeded. The `Retry-After` header indicates when to retry. |
| `quota_exceeded` | rate_limit | {quota_type} quota of {limit} exceeded. Resets at {resets_at}. | A monthly or daily usage quota has been exhausted. Details include `current`, `limit`, `resets_at`, and `upgrade_url`. |
| `sending_suspended` | rate_limit | Email sending has been suspended for this organization due to {reason}. | Sending is temporarily suspended due to high bounce rates, spam complaints, or manual review. Details include `reason`, `suspended_at`, and `review_url`. |

### 5xx Server Errors

| Code | Type | Message Template | When It Occurs |
|------|------|-----------------|----------------|
| `internal_error` | server | An unexpected error occurred. Please try again or contact support if the issue persists. | An unhandled exception in the Lambda handler. The `request_id` is essential for support to trace the failure in CloudWatch. |
| `upstream_error` | server | An upstream service (SES) returned an error. Please retry. | Amazon SES, DynamoDB, or another AWS service returned a transient error. Retrying with exponential backoff is recommended. |
| `service_unavailable` | server | The service is temporarily unavailable. Please retry shortly. | The API is undergoing maintenance or experiencing capacity issues. A `Retry-After` header may be present. |
| `timeout` | server | The request timed out after {seconds} seconds. | The Lambda function hit its execution time limit (29 seconds for API Gateway integration). This is uncommon and typically indicates a DynamoDB hot partition or a very large query. |

---

## 3. Pagination

AgentMail uses **cursor-based pagination** for all list endpoints. Cursor-based pagination provides stable results even when data is being inserted or deleted between pages, unlike offset-based pagination.

### Request Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 20 | Number of items to return per page. Minimum: 1. Maximum: 100. |
| `page_token` | string | (none) | Opaque cursor from a previous response's `next_page_token`. Omit for the first page. |
| `ascending` | boolean | false | Sort order. `false` (default) returns newest first for time-ordered resources (messages, threads). `true` returns oldest first. For non-time-ordered resources (inboxes), this controls alphabetical order. |

### Response Envelope

All list endpoints return the same envelope:

```json
{
  "data": [
    { "id": "msg_01HXYZ...", "subject": "Welcome", "created_at": "2026-04-10T14:30:00.000Z" },
    { "id": "msg_01HXYW...", "subject": "Confirm", "created_at": "2026-04-10T14:25:00.000Z" }
  ],
  "has_more": true,
  "next_page_token": "eyJsYXN0X2tl..."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `data` | array | Array of resource objects. May be empty (`[]`) if no results match. |
| `has_more` | boolean | `true` if there are more pages after this one. `false` on the last page. |
| `next_page_token` | string or null | Opaque cursor string to pass as `page_token` for the next page. `null` when `has_more` is `false`. |

### Cursor Implementation

Under the hood, cursors are DynamoDB `LastEvaluatedKey` objects that are serialized to JSON and then Base64-encoded. This is an implementation detail; clients must treat cursors as opaque strings.

**Cursor behavior:**

- Cursors are tied to the exact query parameters (limit, ascending, any filters) used to generate them. Changing query parameters between pages produces undefined results.
- Cursors expire after **24 hours**. Using an expired cursor returns a `400 invalid_parameter` error with `param: "page_token"`.
- Cursors are scoped to the authenticated organization. Using a cursor from one org with another org's API key returns `400 invalid_parameter`.

### Example: Paginating Through All Messages

**First request:**

```
GET /v1/inboxes/inb_01HXYZ.../messages?limit=50
```

**Response:**

```json
{
  "data": [ /* 50 messages, newest first */ ],
  "has_more": true,
  "next_page_token": "eyJsYXN0X2tleSI6eyJQSyI6eyJTIjoiaW5iXzAxSFhZWi4uLiJ9LCJTS..."
}
```

**Second request:**

```
GET /v1/inboxes/inb_01HXYZ.../messages?limit=50&page_token=eyJsYXN0X2tleSI6eyJQSyI6eyJTIjoiaW5iXzAxSFhZWi4uLiJ9LCJTS...
```

**Last page response:**

```json
{
  "data": [ /* 12 messages */ ],
  "has_more": false,
  "next_page_token": null
}
```

### Client-Side Pagination Patterns

**Python SDK:**

```python
import agentmail

client = agentmail.Client(api_key="ak_live_xxx")

# Iterate through all messages in an inbox
all_messages = []
page_token = None

while True:
    response = client.inboxes.messages.list(
        inbox_id="inb_01HXYZ...",
        limit=100,
        page_token=page_token,
    )
    all_messages.extend(response.data)

    if not response.has_more:
        break
    page_token = response.next_page_token

print(f"Total messages: {len(all_messages)}")
```

**Python SDK (auto-pagination iterator):**

```python
# The SDK also provides an auto-paginating iterator
for message in client.inboxes.messages.list_auto(inbox_id="inb_01HXYZ...", limit=100):
    print(message.subject)
```

**Node.js SDK:**

```javascript
const AgentMail = require("agentmail");

const client = new AgentMail({ apiKey: "ak_live_xxx" });

// Manual pagination
async function getAllMessages(inboxId) {
  const allMessages = [];
  let pageToken = undefined;

  do {
    const response = await client.inboxes.messages.list(inboxId, {
      limit: 100,
      pageToken,
    });
    allMessages.push(...response.data);
    pageToken = response.nextPageToken;
  } while (response.hasMore);

  return allMessages;
}
```

**Node.js SDK (auto-pagination):**

```javascript
// Auto-paginating async iterator
for await (const message of client.inboxes.messages.listAuto(inboxId, { limit: 100 })) {
  console.log(message.subject);
}
```

**cURL (manual pagination):**

```bash
# First page
curl -s -H "x-api-key: ak_live_xxx" \
  "https://api.agentmail.aws/v1/inboxes/inb_01HXYZ.../messages?limit=50" \
  | jq '.next_page_token'

# Next page (using the token from the previous response)
curl -s -H "x-api-key: ak_live_xxx" \
  "https://api.agentmail.aws/v1/inboxes/inb_01HXYZ.../messages?limit=50&page_token=eyJsYXN0..."
```

---

## 4. Idempotency

All POST (create) endpoints support idempotent requests via the `Idempotency-Key` header. This prevents duplicate resource creation when a client retries a request due to network failures or timeouts.

### How It Works

1. The client generates a unique key (a UUID v4 is recommended) and includes it in the `Idempotency-Key` header.
2. On the first request with that key, the server processes the request normally and stores the response alongside the key.
3. On subsequent requests with the same key (within 24 hours), the server returns the stored response without re-executing the operation.

### Request Format

```
POST /v1/inboxes
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json

{
  "display_name": "Support Inbox"
}
```

### Behavior Matrix

| Scenario | HTTP Status | Body | Notes |
|----------|:-----------:|------|-------|
| First request with key | 201 | Created resource | Normal creation. Response is stored for 24h. |
| Replay within 24h, same key, same body | 200 | Original response body | Idempotent replay. Note: status is 200, not 201, to signal this is a replay. |
| Replay within 24h, same key, different body | 409 | Error: `already_exists` | The key is bound to the original request body. Changing the body is a conflict. |
| After 24h, same key | 201 | New resource | The key has expired (TTL). The request is treated as new. |
| No `Idempotency-Key` header | 201 | Created resource | Normal creation. No idempotency protection. |

### Implementation Details

Idempotency keys are stored in a dedicated DynamoDB table:

```
Table: agentmail-idempotency
Partition Key: org_id#idempotency_key  (String)
Attributes:
  - response_status: (Number) HTTP status code of the original response
  - response_body:   (String) JSON-serialized response body
  - request_hash:    (String) SHA-256 of the request body (for conflict detection)
  - created_at:      (String) ISO 8601 timestamp
  - ttl:             (Number) Unix timestamp, 24 hours after created_at
```

The write uses a DynamoDB `ConditionExpression` of `attribute_not_exists(PK)` to ensure atomicity. If the condition fails, the existing record is read and the stored response is returned.

### Scope

- Idempotency keys are scoped **per organization**. Two different organizations can use the same key value without conflict.
- Keys are specific to an endpoint. The same key used on `/v1/inboxes` and `/v1/inboxes/{id}/messages` are treated as separate keys (the full request path is part of the stored key).
- Only POST endpoints support idempotency. GET, PUT, PATCH, and DELETE are naturally idempotent and do not need this mechanism.

### Best Practices

1. **Always use idempotency keys for critical creates.** Especially for `POST /v1/inboxes/{id}/messages/send` -- duplicate email sends are far worse than duplicate inbox creation.
2. **Generate fresh keys per logical operation.** Do not reuse keys across different intended operations.
3. **Retry with the same key.** When retrying a failed request due to a network timeout, always include the same `Idempotency-Key` that was used in the original attempt.
4. **Use UUID v4.** Any string up to 255 characters works, but UUID v4 provides sufficient uniqueness with minimal coordination.

---

## 5. Request Validation

Request validation happens in two phases: schema validation at the API Gateway level, and business logic validation inside the Lambda handler.

### Phase 1: API Gateway Schema Validation

API Gateway request validators enforce the OpenAPI schema before the request reaches the Lambda function. This catches:

- Missing required fields
- Wrong data types (string where number expected)
- Values outside of `enum` constraints
- Strings exceeding `maxLength`
- Arrays exceeding `maxItems`
- Pattern mismatches (e.g., email regex)

API Gateway validation errors return a generic `400` with `code: "invalid_request"`. The `message` field includes the OpenAPI validation error from API Gateway.

### Phase 2: Lambda Business Logic Validation

The Lambda handler performs additional validation that cannot be expressed in OpenAPI:

- Cross-field validation (e.g., `scheduled_at` must be in the future)
- Reference validation (e.g., the `inbox_id` in the URL must exist)
- Permission checks (e.g., the API key must have `messages:write` scope)
- Rate and quota checks

### Validation Error Format

When a request has multiple validation failures, they are returned as an array inside `details.errors`:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "Request validation failed",
    "type": "validation",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/invalid_request",
    "details": {
      "errors": [
        {
          "field": "to",
          "message": "Must be a valid email address",
          "value": "not-an-email"
        },
        {
          "field": "subject",
          "message": "Must be between 1 and 998 characters",
          "value": ""
        },
        {
          "field": "body_html",
          "message": "Either body_text or body_html must be provided",
          "value": null
        }
      ]
    }
  }
}
```

### Field Error Object

| Field | Type | Description |
|-------|------|-------------|
| `field` | string | The JSON path to the field that failed validation. Nested fields use dot notation: `attachments.0.filename`. |
| `message` | string | Human-readable description of the validation rule that was violated. |
| `value` | any | The value that was submitted (may be `null` if the field was missing). Sensitive values (passwords, tokens) are redacted to `"[REDACTED]"`. |

### Common Validation Rules

| Field | Rule | Error Message |
|-------|------|---------------|
| `to` | RFC 5322 email, max 50 recipients | "Must be a valid email address" / "Maximum 50 recipients" |
| `subject` | 1--998 characters | "Must be between 1 and 998 characters" |
| `body_text` / `body_html` | At least one required for send | "Either body_text or body_html must be provided" |
| `display_name` | 1--200 characters, no control chars | "Must be between 1 and 200 characters" |
| `limit` | Integer, 1--100 | "Must be an integer between 1 and 100" |
| `page_token` | Valid Base64, not expired | "Invalid or expired page token" |
| `webhook_url` | Valid HTTPS URL | "Must be a valid HTTPS URL" |
| `inbox_address` | Valid local part, 1--64 chars | "Must be a valid email local part" |

---

## 6. API Versioning

### Current Version

The current and only active version is **v1**, included in the URL path:

```
https://api.agentmail.aws/v1/inboxes
https://api.agentmail.aws/v1/inboxes/{inbox_id}/messages
```

### Versioning Strategy

AgentMail uses **URL path versioning** (not header-based). The version is the first path segment after the base URL.

**Why path versioning:**

- Explicit and visible in every request
- Easy to route at the infrastructure level (API Gateway stages)
- No ambiguity about which version is being called
- Works naturally with API Gateway deployments

### What Constitutes a Breaking Change

The following are **breaking changes** and require a new major version:

- Removing a field from a response
- Renaming a field in a request or response
- Changing the type of a field (e.g., string to number)
- Removing an endpoint
- Changing the semantics of an existing field
- Changing a required field to optional (or vice versa) in requests
- Changing error codes for existing failure modes

The following are **non-breaking changes** and are made within the current version:

- Adding new fields to response objects
- Adding new optional parameters to requests
- Adding new endpoints
- Adding new error codes for new failure modes
- Adding new enum values (clients should handle unknown enum values gracefully)
- Relaxing validation constraints (e.g., increasing a max length)

### Version Lifecycle

Each API version goes through three phases:

```
Active ──────────> Deprecated ──────────> Sunset (Removed)
                   (6 month notice)       (12 months after deprecation)
```

1. **Active:** Fully supported. Receives new features, bug fixes, and security patches.
2. **Deprecated:** Still functional, but no new features. Clients receive deprecation headers on every response. A 6-month migration window is provided.
3. **Sunset:** The version is removed. Requests return `410 Gone` with a message directing clients to the current version.

### Deprecation Headers

When a version or endpoint is deprecated, every response includes these headers:

```
Sunset: Sat, 01 Jan 2028 00:00:00 GMT
Deprecation: true
Link: <https://docs.agentmail.aws/migration/v1-to-v2>; rel="successor-version"
```

| Header | Value | Description |
|--------|-------|-------------|
| `Sunset` | HTTP date | The date after which this version/endpoint will stop working. |
| `Deprecation` | `true` | Indicates this version/endpoint is deprecated. |
| `Link` | URL with `rel` | Link to the migration guide for the replacement. |

### SDK Version Handling

The SDKs pin to a specific API version in their configuration:

```python
# Python
client = agentmail.Client(api_key="ak_live_xxx")
# The SDK internally uses v1. When v2 is available, a new major SDK version will be released.
```

```javascript
// Node.js
const client = new AgentMail({ apiKey: "ak_live_xxx" });
// Same -- API version is embedded in the SDK. Major SDK version bump = major API version bump.
```

---

## 7. Rate Limit Headers

Every API response -- both success and error -- includes rate limit headers so clients can proactively manage their request rate.

### Headers on Every Response

```
X-RateLimit-Limit: 50
X-RateLimit-Remaining: 48
X-RateLimit-Reset: 1712764260
X-RateLimit-Policy: 50;w=1
X-Request-Id: req_01HXYZ...
```

| Header | Type | Description |
|--------|------|-------------|
| `X-RateLimit-Limit` | integer | The maximum number of requests allowed in the current window. |
| `X-RateLimit-Remaining` | integer | The number of requests remaining in the current window. |
| `X-RateLimit-Reset` | Unix timestamp | When the current window resets (seconds since epoch). |
| `X-RateLimit-Policy` | string | The rate limit policy in the format `{limit};w={window_seconds}`. Example: `50;w=1` means 50 requests per 1-second window. |
| `X-Request-Id` | string | Unique request identifier. Matches `request_id` in error responses. |

### Additional Headers on 429 Responses

When a request is rate limited, the response includes one additional header:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 2
X-RateLimit-Limit: 50
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1712764260
X-RateLimit-Policy: 50;w=1
Content-Type: application/json

{
  "error": {
    "code": "rate_limited",
    "message": "Too many requests. Retry after 2 seconds.",
    "type": "rate_limit",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/rate_limited",
    "details": {
      "retry_after": 2,
      "limit": 50,
      "window": 1
    }
  }
}
```

| Header | Type | Description |
|--------|------|-------------|
| `Retry-After` | integer | Number of seconds the client should wait before retrying. Only present on 429 responses. |

### Quota Exceeded Response

When a monthly or daily quota is exhausted, the response structure is slightly different:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 86400
X-RateLimit-Limit: 50000
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1714521600
Content-Type: application/json

{
  "error": {
    "code": "quota_exceeded",
    "message": "Monthly request quota of 50,000 exceeded. Resets at 2026-05-01T00:00:00Z.",
    "type": "rate_limit",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/quota_exceeded",
    "details": {
      "quota_type": "monthly_requests",
      "current": 50000,
      "limit": 50000,
      "resets_at": "2026-05-01T00:00:00Z"
    },
    "upgrade_url": "https://console.agentmail.aws/dashboard/usage"
  }
}
```

### Client-Side Rate Limit Handling

SDKs should implement the following algorithm:

1. Before each request, check `X-RateLimit-Remaining`. If `0`, wait until `X-RateLimit-Reset`.
2. On a `429` response, read `Retry-After` and wait that many seconds before retrying.
3. Use jitter: add a random delay of 0--500ms to prevent thundering herd when many clients back off simultaneously.
4. Cap retries: SDKs should retry a maximum of 3 times for rate limit errors, then surface the error to the caller.

---

## 8. Request/Response Conventions

### Content Type

All request and response bodies are `application/json` unless explicitly documented otherwise. The exceptions are:

| Endpoint | Content-Type | Notes |
|----------|-------------|-------|
| `GET /v1/inboxes/{id}/messages/{id}/raw` | `message/rfc822` | Raw RFC 822 email |
| `GET /v1/inboxes/{id}/messages/{id}/attachments/{id}` | varies | The MIME type of the attachment |
| `POST /v1/inboxes/{id}/messages/send` (multipart) | `multipart/form-data` | When sending with binary attachments |

### Timestamps

All timestamps are **ISO 8601 in UTC**, with millisecond precision:

```
2026-04-10T14:30:00.000Z
```

- The API always returns timestamps in this format.
- The API accepts timestamps with or without milliseconds, and with `Z` or `+00:00` as the UTC designator.
- Non-UTC timestamps are rejected with `400 invalid_parameter`.

### Resource IDs

All resource IDs are prefixed strings using ULID (Universally Unique Lexicographically Sortable Identifier) as the unique component. ULIDs are 26-character Crockford Base32 strings that encode creation time, enabling natural chronological sorting.

| Resource | Prefix | Example |
|----------|--------|---------|
| Organization | `org_` | `org_01HXYZ1234567890ABCDEFGHJK` |
| Inbox | `inb_` | `inb_01HXYW9876543210ZYXWVUTSRQ` |
| Message | `msg_` | `msg_01HXZ01234567890MNOPQRSTUV` |
| Thread | `thr_` | `thr_01HXYA9876543210FEDCBA0987` |
| Draft | `drf_` | `drf_01HXYB1234567890GHIJKLMNOP` |
| Domain | `dom_` | `dom_01HXYC9876543210QRSTUVWXYZ` |
| Webhook | `whk_` | `whk_01HXYD1234567890ABCDEFGHJK` |
| API Key | `key_` | `key_01HXYE9876543210MNOPQRSTUV` |
| Pod | `pod_` | `pod_01HXYF1234567890ZYXWVUTSRQ` |
| Request | `req_` | `req_01HXYG9876543210FEDCBA0987` |

### Null Handling

- **Null fields are omitted from responses.** If a message has no `cc` recipients, the `cc` field is simply absent from the JSON, not present as `null`.
- **Empty arrays are included.** If an inbox has no webhooks, the response includes `"webhooks": []`, not an omitted field.
- **Empty strings are treated as missing.** Submitting `"subject": ""` is equivalent to omitting `subject` and triggers `missing_parameter` if `subject` is required.

### Boolean Fields

Boolean fields are always `true` or `false` (JSON booleans). The API rejects string representations (`"true"`, `"false"`) and numeric representations (`1`, `0`) with `400 invalid_parameter`.

### Response Envelopes

**List responses** are always wrapped:

```json
{
  "data": [ /* array of resource objects */ ],
  "has_more": true,
  "next_page_token": "eyJ..."
}
```

**Single resource responses** are returned directly (not wrapped):

```json
{
  "id": "inb_01HXYZ...",
  "display_name": "Support Inbox",
  "address": "support@acme.agentmail.aws",
  "created_at": "2026-04-10T14:30:00.000Z"
}
```

**Create responses** return the created resource directly with a `201 Created` status and a `Location` header:

```
HTTP/1.1 201 Created
Location: /v1/inboxes/inb_01HXYZ...
Content-Type: application/json

{
  "id": "inb_01HXYZ...",
  "display_name": "Support Inbox",
  ...
}
```

**Delete responses** return `204 No Content` with an empty body.

### Request Size Limits

| Limit | Value | Notes |
|-------|-------|-------|
| Request body (JSON) | 6 MB | API Gateway payload limit |
| Request body (multipart) | 25 MB | For attachment uploads on paid tiers |
| URL length | 8,192 characters | API Gateway URL limit |
| Header size | 10 KB total | All headers combined |
| Query string | 4,096 characters | After URL encoding |

---

## 9. Webhook Signature Verification

When AgentMail delivers a webhook event to your endpoint, the request includes a signature header that allows you to verify the payload was sent by AgentMail and has not been tampered with.

### Signature Header

```
X-AgentMail-Signature: t=1712764260,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd
```

The header contains two components separated by a comma:

| Component | Description |
|-----------|-------------|
| `t` | Unix timestamp (seconds) of when the signature was generated. |
| `v1` | HMAC-SHA256 signature of the payload. |

### Verification Algorithm

1. **Extract** the timestamp (`t`) and signature (`v1`) from the `X-AgentMail-Signature` header.
2. **Construct** the signed payload by concatenating: `{timestamp}.{raw_request_body}`.
3. **Compute** the HMAC-SHA256 of the signed payload using your webhook secret as the key.
4. **Compare** the computed signature with the `v1` value from the header using a constant-time comparison function.
5. **Validate** the timestamp: reject the webhook if the timestamp is more than 5 minutes old (to prevent replay attacks).

### Python

```python
import hashlib
import hmac
import time


def verify_webhook(payload: bytes, signature_header: str, webhook_secret: str) -> bool:
    """
    Verify an AgentMail webhook signature.

    Args:
        payload: Raw request body as bytes.
        signature_header: Value of the X-AgentMail-Signature header.
        webhook_secret: Your webhook signing secret (whsec_xxx).

    Returns:
        True if the signature is valid and the timestamp is fresh.

    Raises:
        ValueError: If the signature is invalid or the timestamp is stale.
    """
    # Parse the signature header
    elements = dict(pair.split("=", 1) for pair in signature_header.split(","))
    timestamp = elements.get("t")
    signature = elements.get("v1")

    if not timestamp or not signature:
        raise ValueError("Invalid signature header format")

    # Check timestamp freshness (5 minute tolerance)
    current_time = int(time.time())
    if abs(current_time - int(timestamp)) > 300:
        raise ValueError(
            f"Timestamp is too old: {timestamp} (current: {current_time})"
        )

    # Compute expected signature
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(
        webhook_secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Signature mismatch")

    return True


# Usage in a Flask app
from flask import Flask, request, abort

app = Flask(__name__)
WEBHOOK_SECRET = "whsec_xxx"


@app.route("/webhooks/agentmail", methods=["POST"])
def handle_webhook():
    try:
        verify_webhook(
            payload=request.get_data(),
            signature_header=request.headers.get("X-AgentMail-Signature", ""),
            webhook_secret=WEBHOOK_SECRET,
        )
    except ValueError as e:
        abort(400, str(e))

    event = request.get_json()
    print(f"Received event: {event['type']}")
    return "", 200
```

### Node.js

```javascript
const crypto = require("crypto");

/**
 * Verify an AgentMail webhook signature.
 *
 * @param {Buffer} payload - Raw request body.
 * @param {string} signatureHeader - Value of X-AgentMail-Signature header.
 * @param {string} webhookSecret - Your webhook signing secret.
 * @returns {boolean} True if valid.
 * @throws {Error} If invalid or stale.
 */
function verifyWebhook(payload, signatureHeader, webhookSecret) {
  // Parse the signature header
  const elements = Object.fromEntries(
    signatureHeader.split(",").map((pair) => pair.split("=", 2))
  );
  const timestamp = elements.t;
  const signature = elements.v1;

  if (!timestamp || !signature) {
    throw new Error("Invalid signature header format");
  }

  // Check timestamp freshness (5 minute tolerance)
  const currentTime = Math.floor(Date.now() / 1000);
  if (Math.abs(currentTime - parseInt(timestamp, 10)) > 300) {
    throw new Error(`Timestamp is too old: ${timestamp}`);
  }

  // Compute expected signature
  const signedPayload = Buffer.concat([
    Buffer.from(`${timestamp}.`),
    payload,
  ]);
  const expected = crypto
    .createHmac("sha256", webhookSecret)
    .update(signedPayload)
    .digest("hex");

  // Constant-time comparison
  if (!crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature))) {
    throw new Error("Signature mismatch");
  }

  return true;
}

// Usage in an Express app
const express = require("express");
const app = express();

const WEBHOOK_SECRET = "whsec_xxx";

app.post(
  "/webhooks/agentmail",
  express.raw({ type: "application/json" }),
  (req, res) => {
    try {
      verifyWebhook(
        req.body,
        req.headers["x-agentmail-signature"] || "",
        WEBHOOK_SECRET
      );
    } catch (err) {
      return res.status(400).json({ error: err.message });
    }

    const event = JSON.parse(req.body);
    console.log(`Received event: ${event.type}`);
    res.status(200).end();
  }
);
```

### Go

```go
package webhook

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
)

// VerifyWebhook verifies an AgentMail webhook signature.
func VerifyWebhook(payload []byte, signatureHeader, webhookSecret string) error {
	// Parse the signature header
	elements := make(map[string]string)
	for _, pair := range strings.Split(signatureHeader, ",") {
		parts := strings.SplitN(pair, "=", 2)
		if len(parts) == 2 {
			elements[parts[0]] = parts[1]
		}
	}

	timestamp, ok := elements["t"]
	if !ok {
		return fmt.Errorf("missing timestamp in signature header")
	}
	signature, ok := elements["v1"]
	if !ok {
		return fmt.Errorf("missing signature in signature header")
	}

	// Check timestamp freshness (5 minute tolerance)
	ts, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil {
		return fmt.Errorf("invalid timestamp: %w", err)
	}
	now := time.Now().Unix()
	if math.Abs(float64(now-ts)) > 300 {
		return fmt.Errorf("timestamp is too old: %d (current: %d)", ts, now)
	}

	// Compute expected signature
	signedPayload := fmt.Sprintf("%s.%s", timestamp, string(payload))
	mac := hmac.New(sha256.New, []byte(webhookSecret))
	mac.Write([]byte(signedPayload))
	expected := hex.EncodeToString(mac.Sum(nil))

	// Constant-time comparison
	if !hmac.Equal([]byte(expected), []byte(signature)) {
		return fmt.Errorf("signature mismatch")
	}

	return nil
}
```

### Ruby

```ruby
require "openssl"

module AgentMail
  class WebhookVerifier
    TOLERANCE = 300 # 5 minutes in seconds

    def initialize(webhook_secret)
      @webhook_secret = webhook_secret
    end

    # Verify an AgentMail webhook signature.
    #
    # @param payload [String] Raw request body.
    # @param signature_header [String] Value of X-AgentMail-Signature header.
    # @return [Boolean] True if valid.
    # @raise [SignatureVerificationError] If invalid or stale.
    def verify(payload, signature_header)
      elements = signature_header.split(",").each_with_object({}) do |pair, hash|
        key, value = pair.split("=", 2)
        hash[key] = value
      end

      timestamp = elements["t"]
      signature = elements["v1"]

      raise SignatureVerificationError, "Invalid header format" unless timestamp && signature

      # Check timestamp freshness
      current_time = Time.now.to_i
      if (current_time - timestamp.to_i).abs > TOLERANCE
        raise SignatureVerificationError, "Timestamp too old: #{timestamp}"
      end

      # Compute expected signature
      signed_payload = "#{timestamp}.#{payload}"
      expected = OpenSSL::HMAC.hexdigest("SHA256", @webhook_secret, signed_payload)

      # Constant-time comparison
      unless OpenSSL.secure_compare(expected, signature)
        raise SignatureVerificationError, "Signature mismatch"
      end

      true
    end
  end

  class SignatureVerificationError < StandardError; end
end

# Usage in a Sinatra app
require "sinatra"

WEBHOOK_SECRET = "whsec_xxx"
verifier = AgentMail::WebhookVerifier.new(WEBHOOK_SECRET)

post "/webhooks/agentmail" do
  payload = request.body.read
  signature = request.env["HTTP_X_AGENTMAIL_SIGNATURE"] || ""

  begin
    verifier.verify(payload, signature)
  rescue AgentMail::SignatureVerificationError => e
    halt 400, { error: e.message }.to_json
  end

  event = JSON.parse(payload)
  puts "Received event: #{event['type']}"
  status 200
end
```

### Security Notes

1. **Always verify signatures in production.** Skipping verification makes your endpoint vulnerable to forged webhook events.
2. **Use the raw request body.** Do not parse the JSON and re-serialize it for verification. Parsing can change whitespace, key ordering, or encoding, which would invalidate the signature.
3. **Reject stale timestamps.** The 5-minute tolerance prevents replay attacks where an attacker captures a valid webhook and re-sends it later.
4. **Constant-time comparison is mandatory.** Using `==` for string comparison leaks timing information that can be exploited to forge signatures.
5. **Store your webhook secret securely.** Treat it like an API key. Use environment variables or a secrets manager, never hard-code it in source.

---

## 10. SDK Error Handling Patterns

The AgentMail SDKs provide structured error classes that map directly to the API error codes. All SDK errors extend a base class, allowing both broad and specific error handling.

### Python SDK

**Error Hierarchy:**

```
AgentMailError (base)
├── AuthenticationError          (401)
│   ├── InvalidApiKeyError       (invalid_api_key)
│   └── ExpiredTokenError        (expired_token)
├── AuthorizationError           (403)
│   ├── InsufficientScopeError   (insufficient_scope)
│   ├── FeatureNotAvailableError (feature_not_available)
│   └── OrganizationDisabledError(organization_disabled)
├── NotFoundError                (404)
│   ├── InboxNotFoundError       (inbox_not_found)
│   ├── MessageNotFoundError     (message_not_found)
│   └── ThreadNotFoundError      (thread_not_found)
├── ValidationError              (400)
├── ConflictError                (409)
├── RateLimitError               (429)
│   ├── QuotaExceededError       (quota_exceeded)
│   └── SendingSuspendedError    (sending_suspended)
└── ServerError                  (5xx)
```

**Broad error handling:**

```python
import agentmail
from agentmail.errors import AgentMailError, RateLimitError, NotFoundError

client = agentmail.Client(api_key="ak_live_xxx")

try:
    inbox = client.inboxes.create(display_name="Support")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after} seconds.")
    print(f"Limit: {e.details.get('limit')}")
except NotFoundError as e:
    print(f"Resource not found: {e.message}")
except AgentMailError as e:
    # Catch-all for any API error
    print(f"API error [{e.code}]: {e.message}")
    print(f"Request ID: {e.request_id}")
    print(f"HTTP status: {e.status}")
```

**Specific error handling:**

```python
from agentmail.errors import (
    InvalidApiKeyError,
    QuotaExceededError,
    InboxNotFoundError,
    ValidationError,
)

try:
    message = client.inboxes.messages.send(
        inbox_id="inb_01HXYZ...",
        to=["user@example.com"],
        subject="Hello",
        body_text="World",
    )
except InvalidApiKeyError:
    # Re-authenticate or fail fast
    raise SystemExit("API key is invalid. Check your configuration.")
except QuotaExceededError as e:
    print(f"Quota exceeded. Resets at {e.details['resets_at']}")
    print(f"Upgrade at: {e.upgrade_url}")
except InboxNotFoundError as e:
    print(f"Inbox does not exist: {e.message}")
except ValidationError as e:
    # Access individual field errors
    for field_error in e.details.get("errors", []):
        print(f"  {field_error['field']}: {field_error['message']}")
```

**Error object properties:**

```python
except AgentMailError as e:
    e.code        # "quota_exceeded" (str)
    e.message     # "Monthly email limit..." (str)
    e.type        # "rate_limit" (str)
    e.status      # 429 (int)
    e.request_id  # "req_01HXYZ..." (str)
    e.details     # {"current": 1000, "limit": 1000, ...} (dict)
    e.param       # "max_emails_per_month" (str or None)
    e.upgrade_url # "https://console.agentmail.aws/..." (str or None)
```

### Node.js SDK

**Error Hierarchy:**

```
AgentMailError (base)
├── AuthenticationError
├── AuthorizationError
├── NotFoundError
├── ValidationError
├── ConflictError
├── RateLimitError
└── ServerError
```

**Error handling:**

```javascript
const AgentMail = require("agentmail");
const {
  AgentMailError,
  RateLimitError,
  NotFoundError,
  ValidationError,
} = AgentMail.errors;

const client = new AgentMail({ apiKey: "ak_live_xxx" });

try {
  const inbox = await client.inboxes.create({ displayName: "Support" });
} catch (err) {
  if (err instanceof RateLimitError) {
    console.log(`Rate limited. Retry after ${err.retryAfter} seconds.`);
    console.log(`Limit: ${err.details?.limit}`);
  } else if (err instanceof NotFoundError) {
    console.log(`Resource not found: ${err.message}`);
  } else if (err instanceof ValidationError) {
    // Access individual field errors
    for (const fieldError of err.details?.errors || []) {
      console.log(`  ${fieldError.field}: ${fieldError.message}`);
    }
  } else if (err instanceof AgentMailError) {
    console.log(`API error [${err.code}]: ${err.message}`);
    console.log(`Request ID: ${err.requestId}`);
    console.log(`HTTP status: ${err.status}`);
  } else {
    // Network error, timeout, etc.
    throw err;
  }
}
```

**Error object properties:**

```javascript
catch (err) {
  err.code;        // "quota_exceeded" (string)
  err.message;     // "Monthly email limit..." (string)
  err.type;        // "rate_limit" (string)
  err.status;      // 429 (number)
  err.requestId;   // "req_01HXYZ..." (string)
  err.details;     // { current: 1000, limit: 1000, ... } (object)
  err.param;       // "max_emails_per_month" (string | undefined)
  err.upgradeUrl;  // "https://console.agentmail.aws/..." (string | undefined)
  err.retryAfter;  // 2 (number, only on RateLimitError)
}
```

### Automatic Retry Behavior

Both SDKs include built-in retry logic with exponential backoff. Retries are **enabled by default** and can be configured.

**Retryable conditions:**

| Condition | Retried | Notes |
|-----------|:-------:|-------|
| HTTP 429 (rate limited) | Yes | Waits for `Retry-After` seconds plus jitter. |
| HTTP 500 (internal error) | Yes | Exponential backoff. |
| HTTP 502 (upstream error) | Yes | Exponential backoff. |
| HTTP 503 (service unavailable) | Yes | Waits for `Retry-After` if present, else exponential backoff. |
| HTTP 504 (timeout) | Yes | Exponential backoff. |
| Network error (ECONNRESET, etc.) | Yes | Exponential backoff. |
| HTTP 400 (validation) | No | Client error; retrying will not help. |
| HTTP 401 (auth) | No | Fix credentials first. |
| HTTP 403 (forbidden) | No | Fix permissions first. |
| HTTP 404 (not found) | No | Resource does not exist. |
| HTTP 409 (conflict) | No | Resolve the conflict first. |
| HTTP 422 (unprocessable) | No | Fix the request first. |

**Python retry configuration:**

```python
client = agentmail.Client(
    api_key="ak_live_xxx",
    max_retries=3,           # Default: 3. Set to 0 to disable retries.
    retry_backoff_factor=0.5, # Default: 0.5. Base delay multiplier.
    retry_backoff_max=30,     # Default: 30. Maximum delay in seconds.
)

# Retry delays (with default settings):
# Attempt 1: immediate
# Attempt 2: 0.5s + jitter
# Attempt 3: 1.0s + jitter
# Attempt 4: 2.0s + jitter (if max_retries=4)
```

**Node.js retry configuration:**

```javascript
const client = new AgentMail({
  apiKey: "ak_live_xxx",
  maxRetries: 3, // Default: 3. Set to 0 to disable.
  retryBackoffFactor: 0.5, // Default: 0.5.
  retryBackoffMax: 30, // Default: 30 seconds.
});
```

**Backoff formula:**

```
delay = min(retry_backoff_factor * (2 ^ attempt), retry_backoff_max) + random(0, 0.5)
```

Where `attempt` is zero-indexed (first retry is attempt 0). The random jitter of 0--500ms prevents thundering herd effects.

**Disabling retries for a single request:**

```python
# Python: override per-request
inbox = client.inboxes.create(
    display_name="Support",
    request_options={"max_retries": 0},
)
```

```javascript
// Node.js: override per-request
const inbox = await client.inboxes.create(
  { displayName: "Support" },
  { maxRetries: 0 }
);
```

### Timeout Configuration

Both SDKs allow configuring request timeouts:

```python
# Python
client = agentmail.Client(
    api_key="ak_live_xxx",
    timeout=30.0,  # Default: 60 seconds. Per-request timeout.
)
```

```javascript
// Node.js
const client = new AgentMail({
  apiKey: "ak_live_xxx",
  timeout: 30000, // Default: 60000ms. Per-request timeout.
});
```

When a timeout is hit, the SDK raises a `TimeoutError` (Python) or rejects with an `AgentMailTimeoutError` (Node.js). These are **not** subclasses of `AgentMailError` because they are client-side errors, not API errors.

---

## Appendix A: Quick Reference -- HTTP Status Codes

| Status | Meaning | Retryable | Action |
|:------:|---------|:---------:|--------|
| 200 | Success | -- | Process the response. |
| 201 | Created | -- | Resource was created. Check `Location` header. |
| 204 | No Content | -- | Delete was successful. No body. |
| 400 | Bad Request | No | Fix the request and resend. |
| 401 | Unauthorized | No | Check API key / token. |
| 403 | Forbidden | No | Check permissions / tier / domain verification. |
| 404 | Not Found | No | Verify the resource ID. |
| 409 | Conflict | No | Resolve the conflict (duplicate ID, claimed domain). |
| 422 | Unprocessable | No | Fix the business logic issue. |
| 429 | Rate Limited | Yes | Wait for `Retry-After`, then retry. |
| 500 | Internal Error | Yes | Retry with backoff. Report `request_id` if persistent. |
| 502 | Bad Gateway | Yes | Retry with backoff. |
| 503 | Unavailable | Yes | Wait for `Retry-After`, then retry. |
| 504 | Timeout | Yes | Retry with backoff. |

---

## Appendix B: ID Prefix Quick Reference

| Prefix | Resource | Example |
|--------|----------|---------|
| `org_` | Organization | `org_01HXYZ...` |
| `inb_` | Inbox | `inb_01HXYZ...` |
| `msg_` | Message | `msg_01HXYZ...` |
| `thr_` | Thread | `thr_01HXYZ...` |
| `drf_` | Draft | `drf_01HXYZ...` |
| `dom_` | Domain | `dom_01HXYZ...` |
| `whk_` | Webhook | `whk_01HXYZ...` |
| `key_` | API Key | `key_01HXYZ...` |
| `pod_` | Pod | `pod_01HXYZ...` |
| `req_` | Request ID | `req_01HXYZ...` |
| `whsec_` | Webhook Secret | `whsec_01HXYZ...` |

---

## Appendix C: Error Response Examples

### Validation Error (Multiple Fields)

```
POST /v1/inboxes/inb_01HXYZ.../messages/send
Content-Type: application/json

{
  "to": ["not-an-email"],
  "subject": "",
  "body_text": null
}
```

```json
HTTP/1.1 400 Bad Request

{
  "error": {
    "code": "invalid_request",
    "message": "Request validation failed",
    "type": "validation",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/invalid_request",
    "details": {
      "errors": [
        {"field": "to.0", "message": "Must be a valid email address", "value": "not-an-email"},
        {"field": "subject", "message": "Must be between 1 and 998 characters", "value": ""},
        {"field": "body_text", "message": "Either body_text or body_html must be provided", "value": null}
      ]
    }
  }
}
```

### Authentication Error

```
GET /v1/inboxes
(no authentication header)
```

```json
HTTP/1.1 401 Unauthorized

{
  "error": {
    "code": "authentication_required",
    "message": "No API key or JWT token was provided. Include an x-api-key or Authorization: Bearer header.",
    "type": "auth",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/authentication_required"
  }
}
```

### Rate Limit Error

```json
HTTP/1.1 429 Too Many Requests
Retry-After: 2
X-RateLimit-Remaining: 0

{
  "error": {
    "code": "rate_limited",
    "message": "Too many requests. Retry after 2 seconds.",
    "type": "rate_limit",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/rate_limited",
    "details": {
      "retry_after": 2,
      "limit": 50,
      "window": 1
    }
  }
}
```

### Quota Exceeded with Upgrade URL

```json
HTTP/1.1 429 Too Many Requests

{
  "error": {
    "code": "quota_exceeded",
    "message": "Monthly email limit of 1,000 exceeded. Upgrade to Pro for 10,000 emails/month.",
    "type": "rate_limit",
    "param": "max_emails_per_month",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/quota_exceeded",
    "details": {
      "current": 1000,
      "limit": 1000,
      "resets_at": "2026-05-01T00:00:00Z"
    },
    "upgrade_url": "https://console.agentmail.aws/dashboard/usage"
  }
}
```

### Conflict Error (Duplicate Inbox Address)

```json
HTTP/1.1 409 Conflict

{
  "error": {
    "code": "already_exists",
    "message": "An inbox with the address support@acme.agentmail.aws already exists.",
    "type": "conflict",
    "param": "address",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/already_exists",
    "details": {
      "conflicting_field": "address",
      "conflicting_value": "support@acme.agentmail.aws"
    }
  }
}
```

### Server Error

```json
HTTP/1.1 500 Internal Server Error

{
  "error": {
    "code": "internal_error",
    "message": "An unexpected error occurred. Please try again or contact support if the issue persists.",
    "type": "server",
    "request_id": "req_01HXYZ...",
    "documentation_url": "https://docs.agentmail.aws/errors/internal_error"
  }
}
```
