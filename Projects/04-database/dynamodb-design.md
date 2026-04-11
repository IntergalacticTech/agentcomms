# DynamoDB Design

Complete single-table design for AgentMail, including entity layouts, GSI strategy, access patterns, capacity planning, streams, and backup strategy.

---

## Design Rationale

### Why Single-Table DynamoDB

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **Single-table DynamoDB** | All access patterns in one table; transactional writes across entities; predictable single-digit ms latency; pay-per-request | Complex key design; steep learning curve; no ad-hoc queries | **Selected** |
| Multi-table DynamoDB | Simpler per-table design; independent scaling | No cross-table transactions; more tables to manage; higher aggregate cost | Rejected |
| Aurora Serverless v2 | Flexible queries; relational joins; familiar SQL | Connection pooling complexity; per-hour minimum cost even at zero traffic; cold start latency | Rejected |
| Aurora + DynamoDB hybrid | Best of both | Operational complexity; data sync challenges; dual write risks | Rejected |

The single-table design is optimal because:

1. **All access patterns are known upfront.** AgentMail's API defines every query the database must support. There are no ad-hoc reporting needs (those go to OpenSearch).
2. **Cross-entity transactions are needed.** Creating an inbox must atomically update the pod's inbox count. Sending a message must create the message and update the thread.
3. **Cost at zero traffic is $0.** On-demand DynamoDB charges only for reads and writes, unlike Aurora which has a minimum hourly cost.
4. **Latency is guaranteed.** Single-digit millisecond reads regardless of table size.

### Table Configuration

| Property | Value |
|----------|-------|
| Table name | `agentmail` |
| Partition key | `PK` (String) |
| Sort key | `SK` (String) |
| Billing mode | On-demand (switch to provisioned at ~$10K/month DynamoDB spend) |
| Encryption | AWS-owned key (default), KMS for enterprise |
| Point-in-time recovery | Enabled |
| Deletion protection | Enabled |
| Stream | Enabled (NEW_AND_OLD_IMAGES) |
| Table class | Standard |

---

## Entity Layouts

### Organization

```
PK:              ORG#{org_id}
SK:              ORG#{org_id}
entity_type:     Organization
id:              {org_id}                        # ULID
name:            "Acme Corp"
email:           "admin@example.com"
tier:            "pro"                           # SaaS tiers: free | pro | business | scale
                                                 # Marketplace tiers: starter | growth | scale | enterprise
status:          "active"                        # active | suspended | cancelled
marketplace_customer_id: "cust_abc123"           # AWS Marketplace customer ID
subscription_id: "sub_xyz789"                    # AWS Marketplace subscription
settings: {
  default_domain:            "mail.acme.com"
  webhook_secret:            "whsec_xxxx"
  retention_days:            365
  ai_categorization_enabled: true
  max_attachment_size_mb:    25
}
quotas: {
  max_inboxes:          100000
  max_messages_per_day: 100000
  max_api_keys:         50
  max_pods:             100
  max_domains:          20
  max_webhooks:         50
}
usage: {
  inboxes:    1247
  api_keys:   3
  pods:       2
  domains:    1
}
created_at:      "2026-01-15T09:00:00.000Z"
updated_at:      "2026-04-10T12:00:00.000Z"

GSI1PK:          TIER#{tier}
GSI1SK:          ORG#{org_id}
```

### API Key

```
PK:              ORG#{org_id}
SK:              APIKEY#{key_id}
entity_type:     ApiKey
id:              {key_id}                        # ULID
org_id:          {org_id}
name:            "Production Key"
prefix:          "am_live_7kB3"                  # First 4 chars for identification
key_hash:        "a1b2c3d4...sha256"             # SHA-256 of plaintext key
environment:     "live"                          # live | test
scope:           "org"                           # org | pod | inbox
scope_resource_id: null                          # Pod or inbox ID when scoped
status:          "active"                        # active | revoked
last_used_at:    "2026-04-10T14:00:00.000Z"
created_at:      "2026-01-15T09:00:00.000Z"
expires_at:      null                            # Optional expiry

GSI1PK:          APIKEY#{key_hash}               # Lookup by hash during auth
GSI1SK:          APIKEY#{key_id}
```

### Pod

```
PK:              ORG#{org_id}
SK:              POD#{pod_id}
entity_type:     Pod
id:              {pod_id}                        # ULID
org_id:          {org_id}
name:            "Customer Outreach"
description:     "Inboxes for customer outreach agents"
inbox_count:     342
settings: {
  default_domain:            "outreach.acme.com"
  ai_categorization_enabled: true
  retention_days:            180
}
created_at:      "2026-02-01T10:00:00.000Z"
updated_at:      "2026-04-08T16:45:00.000Z"

GSI1PK:          ORG#{org_id}#PODS
GSI1SK:          POD#{pod_id}
```

### Inbox

```
PK:              ORG#{org_id}
SK:              INBOX#{inbox_id}
entity_type:     Inbox
id:              {inbox_id}                      # ULID
org_id:          {org_id}
pod_id:          {pod_id}
email:           "agent-47@mail.acme.com"
display_name:    "Support Agent 47"
status:          "active"                        # active | paused | deleted
message_count:   1847
unread_count:    12
settings: {
  auto_reply_enabled:    false
  categorization_enabled: true
  spam_filter_level:     "normal"
  retention_days:        180
}
forwarding: {
  enabled:  false
  address:  null
}
created_at:      "2026-03-01T08:00:00.000Z"
updated_at:      "2026-04-10T14:00:00.000Z"
deleted_at:      null

GSI1PK:          POD#{pod_id}#INBOXES
GSI1SK:          INBOX#{inbox_id}
GSI2PK:          EMAIL#{email_address}           # Lookup by email for inbound routing
GSI2SK:          INBOX#{inbox_id}
```

### Message

```
PK:              INBOX#{inbox_id}
SK:              MSG#{message_id}
entity_type:     Message
id:              {message_id}                    # ULID (encodes receive time)
inbox_id:        {inbox_id}
org_id:          {org_id}
thread_id:       {thread_id}
direction:       "inbound"                       # inbound | outbound
from: {
  name:    "Jane Doe"
  address: "jane@example.com"
}
to:              [{ name, address }]
cc:              [{ name, address }]
bcc:             [{ name, address }]
reply_to:        [{ name, address }]
subject:         "Question about pricing"
snippet:         "Hi, I was wondering about..."  # First 200 chars, plain text
body_s3_key:     "bodies/{org_id}/{inbox_id}/{message_id}.json"
is_read:         false
is_starred:      false
is_spam:         false
is_trash:        false
labels:          ["inquiry"]
category:        "sales"                         # AI-assigned category
headers: {
  message_id:    "<abc123@example.com>"
  in_reply_to:   null
  references:    null
}
ses_message_id:  null                            # SES ID for outbound
attachment_count: 1
has_attachments: true
size_bytes:      24576
received_at:     "2026-04-10T14:30:00.000Z"
created_at:      "2026-04-10T14:30:00.000Z"

GSI1PK:          THREAD#{thread_id}              # Messages in a thread
GSI1SK:          MSG#{message_id}
GSI3PK:          ORG#{org_id}#MSGS               # Org-wide message listing
GSI3SK:          MSG#{message_id}                # ULID sorts chronologically
```

Note: `body_text` and `body_html` are stored in S3 (referenced by `body_s3_key`) to stay under DynamoDB's 400 KB item limit. The `snippet` field provides a preview without fetching from S3.

### Thread

```
PK:              INBOX#{inbox_id}
SK:              THREAD#{thread_id}
entity_type:     Thread
id:              {thread_id}                     # ULID
inbox_id:        {inbox_id}
org_id:          {org_id}
subject:         "Question about pricing"
snippet:         "Thanks, I'll look into this."
message_count:   3
unread_count:    1
participants:    [{ name, address }]
labels:          ["sales", "inquiry"]
category:        "sales"
is_read:         false
is_starred:      false
is_trash:        false
last_message_at: "2026-04-10T14:35:00.000Z"
created_at:      "2026-04-10T14:30:00.000Z"
updated_at:      "2026-04-10T14:35:00.000Z"

GSI1PK:          INBOX#{inbox_id}#THREADS
GSI1SK:          THREAD#{thread_id}
```

### Draft

```
PK:              INBOX#{inbox_id}
SK:              DRAFT#{draft_id}
entity_type:     Draft
id:              {draft_id}                      # ULID
inbox_id:        {inbox_id}
org_id:          {org_id}
thread_id:       null                            # If replying to a thread
in_reply_to_message_id: null
to:              [{ name, address }]
cc:              [{ name, address }]
bcc:             [{ name, address }]
subject:         "Follow-up"
body_text:       "Draft content..."
body_html:       "<p>Draft content...</p>"
attachments:     [{ id, filename, content_type, size, s3_key }]
created_at:      "2026-04-10T14:00:00.000Z"
updated_at:      "2026-04-10T14:20:00.000Z"

GSI1PK:          INBOX#{inbox_id}#DRAFTS
GSI1SK:          DRAFT#{draft_id}
```

### Domain

```
PK:              ORG#{org_id}
SK:              DOMAIN#{domain_id}
entity_type:     Domain
id:              {domain_id}                     # ULID
org_id:          {org_id}
domain:          "mail.acme.com"
status:          "verified"                      # pending | verifying | verified | failed
mx_verified:     true
spf_verified:    true
dkim_verified:   true
dmarc_verified:  true
catch_all_inbox_id: null
dns_records: {
  mx:    { type, name, value, verified }
  spf:   { type, name, value, verified }
  dkim:  [{ type, name, value, verified }]
  dmarc: { type, name, value, verified }
}
ses_identity_arn: "arn:aws:ses:us-east-1:123456789012:identity/mail.acme.com"
created_at:      "2026-02-01T10:00:00.000Z"
verified_at:     "2026-02-01T10:30:00.000Z"

GSI1PK:          DOMAIN#{domain_name}            # Lookup by domain name
GSI1SK:          DOMAIN#{domain_id}
```

### Webhook

```
PK:              ORG#{org_id}
SK:              WEBHOOK#{webhook_id}
entity_type:     Webhook
id:              {webhook_id}                    # ULID
org_id:          {org_id}
url:             "https://api.example.com/webhooks/agentmail"
events:          ["message.received", "message.sent"]
status:          "active"                        # active | paused | disabled
secret:          "whsec_xxxx"                    # HMAC signing secret
filter: {
  pod_ids:   ["01HXYZ..."]
  inbox_ids: []
}
delivery_stats: {
  total_delivered:   14523
  total_failed:      12
  last_delivered_at: "2026-04-10T14:30:00.000Z"
  last_failed_at:    "2026-04-09T03:12:00.000Z"
  consecutive_failures: 0
}
created_at:      "2026-02-15T10:00:00.000Z"
updated_at:      "2026-04-10T14:30:00.000Z"

GSI1PK:          ORG#{org_id}#WEBHOOKS
GSI1SK:          WEBHOOK#{webhook_id}
```

### List Entry

```
PK:              LIST#{list_id}
SK:              MEMBER#{email_address}
entity_type:     ListEntry
list_id:         {list_id}
address:         "subscriber1@example.com"
name:            "Subscriber One"
subscribed_at:   "2026-03-15T09:00:00.000Z"

---

PK:              ORG#{org_id}
SK:              LIST#{list_id}
entity_type:     List
id:              {list_id}                       # ULID
org_id:          {org_id}
name:            "Product Updates"
inbox_id:        {inbox_id}                      # Sending inbox
member_count:    4521
created_at:      "2026-03-01T10:00:00.000Z"
updated_at:      "2026-04-10T12:00:00.000Z"

GSI1PK:          ORG#{org_id}#LISTS
GSI1SK:          LIST#{list_id}
```

### Attachment

```
PK:              MSG#{message_id}
SK:              ATTACH#{attachment_id}
entity_type:     Attachment
id:              {attachment_id}                 # ULID
message_id:      {message_id}
inbox_id:        {inbox_id}
org_id:          {org_id}
filename:        "requirements.pdf"
content_type:    "application/pdf"
size:            245760                          # bytes
s3_bucket:       "agentmail-attachments-prod"
s3_key:          "attachments/{org_id}/{inbox_id}/{message_id}/{attachment_id}/{filename}"
checksum_sha256: "e3b0c44298fc..."
is_inline:       false
content_id:      null                            # CID for inline images
created_at:      "2026-04-10T14:30:00.000Z"
```

### WebSocket Connection

```
PK:              WSCONN#{connection_id}
SK:              WSCONN#{connection_id}
entity_type:     WebSocketConnection
connection_id:   {api_gateway_connection_id}
org_id:          {org_id}
key_id:          {api_key_id}
subscriptions:   ["inbox:01HXYZ...", "org:01HXYZ..."]
connected_at:    "2026-04-10T14:30:00.000Z"
last_ping_at:    "2026-04-10T14:35:00.000Z"
ttl:             1712766600                      # Auto-delete after 1 hour of no pings

GSI1PK:          ORG#{org_id}#WSCONNS
GSI1SK:          WSCONN#{connection_id}
GSI4PK:          WSSUB#inbox:01HXYZ...           # Lookup connections by subscription channel
GSI4SK:          WSCONN#{connection_id}
```

### Subscription (AWS Marketplace)

```
PK:              ORG#{org_id}
SK:              SUBSCRIPTION#{subscription_id}
entity_type:     Subscription
id:              {subscription_id}
org_id:          {org_id}
marketplace_customer_id: "cust_abc123"
product_code:    "agentmail-saas"
tier:            "pro"
status:          "active"                        # active | suspended | cancelled | expired
entitlements: {
  max_inboxes:          100000
  max_messages_per_day: 100000
  ai_tokens_per_month:  10000000
}
started_at:      "2026-01-15T09:00:00.000Z"
expires_at:      null
cancelled_at:    null
created_at:      "2026-01-15T09:00:00.000Z"
updated_at:      "2026-04-01T00:00:00.000Z"
```

### Categorization Config

```
PK:              ORG#{org_id}
SK:              CATCONFIG#{config_id}
entity_type:     CategorizationConfig
id:              {config_id}
org_id:          {org_id}
pod_id:          null                            # Optional: pod-level override
categories:      ["sales", "support", "billing", "spam", "newsletter", "other"]
prompt_template: "Classify the following email into one of these categories: {categories}..."
model_id:        "anthropic.claude-3-haiku-20240307-v1:0"
enabled:         true
created_at:      "2026-02-01T10:00:00.000Z"
updated_at:      "2026-03-15T12:00:00.000Z"
```

### Extraction Schema

```
PK:              ORG#{org_id}
SK:              EXTRACT#{schema_id}
entity_type:     ExtractionSchema
id:              {schema_id}
org_id:          {org_id}
pod_id:          null
name:            "Order Details"
schema: {
  type: "object"
  properties: {
    order_id:      { type: "string" }
    customer_name: { type: "string" }
    total:         { type: "number" }
    items:         { type: "array", items: { type: "string" } }
  }
}
prompt_template: "Extract the following fields from this email..."
model_id:        "anthropic.claude-3-haiku-20240307-v1:0"
enabled:         true
created_at:      "2026-02-01T10:00:00.000Z"
updated_at:      "2026-03-15T12:00:00.000Z"
```

### AI Usage

```
PK:              ORG#{org_id}
SK:              AIUSAGE#{date}#{usage_id}
entity_type:     AIUsage
id:              {usage_id}
org_id:          {org_id}
date:            "2026-04-10"
model_id:        "anthropic.claude-3-haiku-20240307-v1:0"
operation:       "categorization"                # categorization | extraction | search_embedding
input_tokens:    1247
output_tokens:   23
cost_usd:        0.00032
inbox_id:        {inbox_id}
message_id:      {message_id}
created_at:      "2026-04-10T14:30:00.000Z"
ttl:             1720569600                      # Auto-delete after 90 days

GSI5PK:          ORG#{org_id}#AIUSAGE#{date}
GSI5SK:          AIUSAGE#{usage_id}
```

---

## Global Secondary Indexes

### GSI1: Multi-Purpose Lookup

| Purpose | GSI1PK | GSI1SK |
|---------|--------|--------|
| Auth: API key by hash | `APIKEY#{key_hash}` | `APIKEY#{key_id}` |
| Domain by name | `DOMAIN#{domain_name}` | `DOMAIN#{domain_id}` |
| Pods in org | `ORG#{org_id}#PODS` | `POD#{pod_id}` |
| Inboxes in pod | `POD#{pod_id}#INBOXES` | `INBOX#{inbox_id}` |
| Threads in inbox | `INBOX#{inbox_id}#THREADS` | `THREAD#{thread_id}` |
| Messages in thread | `THREAD#{thread_id}` | `MSG#{message_id}` |
| Drafts in inbox | `INBOX#{inbox_id}#DRAFTS` | `DRAFT#{draft_id}` |
| Webhooks in org | `ORG#{org_id}#WEBHOOKS` | `WEBHOOK#{webhook_id}` |
| Lists in org | `ORG#{org_id}#LISTS` | `LIST#{list_id}` |
| WebSocket conns in org | `ORG#{org_id}#WSCONNS` | `WSCONN#{connection_id}` |
| Orgs by tier | `TIER#{tier}` | `ORG#{org_id}` |

**Projection:** ALL (all attributes projected to support diverse queries)

### GSI2: Email Address Routing

| Purpose | GSI2PK | GSI2SK |
|---------|--------|--------|
| Inbox by email address | `EMAIL#{email_address}` | `INBOX#{inbox_id}` |

**Projection:** KEYS_ONLY + `org_id`, `pod_id`, `status`

This GSI is critical for the inbound email path. When SES receives an email, the Lambda looks up the destination inbox by email address.

### GSI3: Organization-Wide Listings

| Purpose | GSI3PK | GSI3SK |
|---------|--------|--------|
| All messages in org | `ORG#{org_id}#MSGS` | `MSG#{message_id}` |

**Projection:** `inbox_id`, `thread_id`, `direction`, `from`, `subject`, `snippet`, `is_read`, `category`, `received_at`

Supports the org-wide message listing and filtering without scanning every inbox.

### GSI4: WebSocket Subscription Fan-Out

| Purpose | GSI4PK | GSI4SK |
|---------|--------|--------|
| Connections subscribing to a channel | `WSSUB#{channel}` | `WSCONN#{connection_id}` |

**Projection:** `connection_id`, `org_id`

When an event occurs (e.g., new message in inbox X), query GSI4 for `WSSUB#inbox:X` to find all WebSocket connections that need to be notified.

### GSI5: AI Usage Reporting

| Purpose | GSI5PK | GSI5SK |
|---------|--------|--------|
| AI usage by org and date | `ORG#{org_id}#AIUSAGE#{date}` | `AIUSAGE#{usage_id}` |

**Projection:** `model_id`, `operation`, `input_tokens`, `output_tokens`, `cost_usd`

Supports the metrics/query endpoint for AI token usage reporting.

### GSI6: Message by SES ID

| Purpose | GSI6PK | GSI6SK |
|---------|--------|--------|
| Message by SES message ID | `SES#{ses_message_id}` | `MSG#{message_id}` |

**Projection:** KEYS_ONLY + `inbox_id`, `org_id`

Used when SES sends bounce/complaint/delivery notifications that reference the SES message ID. This GSI maps back to the AgentMail message record.

---

## Access Patterns

### API Endpoint to DynamoDB Operation Mapping

| API Endpoint | DynamoDB Operation | Key Condition |
|-------------|-------------------|---------------|
| `GET /organizations/me` | GetItem | PK=`ORG#{org_id}`, SK=`ORG#{org_id}` |
| `GET /api-keys` | Query | PK=`ORG#{org_id}`, SK begins_with `APIKEY#` |
| `POST /api-keys` | PutItem + UpdateItem | PK=`ORG#{org_id}`, SK=`APIKEY#{key_id}` + update org usage |
| `DELETE /api-keys/{id}` | UpdateItem | PK=`ORG#{org_id}`, SK=`APIKEY#{id}`, set status=revoked |
| `GET /pods` | Query GSI1 | GSI1PK=`ORG#{org_id}#PODS` |
| `GET /pods/{id}` | GetItem | PK=`ORG#{org_id}`, SK=`POD#{id}` |
| `POST /pods` | TransactWriteItems | PutItem pod + UpdateItem org usage |
| `DELETE /pods/{id}` | TransactWriteItems | DeleteItem pod + UpdateItem org usage |
| `GET /inboxes` | Query GSI1 | GSI1PK=`POD#{pod_id}#INBOXES` (if pod_id) or PK=`ORG#{org_id}`, SK begins_with `INBOX#` |
| `GET /inboxes/{id}` | GetItem | PK=`ORG#{org_id}`, SK=`INBOX#{id}` |
| `POST /inboxes` | TransactWriteItems | PutItem inbox + UpdateItem pod inbox_count + UpdateItem org usage |
| `PATCH /inboxes/{id}` | UpdateItem | PK=`ORG#{org_id}`, SK=`INBOX#{id}` |
| `DELETE /inboxes/{id}` | UpdateItem | Set status=deleted, deleted_at=now |
| `GET /inboxes/{id}/messages` | Query | PK=`INBOX#{id}`, SK begins_with `MSG#`, ScanIndexForward=ascending |
| `GET /inboxes/{id}/messages/{mid}` | GetItem + S3 GetObject | PK=`INBOX#{id}`, SK=`MSG#{mid}` + fetch body from S3 |
| `POST /inboxes/{id}/messages` | TransactWriteItems + SES | PutItem msg + UpdateItem thread + UpdateItem inbox counts |
| `POST /inboxes/{id}/messages/{mid}/reply` | TransactWriteItems + SES | Same as send + auto-populate from, subject, headers |
| `POST /inboxes/{id}/messages/{mid}/reply-all` | TransactWriteItems + SES | Same as reply + include all recipients |
| `POST /inboxes/{id}/messages/{mid}/forward` | TransactWriteItems + SES | Same as send + include original attachments |
| `PATCH /inboxes/{id}/messages/{mid}` | UpdateItem | PK=`INBOX#{id}`, SK=`MSG#{mid}` |
| `GET /inboxes/{id}/messages/{mid}/attachments/{aid}` | GetItem + S3 presign | PK=`MSG#{mid}`, SK=`ATTACH#{aid}` |
| `GET /inboxes/{id}/messages/{mid}/raw` | S3 GetObject | Key: `raw-email/{org_id}/{inbox_id}/{message_id}.eml` |
| `GET /inboxes/{id}/threads` | Query GSI1 | GSI1PK=`INBOX#{id}#THREADS`, ScanIndexForward=ascending |
| `GET /inboxes/{id}/threads/{tid}` | GetItem + Query GSI1 | GetItem thread + Query GSI1PK=`THREAD#{tid}` for messages |
| `PATCH /inboxes/{id}/threads/{tid}` | UpdateItem | PK=`INBOX#{id}`, SK=`THREAD#{tid}` |
| `DELETE /inboxes/{id}/threads/{tid}` | BatchWriteItem | Update thread + all messages is_trash=true |
| `GET /inboxes/{id}/drafts` | Query GSI1 | GSI1PK=`INBOX#{id}#DRAFTS` |
| `GET /inboxes/{id}/drafts/{did}` | GetItem | PK=`INBOX#{id}`, SK=`DRAFT#{did}` |
| `POST /inboxes/{id}/drafts` | PutItem | PK=`INBOX#{id}`, SK=`DRAFT#{did}` |
| `PATCH /inboxes/{id}/drafts/{did}` | UpdateItem | PK=`INBOX#{id}`, SK=`DRAFT#{did}` |
| `DELETE /inboxes/{id}/drafts/{did}` | DeleteItem | PK=`INBOX#{id}`, SK=`DRAFT#{did}` |
| `POST /inboxes/{id}/drafts/{did}/send` | TransactWriteItems + SES | PutItem msg + DeleteItem draft + update counts |
| `GET /domains` | Query | PK=`ORG#{org_id}`, SK begins_with `DOMAIN#` |
| `GET /domains/{id}` | GetItem | PK=`ORG#{org_id}`, SK=`DOMAIN#{id}` |
| `POST /domains` | TransactWriteItems | PutItem domain + SES VerifyDomainIdentity |
| `PATCH /domains/{id}` | UpdateItem | PK=`ORG#{org_id}`, SK=`DOMAIN#{id}` |
| `DELETE /domains/{id}` | TransactWriteItems | DeleteItem domain + SES DeleteIdentity |
| `POST /domains/{id}/verify` | GetItem + SES | Trigger re-check of DNS records |
| `GET /domains/{id}/zone-file` | GetItem | Read DNS records, format as BIND zone |
| `GET /webhooks` | Query GSI1 | GSI1PK=`ORG#{org_id}#WEBHOOKS` |
| `GET /webhooks/{id}` | GetItem | PK=`ORG#{org_id}`, SK=`WEBHOOK#{id}` |
| `POST /webhooks` | PutItem | PK=`ORG#{org_id}`, SK=`WEBHOOK#{id}` |
| `PATCH /webhooks/{id}` | UpdateItem | PK=`ORG#{org_id}`, SK=`WEBHOOK#{id}` |
| `DELETE /webhooks/{id}` | DeleteItem | PK=`ORG#{org_id}`, SK=`WEBHOOK#{id}` |
| `GET /lists` | Query GSI1 | GSI1PK=`ORG#{org_id}#LISTS` |
| `GET /lists/{id}` | GetItem + Query | GetItem list metadata + Query PK=`LIST#{id}` for members |
| `POST /lists` | TransactWriteItems | PutItem list + BatchWriteItem members |
| `DELETE /lists/{id}` | BatchWriteItem | Delete list + all members |
| `POST /metrics/query` | Query GSI5 | GSI5PK=`ORG#{org_id}#AIUSAGE#{date}` |
| `POST /search` | OpenSearch query | Not DynamoDB -- routed to OpenSearch Serverless |
| **Inbound email routing** | Query GSI2 | GSI2PK=`EMAIL#{recipient_address}` |
| **SES bounce/complaint** | Query GSI6 | GSI6PK=`SES#{ses_message_id}` |
| **WebSocket fan-out** | Query GSI4 | GSI4PK=`WSSUB#{channel}` |
| **Auth: key lookup** | Query GSI1 | GSI1PK=`APIKEY#{key_hash}` |

---

## Capacity Planning

### On-Demand Mode (Default)

On-demand capacity automatically scales to handle any traffic level. Pricing:

| Operation | Cost per million |
|-----------|-----------------|
| Write request units (WRU) | $1.25 |
| Read request units (RRU) | $0.25 |

### Estimated Monthly Costs

| Scale | Writes/Day | Reads/Day | Monthly Cost |
|-------|-----------|-----------|-------------|
| Startup (100K msgs/day) | ~500K | ~2M | ~$50 |
| Growth (1M msgs/day) | ~5M | ~20M | ~$500 |
| Full Scale (10M msgs/day) | ~50M | ~200M | ~$5,000 |

### Provisioned Mode (at Scale)

When DynamoDB spend exceeds ~$3,000/month, switch to provisioned capacity with auto-scaling for 50-70% cost savings:

```yaml
Resources:
  AgentMailTable:
    Type: AWS::DynamoDB::Table
    Properties:
      BillingMode: PROVISIONED
      ProvisionedThroughput:
        ReadCapacityUnits: 5000
        WriteCapacityUnits: 2000

  ReadScalingTarget:
    Type: AWS::ApplicationAutoScaling::ScalableTarget
    Properties:
      MaxCapacity: 50000
      MinCapacity: 1000
      ResourceId: !Sub table/${AgentMailTable}
      ScalableDimension: dynamodb:table:ReadCapacityUnits
      ServiceNamespace: dynamodb

  ReadScalingPolicy:
    Type: AWS::ApplicationAutoScaling::ScalingPolicy
    Properties:
      PolicyName: ReadAutoScaling
      PolicyType: TargetTrackingScaling
      ScalableTargetId: !Ref ReadScalingTarget
      TargetTrackingScalingPolicyConfiguration:
        TargetValue: 70.0
        PredefinedMetricSpecification:
          PredefinedMetricType: DynamoDBReadCapacityUtilization
        ScaleInCooldown: 60
        ScaleOutCooldown: 60
```

---

## Hot Partition Avoidance

### Problem

A single inbox receiving millions of messages per day would create a hot partition on `PK=INBOX#{inbox_id}`.

### Mitigation Strategies

1. **Adaptive capacity (automatic).** DynamoDB automatically redistributes throughput to hot partitions. This handles moderate hot spots without intervention.

2. **Write sharding for extreme inboxes.** For inboxes exceeding 1,000 writes per second, distribute across shards:

```python
import random

SHARD_COUNT = 10

def sharded_pk(inbox_id: str) -> str:
    """Generate a sharded partition key for high-volume inboxes."""
    shard = random.randint(0, SHARD_COUNT - 1)
    return f"INBOX#{inbox_id}#SHARD#{shard}"

def query_all_shards(inbox_id: str, sk_prefix: str):
    """Query all shards and merge results."""
    results = []
    for shard in range(SHARD_COUNT):
        pk = f"INBOX#{inbox_id}#SHARD#{shard}"
        response = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": pk, ":prefix": sk_prefix},
        )
        results.extend(response["Items"])
    # Sort by SK (ULID, so chronological)
    results.sort(key=lambda x: x["SK"], reverse=True)
    return results
```

3. **Monitoring.** CloudWatch alarm on `ConsumedReadCapacityUnits` and `ConsumedWriteCapacityUnits` per partition key (using CloudWatch Contributor Insights):

```yaml
ContributorInsightsRule:
  Type: AWS::DynamoDB::Table
  Properties:
    ContributorInsightsSpecification:
      Enabled: true
```

---

## DynamoDB Streams

### Configuration

```yaml
StreamSpecification:
  StreamViewType: NEW_AND_OLD_IMAGES
```

Every insert, update, and delete on the table produces a stream record containing both the old and new item images.

### Stream Consumers

| Consumer | Trigger | Purpose |
|----------|---------|---------|
| OpenSearch Indexer | Lambda (event source mapping) | Index messages for full-text and semantic search |
| Event Router | Lambda (event source mapping) | Route events to EventBridge for webhook delivery |
| WebSocket Notifier | Lambda (event source mapping) | Push real-time notifications to connected WebSocket clients |
| Metrics Aggregator | Lambda (event source mapping) | Aggregate usage metrics for billing and reporting |
| Audit Log | Kinesis Data Firehose (via EventBridge Pipes) | Archive all changes to S3 for compliance |

### Lambda Event Source Mapping

```yaml
OpenSearchIndexerMapping:
  Type: AWS::Lambda::EventSourceMapping
  Properties:
    EventSourceArn: !GetAtt AgentMailTable.StreamArn
    FunctionName: !Ref OpenSearchIndexerFunction
    StartingPosition: TRIM_HORIZON
    BatchSize: 100
    MaximumBatchingWindowInSeconds: 5
    MaximumRetryAttempts: 3
    BisectBatchOnFunctionError: true
    DestinationConfig:
      OnFailure:
        Destination: !GetAtt StreamDLQ.Arn
    FilterCriteria:
      Filters:
        - Pattern: '{"dynamodb":{"NewImage":{"entity_type":{"S":["Message","Thread"]}}}}'
```

---

## TTL Configuration

Transient records use DynamoDB TTL for automatic cleanup:

| Entity | TTL Attribute | Duration | Reason |
|--------|--------------|----------|--------|
| OTP codes | `ttl` | 24 hours + 1 hour buffer | Verification codes are single-use and time-limited |
| WebSocket connections | `ttl` | 1 hour after last ping | Stale connections from disconnected clients |
| AI usage records | `ttl` | 90 days | Historical data moves to S3 via Streams before TTL |
| Deleted messages (soft) | `ttl` | Retention period (default 30 days) | Purge trashed messages after retention window |
| Rate limit audit entries | `ttl` | 7 days | Short-term abuse detection, then discarded |

TTL is configured on the table:

```yaml
TimeToLiveSpecification:
  AttributeName: ttl
  Enabled: true
```

The `ttl` attribute value is a Unix epoch timestamp (seconds). DynamoDB deletes items within 48 hours after the TTL expires (usually much sooner). TTL deletions produce stream records, so downstream consumers can react to deletions.

---

## Backup Strategy

### Point-in-Time Recovery (PITR)

Enabled on the table. Provides continuous backups with per-second granularity, allowing restore to any point in the last 35 days.

```yaml
PointInTimeRecoverySpecification:
  PointInTimeRecoveryEnabled: true
```

**Cost:** ~$0.20 per GB per month of table size.

### On-Demand Backups

Scheduled daily via AWS Backup:

```yaml
BackupPlan:
  Type: AWS::Backup::BackupPlan
  Properties:
    BackupPlan:
      BackupPlanName: agentmail-dynamodb-daily
      BackupPlanRule:
        - RuleName: daily-backup
          TargetBackupVault: !Ref BackupVault
          ScheduleExpression: "cron(0 2 * * ? *)"  # 2 AM UTC daily
          StartWindowMinutes: 60
          CompletionWindowMinutes: 180
          Lifecycle:
            DeleteAfterDays: 90
            MoveToColdStorageAfterDays: 30
```

### Cross-Region Replication

DynamoDB Global Tables are not used initially (single-region deployment). When multi-region is needed:

1. Enable Global Tables for us-east-1 + us-west-2.
2. Global Tables handle bi-directional replication automatically.
3. Conflict resolution: last-writer-wins (DynamoDB default).

### Restore Testing

Monthly restore testing via automation:

1. Restore PITR to a test table.
2. Run validation queries to verify data integrity.
3. Compare item counts and spot-check records.
4. Delete test table.
