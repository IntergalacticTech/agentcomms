# FreeMail on AWS: Architecture for an Email Platform for AI Agents

> **Status as of 2026-04-13.** FreeMail is **live in production** on AWS account `732770059798` in `us-east-1`. The shipped surface includes the REST API at `api.victorymail.dev`, developer console at `console.victorymail.dev`, marketing site at `victorymail.dev`, verified SES sending and receiving for `victorymail.dev` + the `karmascale.net` / `karmascale.org` domain pool, DynamoDB single-table storage, Cognito-based console auth, Stripe billing integration, and the full REST resource surface described in `docs/api-reference.md`.
>
> **This document still contains target-state design for features not yet shipped**, notably: WebSocket real-time event delivery, OpenSearch Serverless vector search, Step Functions pipelines, IMAP/SMTP bridges, dedicated IPs, AWS Marketplace metering integration, and the 4-tier enterprise sales motion. Those sections describe where we're going, not where we are. Sections that only describe aspirational state are marked `> **Target state**` at the top.
>
> For the current **customer-facing tier structure** (Free / Starter $5 / Pro $25 / Enterprise / BYOC), see `docs/billing.md`. This document's "Pricing Tiers" table is older and out of sync — treat `docs/billing.md` as authoritative.
>
> The **BYOC (Bring Your Own Cloud) Marketplace offering** is designed but not yet implemented. See `docs/byoc.md` for the design, and `/tmp/freemail-byoc.md` for the full detailed design doc.

## Executive Summary

This document describes the AWS-native architecture for building **FreeMail** -- an API platform that gives AI agents their own email inboxes to send, receive, and act upon emails.

Current planning direction:

- launch as direct SaaS first
- use `victorymail.dev` for initial deployment and testing
- keep AI features paid-only
- use AWS Marketplace after customers outgrow Pro or require AWS procurement

Technical implementation decision:

- use **Python 3.12** for API handlers, email processing, workers, and metering
- use **TypeScript** for AWS CDK, the developer console, and the MCP server
- launch with **Python and Node.js SDKs**; defer Go until later
- do **not** introduce a Laravel/PHP backend on the launch path

**What FreeMail does:**
- Creates email inboxes on-demand via API (no human provisioning)
- Sends/receives email with full DKIM/SPF/DMARC authentication
- Provides AI-powered semantic search, email categorization, and structured data extraction
- Delivers real-time events via webhooks and WebSockets
- Supports custom domains, multi-tenant pods, and allow/block lists
- Exposes SDKs (Python, Node.js) and a REST API at launch

**Why it matters for AI agents:**
Traditional email providers (Gmail, Outlook) charge $4-12/inbox/month, lack programmatic inbox creation APIs, impose automation-hostile rate limits, and require OAuth flows. FreeMail solves those problems with an API-first model purpose-built for autonomous systems.

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Email Transport Layer (SES)](#2-email-transport-layer-ses)
3. [API Platform](#3-api-platform)
4. [Database Design](#4-database-design)
5. [Real-Time Event System](#5-real-time-event-system)
6. [AI/ML Features](#6-aiml-features)
7. [IMAP/SMTP Compatibility](#7-imapsmtp-compatibility)
8. [AWS Marketplace Integration](#8-aws-marketplace-integration)
9. [Multi-Tenancy & Isolation](#9-multi-tenancy--isolation)
10. [Observability](#10-observability)
11. [CI/CD & Infrastructure as Code](#11-cicd--infrastructure-as-code)
12. [Cost Analysis](#12-cost-analysis)
13. [Phased Implementation Roadmap](#13-phased-implementation-roadmap)

---

## 1. System Architecture Overview

```
                     ┌──────────────────────────────────────────────────┐
                     │                   CUSTOMERS                      │
                     │  REST API  │  WebSocket  │  IMAP  │  SMTP       │
                     └─────┬──────┴──────┬───────┴───┬────┴──────┬─────┘
                           │             │           │           │
                     ┌─────▼─────┐ ┌─────▼─────┐ ┌──▼──┐  ┌────▼────┐
                     │ API GW    │ │ API GW WS │ │ NLB │  │  NLB    │
                     │ (REST)    │ │ (WebSocket)│ │:993 │  │  :587   │
                     └─────┬─────┘ └─────┬─────┘ └──┬──┘  └────┬────┘
                           │             │           │           │
                     ┌─────▼─────┐ ┌─────▼─────┐ ┌──▼──────────▼────┐
                     │  Lambda   │ │  Lambda   │ │  ECS Fargate     │
                     │  Handlers │ │  WS Mgr   │ │  IMAP/SMTP Proxy │
                     └─────┬─────┘ └─────┬─────┘ └────────┬─────────┘
                           │             │                 │
           ┌───────────────┼─────────────┼─────────────────┤
           │               │             │                 │
     ┌─────▼──────┐  ┌────▼───┐  ┌──────▼──────┐  ┌──────▼──────┐
     │  DynamoDB  │  │  S3    │  │  ElastiCache │  │    SES      │
     │  (data)    │  │ (blobs)│  │  (Redis)     │  │  (transport)│
     └────────────┘  └────────┘  └─────────────-┘  └─────────────┘
                           │
                     ┌─────▼──────┐        ┌──────────────────┐
                     │  Kinesis   │───────→│  OpenSearch       │
                     │  (events)  │        │  Serverless       │
                     └────────────┘        │  (vector search)  │
                           │               └──────────────────┘
                     ┌─────▼──────┐
                     │  Bedrock   │
                     │  (AI/ML)   │
                     └────────────┘

     INBOUND EMAIL:
     ┌──────────┐     ┌───────────┐     ┌──────┐     ┌────────┐
     │ Internet │────→│ SES       │────→│  S3  │────→│ Lambda │──→ DynamoDB
     │ (sender) │     │ Inbound   │     │(raw) │     │ Router │──→ Kinesis
     └──────────┘     └───────────┘     └──────┘     └────────┘──→ Bedrock
```

### Core AWS Services

| Layer | Service | Purpose |
|-------|---------|---------|
| **Transport** | SES | Send and receive email (SMTP, DKIM, SPF, DMARC) |
| **API** | API Gateway (REST + WebSocket) | Request routing, auth, throttling, WebSocket connections |
| **Compute** | Lambda at launch, ECS Fargate only if later justified | API handlers, workers, and future long-running services |
| **Primary DB** | DynamoDB | All metadata: orgs, inboxes, messages, threads, API keys |
| **Blob Storage** | S3 | Raw MIME, attachments, large HTML bodies |
| **Cache** | ElastiCache Redis | API key auth, rate limiting, inbox routing cache |
| **Event Bus** | Kinesis Data Streams | Central event pipeline with ordering and replay |
| **AI/ML** | Bedrock + OpenSearch Serverless | Embeddings, categorization, extraction, vector search |
| **DNS** | Route 53 | Platform domain management, health checks |
| **Observability** | CloudWatch + X-Ray | Metrics, logs, alarms, distributed tracing |
| **IaC** | AWS CDK (TypeScript) | Infrastructure as code, deployment pipelines |
| **Marketplace** | Marketplace Metering + Entitlement APIs | Billing, subscription lifecycle |

---

## 2. Email Transport Layer (SES)

### 2.1 Outbound Email (Sending)

**Flow:**
```
API: POST /v1/inboxes/{id}/messages
  → Lambda validates request, writes to DynamoDB (status=queued)
  → Enqueue to SQS send-queue
  → Lambda send-worker:
      1. Build MIME message (text, HTML, attachments from S3)
      2. Call SES SendRawEmail with inbox's verified domain
      3. On success: update status=sent, publish "message.sent" to Kinesis
      4. On SES throttle: message returns to SQS (visibility timeout backoff)
      5. On permanent failure: update status=failed, publish "message.bounced"
```

**SES Configuration:**
- Configuration sets per organization for per-org tracking
- Event destinations: SNS topics for bounces, complaints, deliveries
- Dedicated IPs: tiered pools (free=shared, standard=shared dedicated, enterprise=per-tenant)
- Virtual Deliverability Manager enabled for reputation monitoring ($0.07/1K messages)

**Sending Limits:**
- Default production: 50K/day (request increases via AWS Support)
- Per-tenant rate limiting at API layer, not SES level
- Tenant complaint rate monitoring: auto-suspend at >0.1%, throttle at >0.05%

### 2.2 Inbound Email (Receiving)

**Architecture: Catch-All with Lambda Routing**

SES inbound does not have an "inbox" concept. We build virtual inboxes on top:

```
Internet → MX Record → SES Inbound → Receipt Rule (catch-all for all verified domains)
  ├─→ S3Action: store raw MIME to s3://victorymail-raw-email/inbound/{message-id}
  └─→ LambdaAction (async): inbound-router
        ├─→ Parse recipient address
        ├─→ DynamoDB/Redis lookup: inbox exists? domain verified?
        ├─→ Parse MIME: headers, body, attachments
        ├─→ Store metadata in DynamoDB
        ├─→ Store attachments in S3
        ├─→ Compute thread (In-Reply-To / References headers)
        ├─→ Publish "message.received" to Kinesis
        └─→ If inbox doesn't exist → bounce or discard
```

**MX Records (per domain):**
```
victorymail.dev.   MX  10  inbound-smtp.us-east-1.amazonaws.com.
customer.com.      MX  10  inbound-smtp.us-east-1.amazonaws.com.
```

**SES Inbound Verdicts:** The Lambda receives spam, virus, SPF, DKIM, and DMARC verdicts from SES automatically -- no additional spam filtering service needed.

**Regional Constraint:** SES inbound is only available in us-east-1, us-west-2, and eu-west-1. Start in us-east-1.

### 2.3 Custom Domain Verification

When a customer adds a domain via `POST /v1/domains`:

1. Call `SES CreateEmailIdentity` with Easy DKIM (RSA 2048-bit)
2. Return DNS records to customer:
   - 3 CNAME records for DKIM
   - 1 TXT record for SPF (`v=spf1 include:amazonses.com ~all`)
   - 1 MX record for inbound
   - 1 TXT record for DMARC
3. Scheduled Lambda polls `GetEmailIdentity` every 5 minutes for pending domains
4. On verification: update domain status, fire `domain.verified` event

### 2.4 Deliverability Architecture

**IP Pool Strategy:**
```
Pool: "shared"       → SES shared IPs (free tier tenants)
Pool: "standard"     → 2-4 dedicated IPs, shared across paid tenants
Pool: "premium"      → Dedicated IPs per enterprise tenant ($24.95/mo/IP)
Pool: "transactional"→ Separate IPs for transactional email
```

**Reputation Protection:**
- Per-tenant bounce/complaint rate monitoring via CloudWatch metrics
- Automatic throttling at bounce >3%, suspension at bounce >5%
- Automatic suspension at complaint >0.1%
- Content scanning before sending (heuristic + ML-based spam detection)
- Tenant identity verification (domain ownership required)

### 2.5 SES Cost Model

| Component | Rate | At 10M msgs/day |
|-----------|------|-----------------|
| Outbound emails | $0.10/1K | $15,000/mo |
| Inbound emails | $0.10/1K | $15,000/mo |
| Data (attachments) | $0.12/GB | ~$36,000/mo |
| Dedicated IPs | $24.95/IP/mo | ~$250/mo |
| VDM | $0.07/1K msgs | $21,000/mo |

---

## 3. API Platform

### 3.1 API Layer: API Gateway + Lambda

**Choice justification:** API Gateway provides built-in API key management, usage plans, throttling, and request validation. Lambda cold starts of 200-400ms are acceptable for AI agent workloads. Graduate to ALB + ECS at ~500M requests/month.

**Initial FreeMail API surface:**

| Resource | Key Endpoints | Lambda Memory | Timeout |
|----------|--------------|---------------|---------|
| Agent | sign_up, verify | 512 MB | 15s |
| Organizations | get | 512 MB | 15s |
| API Keys | list, create, delete | 512 MB | 15s |
| Pods | list, get, create, delete | 512 MB | 15s |
| Inboxes | list, get, create, update, delete | 512 MB | 15s |
| Messages | list, get, send, reply, reply_all, forward, update, get_attachment, get_raw | 1024 MB | 30s |
| Threads | list, get, update, delete, get_attachment | 512 MB | 15s |
| Drafts | list, get, create, update, delete, send, get_attachment | 512 MB | 15s |
| Domains | list, get, create, update, delete, verify, get_zone_file | 512 MB | 15s |
| Webhooks | list, get, create, update, delete | 512 MB | 15s |
| Lists | list, get, create, delete | 512 MB | 15s |
| Metrics | query | 1024 MB | 30s |
| Search | query (semantic) | 1024 MB | 30s |

### 3.2 Authentication

**API Key Scoping Model:**
- **Org-level key**: Full access to all resources in the organization
- **Pod-level key**: Access scoped to a specific pod and its inboxes
- **Inbox-level key**: Access to a single inbox (minimum privilege for AI agents)

**Auth Flow:**
```
Request → API Gateway → Lambda Authorizer →
  1. Extract API key from x-api-key or Authorization: Bearer header
  2. Check Redis cache: key_hash → {org_id, pod_id, inbox_id, scopes[], tier}
  3. Cache miss: DynamoDB GSI lookup, populate cache (TTL 5 min)
  4. Validate scope against requested resource
  5. Return IAM policy + context (org_id, scopes)
```

Provisioned concurrency of 50 on the authorizer Lambda eliminates cold starts on the hottest path.

### 3.3 Rate Limiting (Three Tiers)

1. **API Gateway Usage Plans** (coarse): Per-API-key throttle (rps) and monthly quota per pricing tier
2. **Redis Sliding Window** (fine-grained): Lua-script counters keyed by `{org_id}:{resource}:{window}` for per-endpoint limits (e.g., 100 sends/min per inbox)
3. **WAF Rate Rules** (DDoS): 10,000 requests per 5 minutes per IP before reaching Lambda

### 3.4 SDK Generation Pipeline

- OpenAPI 3.1 spec at `/api/openapi.yaml` is the source of truth
- GitHub Actions runs `openapi-generator-cli` on spec changes
- Publishes to PyPI (Python), npm (Node.js), Go modules
- Spec served at `GET /openapi.json` via CloudFront

---

## 4. Database Design

### 4.1 DynamoDB Single-Table Design

**Choice justification:** Automatic partitioning, single-digit ms reads at any scale, natural multi-tenant isolation via partition key prefix, on-demand pricing aligns cost with usage. Complex queries (search, analytics) delegated to purpose-built services.

### 4.2 Entity Layouts

**Table: `victorymail` (Primary)**

| Entity | PK | SK | Key Attributes |
|--------|----|----|----------------|
| Organization | `ORG#{org_id}` | `META` | name, plan, quotas{}, settings{} |
| API Key | `ORG#{org_id}` | `APIKEY#{key_hash}` | key_prefix, scopes[], pod_id?, inbox_id? |
| Pod | `ORG#{org_id}` | `POD#{pod_id}` | name, settings{} |
| Inbox | `ORG#{org_id}` | `INB#{inbox_id}` | address, display_name, pod_id, domain_id |
| Message | `INB#{inbox_id}` | `MSG#{timestamp}#{msg_id}` | from, to[], subject, body_preview(4KB), thread_id, status, labels |
| Thread | `INB#{inbox_id}` | `THR#{thread_id}` | subject, last_message_at, message_count, participants[] |
| Draft | `INB#{inbox_id}` | `DRF#{draft_id}` | from, to[], subject, body_s3_key, attachments[] |
| Domain | `ORG#{org_id}` | `DOM#{domain_id}` | domain_name, status, dkim_tokens[], verified_at |
| Webhook | `ORG#{org_id}` | `WHK#{webhook_id}` | url, events[], secret, status, pod_id? |
| List Entry | `INB#{inbox_id}` | `LST#{type}#{address}` | type(allow/block), scope(send/receive) |
| Attachment | `MSG#{msg_id}` | `ATT#{att_id}` | filename, content_type, size, s3_key |

### 4.3 Global Secondary Indexes

| GSI | PK | SK | Purpose |
|-----|----|----|---------|
| GSI1 | `APIKEY#{key_hash}` | `ORG#{org_id}` | Auth: API key lookup (hottest path) |
| GSI2 | `ADDR#{email_address}` | `INB#{inbox_id}` | Inbound routing: resolve inbox by address |
| GSI3 | `POD#{pod_id}` | `INB#{inbox_id}` | List inboxes in a pod |
| GSI4 | `THR#{thread_id}` | `MSG#{timestamp}#{msg_id}` | List messages in a thread |
| GSI5 | `MSGID#{message_id_header}` | `MSG#{msg_id}` | Thread computation by RFC Message-ID |
| GSI6 | `DOMAIN#{domain_name}` | `ORG#{org_id}` | Domain ownership verification |

### 4.4 Message Storage Tiers

```
DynamoDB item (~1-2 KB):    Headers, subject, from/to, status, thread_id, body_preview (first 4KB)
S3 raw MIME (1KB-40MB):     s3://victorymail-raw-email/{org_id}/{inbox_id}/{msg_id}.eml
S3 attachments (1KB-25MB):  s3://victorymail-attachments/{org_id}/{msg_id}/{att_id}/{filename}
S3 large HTML (>4KB):       s3://victorymail-bodies/{org_id}/{msg_id}/body.html
```

### 4.5 S3 Lifecycle Policies

| Bucket | Standard | IA | Glacier | Delete |
|--------|----------|----|---------|--------|
| raw-email | 30 days | 30-90 days | 90-365 days | Configurable per org |
| attachments | 60 days | 60-180 days | 180+ days | Per org |
| bodies | 30 days | 30-90 days | 90+ days | Per org |
| exports | 7 days | - | - | 7 days |

### 4.6 Email Threading

```python
def resolve_thread(inbox_id, in_reply_to, references, subject):
    # 1. Match In-Reply-To header against existing messages (GSI5)
    # 2. Match References header chain (first ref = thread root)
    # 3. Fallback: normalized subject matching (strip Re:/Fwd:)
    # 4. No match: create new thread
```

Thread items updated atomically with `ADD message_count 1` and `SET last_message_at`.

---

## 5. Real-Time Event System

### 5.1 Central Event Bus: Kinesis Data Streams

**Choice over EventBridge/SNS:** Kinesis provides ordering (partition by inboxId), replay (7-day retention), and dedicated per-consumer throughput (enhanced fan-out). EventBridge lacks ordering; SNS lacks replay. Both hit throughput limits at 100K events/minute.

**Configuration:**
```
Stream: victorymail-events
  Shards: 4 (auto-scale via Application Auto Scaling)
  Partition key: inboxId (preserves per-inbox ordering)
  Retention: 7 days
  Encryption: AWS-managed KMS
  Enhanced fan-out consumers:
    - webhook-pipeline
    - websocket-pipeline
    - analytics-pipeline
    - event-archive (Kinesis Firehose → S3)
```

**Event Schema:**
```json
{
  "eventId": "evt_01H8X9ABC123",
  "eventType": "message.received",
  "eventVersion": "1.0",
  "timestamp": "2026-04-10T14:30:00.000Z",
  "orgId": "org_xxx",
  "podId": "pod_xxx",
  "inboxId": "inbox_xxx",
  "data": { "messageId": "msg_xxx", "from": "...", "subject": "..." }
}
```

**Supported Event Types:**
- `message.received` - inbound email arrived
- `message.sent` - outbound email accepted by SES
- `message.delivered` - outbound delivered to recipient
- `message.bounced` - email bounced
- `message.complained` - spam complaint received
- `message.rejected` - email rejected
- `message.ai_processed` - AI pipeline complete
- `domain.verified` - custom domain verified

### 5.2 Webhook Delivery System

```
Kinesis → Lambda (webhook-dispatcher, enhanced fan-out)
  → Query matching webhook endpoints (org + pod + inbox scope levels)
  → SQS message per endpoint

SQS (webhook-delivery-queue) → Lambda (webhook-sender)
  → HMAC-SHA256 sign payload with webhook secret
  → POST to customer URL (10s timeout)
  → Log delivery attempt to DynamoDB
  → On failure: exponential backoff (10s, 30s, 60s, 300s)
  → After 5 retries → DLQ → disable endpoint
```

**Signature Headers:**
```
X-FreeMail-Signature: v1={sha256-hmac}
X-FreeMail-Timestamp: {unix-epoch}
X-FreeMail-Event-Id: {event-id}
```

**Endpoint Validation:** On registration, send a challenge POST. Endpoint must echo `{"challenge": "ch_xxx"}` within 10 seconds.

**Performance Target:** Webhook delivered within 5 seconds of event (typical: ~1.2 seconds).

### 5.3 WebSocket System

**API Gateway WebSocket API:**
```
$connect  → Lambda authorizer validates API key
           → Store connection in DynamoDB: PK=CONN#{connId}, attributes: orgId, scopes
$default  → Handle subscribe/unsubscribe to channels:
             "inbox:inbox_42", "pod:pod_5", "org:org_1"
           → DynamoDB: PK=SUB#inbox#inbox_42, SK=CONN#{connId}
$disconnect → Cleanup connection and subscription records
```

**Event Delivery:**
```
Kinesis → Lambda (websocket-dispatcher, enhanced fan-out)
  → Query DynamoDB for connections matching event's org/pod/inbox
  → POST to @connections/{connectionId} for each match
  → On 410 GoneException: clean up stale connection
```

**Reconnection/Replay:** Clients provide `lastEventId` on connect. Server replays from Kinesis (7-day retention) by looking up the sequence number for that event ID.

**Heartbeat:** Server sends ping every 30 seconds. Connections without pong after 60 seconds are terminated.

### 5.4 Event System Cost (~100K events/minute)

| Service | Monthly Cost |
|---------|-------------|
| Kinesis (4 shards, enhanced fan-out, 7d) | ~$200 |
| Lambda (normalizers + dispatchers + senders) | ~$1,500 |
| DynamoDB (endpoints + connections + logs) | ~$400 |
| SQS (queues) | ~$120 |
| API Gateway WebSocket (100K connections) | ~$600 |
| **Total** | **~$3,000/mo** |

---

## 6. AI/ML Features

### 6.1 Processing Pipeline (Step Functions Express)

```
Message Arrives → EventBridge → Step Functions Express:
  ├─→ [Text Extraction]  (synchronous, <500ms, no LLM)
  │     Parse MIME, strip quoted replies, extract clean text/HTML
  │     Libraries: email.parser, quotequail, html2text
  │
  └─→ [Parallel Branch]:
        ├─→ [Embedding Generation]  → OpenSearch Serverless
        ├─→ [Categorization]        → DynamoDB (labels)
        └─→ [Extraction]            → DynamoDB (structured data)
```

### 6.2 Semantic Search

**Embedding Model:** Amazon Titan Embeddings V2 Text (512 dimensions)
- $0.00002/1K tokens on-demand, $0.00001/1K batch
- Native Bedrock integration, sufficient quality for email text

**Vector Store:** Amazon OpenSearch Serverless (Vector Engine)
- Shared collection with mandatory `org_id` filter (not per-tenant collections)
- HNSW algorithm, cosine similarity
- Hybrid search: vector similarity + keyword (BM25) + metadata filters

**Query Flow:**
```
POST /v1/search {"query": "invoices from last month", "inbox_ids": [...]}
  → Embed query via Titan V2
  → OpenSearch knn query with org_id filter + inbox_id filter + date range
  → Optional: re-rank top-50 with amazon-rerank-v1.0 (premium tiers)
  → Return ranked message IDs with scores
```

**Indexing Latency:** New messages indexed within 30 seconds of arrival.

### 6.3 Email Categorization

**Model Tiering:**
- **Haiku** ($0.0003/email): Simple categorization (2-5 categories, spam/support/billing)
- **Sonnet** ($0.003/email): Complex multi-label, sentiment + intent + urgency

**Configuration:** Per-inbox prompt templates stored in DynamoDB with configurable label taxonomies. Validated response against allowed labels; retry once on invalid output, fallback to "uncategorized".

**Cost Optimization:** Model router selects Haiku for 60-70% of emails. Prompt caching saves ~30% on repeated system prompts. DynamoDB result cache for identical emails (newsletters) at 5-15% hit rate.

### 6.4 Structured Data Extraction

Customers define JSON schemas per inbox. Bedrock Claude processes emails against the schema using tool_use/structured output mode for guaranteed valid JSON.

```json
// Example schema
{
  "fields": [
    {"name": "order_id", "type": "string", "required": true},
    {"name": "total_amount", "type": "number"},
    {"name": "items", "type": "array", "items": {"type": "object", ...}}
  ]
}
```

**Validation:** JSON Schema validation, type coercion, required field checking. Retry once on validation failure with stricter prompt.

### 6.5 Email Text Extraction

Pure parsing (no LLM). Strips quoted reply chains from all major email clients:
- Gmail: `On {date}, {name} wrote:` + `>`-prefixed lines
- Outlook: `-----Original Message-----`
- Apple Mail: `<blockquote type="cite">`
- HTML: `<div class="gmail_quote">`, `<blockquote>`

Uses `quotequail` (Python) + custom regex. Average parse: <50ms.

### 6.6 AI Cost at Scale

| Scale | Text Extract | Embeddings | Categorization | Extraction | OpenSearch | Total |
|-------|-------------|------------|----------------|------------|-----------|-------|
| 100K/day | $45/mo | $60/mo | $720/mo | $270/mo | $692/mo | **$1,800/mo** |
| 1M/day | $450/mo | $600/mo | $10,800/mo | $10,800/mo | $1,382/mo | **$24,000/mo** |
| 5M/day | $2,250/mo | $3,000/mo | $50,000/mo | $65,000/mo | $2,765/mo | **$90,000/mo** |

---

## 7. IMAP/SMTP Compatibility

**Deferred to Phase 3.** This is significant engineering effort with lower priority than the REST API.

### Architecture (when built):
```
NLB (TCP)
  ├─ :993 (IMAPS) → ECS Fargate: Stalwart Mail Server (Rust, open-source)
  ├─ :143 (IMAP+STARTTLS) → same
  ├─ :587 (SMTP Submission) → ECS Fargate: Haraka (Node.js) → SES SendRawEmail
  └─ :465 (SMTPS) → same
```

**IMAP maps to storage:**
- `FETCH BODY[]` → S3 GetObject (raw MIME)
- `SEARCH` → OpenSearch query
- `STORE FLAGS` → DynamoDB update
- Credentials: API key or generated username/password per inbox

---

## 8. AWS Marketplace Integration

### 8.1 Listing Model: SaaS Contracts with Consumption (Hybrid)

Marketplace is the **post-Pro** channel, not the initial launch channel.

When implemented, customers will be able to commit to a base contract and pay overage on consumption. This supports:

- Growth/Scale committed tiers above Pro
- negotiated private offers
- heavier AI and throughput workloads
- procurement-led enterprise buying

**AWS Revenue Share:** 3% of all revenue processed through Marketplace.

### 8.2 Metering Dimensions (up to 24)

| Dimension Key | Description | Unit |
|---------------|-------------|------|
| `messages_sent` | Outbound emails | Per message |
| `messages_received` | Inbound emails | Per message |
| `inboxes_active` | Active inboxes | Per inbox-hour |
| `domains_active` | Active custom domains | Per domain-hour |
| `api_calls` | Non-message API requests | Per 1,000 |
| `storage_gb` | Email storage consumed | Per GB-hour |
| `webhooks_delivered` | Webhook notifications | Per 1,000 |
| `ai_ops` | Paid AI operations | Per operation |

### 8.3 Customer Onboarding Flow

```
1. Customer subscribes on AWS Marketplace
2. AWS redirects POST to the FreeMail fulfillment endpoint
   with x-amzn-marketplace-token
3. Backend calls ResolveCustomer API → gets CustomerIdentifier, CustomerAWSAccountId, LicenseArn, ProductCode
4. Create tenant, provision resources, generate API keys
5. Associate CustomerAWSAccountId and LicenseArn with tenant for metering
6. Begin metering usage via BatchMeterUsage (hourly)
```

### 8.4 Metering Architecture

```
[API Gateway] → [Kinesis (usage events)]
                        │
                  [Lambda Aggregator - hourly via EventBridge]
                        │
                  [DynamoDB - hourly aggregates per customer]
                        │
                  [Lambda - BatchMeterUsage submission]
                        │
                  [DLQ + CloudWatch Alarms on failure]
```

**Critical rules:**
- Timestamps rounded to UTC hour (last value wins per hour per dimension per customer)
- Records must be submitted within 6 hours (revenue is lost after that)
- DLQ alarm: if metering fails for >4 hours, page operations

### 8.5 Subscription Lifecycle

Subscribe to AWS Marketplace SNS topic via SQS (for durability):

| SNS Action | Response |
|------------|----------|
| `subscribe-success` | Activate customer, start metering |
| `subscribe-fail` | Clean up provisioned resources |
| `unsubscribe-pending` | Continue service until billing period end |
| `unsubscribe-success` | **Stop metering immediately**, disable account |
| `entitlement-updated` | Re-check entitlements, adjust limits |

### 8.6 Pricing Tiers

| Tier | Monthly | Messages Included | Inboxes | Overage/msg |
|------|---------|-------------------|---------|-------------|
| Starter | $29 | 1,000 | 5 | $0.005 |
| Growth | $99 | 10,000 | 25 | $0.003 |
| Scale | $499 | 100,000 | 100 | $0.002 |
| Enterprise | Custom | Custom | Unlimited | Custom |

---

## 9. Multi-Tenancy & Isolation

### 9.1 Data Isolation

| Layer | Mechanism |
|-------|-----------|
| DynamoDB | Partition key prefix (`ORG#{org_id}`) + IAM `dynamodb:LeadingKeys` condition |
| S3 | Prefix-based access (`{org_id}/`) + bucket policy restricting to VPC endpoint |
| OpenSearch | Mandatory `org_id` filter injected by search service (not user-controllable) |
| SES | Per-org configuration sets with independent send rate limits |
| Redis | Key prefix: `{org_id}:` for all tenant-scoped data |

### 9.2 Noisy Neighbor Protection

| Layer | Mechanism |
|-------|-----------|
| API Gateway | Per-API-key throttle via usage plans |
| SQS | Per-org message groups (FIFO) - one org's backlog doesn't block another's |
| SES | Per-configuration-set sending quotas |
| DynamoDB | On-demand mode + adaptive capacity (no shared provisioned to fight over) |
| Lambda | Reserved concurrency on critical functions (auth: 200, send: 100) |

### 9.3 Per-Tenant Quotas

```json
{
  "plan": "growth",
  "quotas": {
    "max_pods": 100,
    "max_inboxes_per_pod": 1000,
    "max_inboxes_total": 10000,
    "max_messages_per_day": 100000,
    "max_attachment_size_mb": 25,
    "max_webhooks": 50,
    "max_api_keys": 100,
    "max_custom_domains": 10,
    "retention_days": 365
  }
}
```

Daily message counts tracked in Redis with 48h TTL.

---

## 10. Observability

### 10.1 Structured Logging

All services emit JSON logs with `org_id`, `request_id`, `trace_id` for tenant-scoped querying via CloudWatch Logs Insights.

### 10.2 Key Metrics

| Metric | Source | Dimensions |
|--------|--------|------------|
| `api.requests` | API Gateway | org_id, endpoint, status_code |
| `api.latency` | API Gateway | org_id, endpoint |
| `messages.sent/received/bounced` | Custom | org_id, inbox_id |
| `webhooks.delivered/failed` | Custom | org_id, webhook_id |
| `ses.bounce_rate/complaint_rate` | SES/CloudWatch | config_set (org) |
| `quota.usage` | Custom | org_id, quota_type |

### 10.3 Alarms

- **P0 (PagerDuty):** API error rate >5% for 5 min; SES bounce rate >5%; Lambda at >80% concurrency limit; Metering DLQ depth >0 for >4 hours
- **P1 (Slack):** API P99 >2s; SQS depth >10K for 10 min; Webhook failure rate >20%
- **P2 (Dashboard):** Per-org usage approaching quota (>80%)

### 10.4 X-Ray Tracing

Enabled on API Gateway + Lambda + SES SDK. 5% sampling rate. End-to-end trace from API request through all downstream calls.

---

## 11. CI/CD & Infrastructure as Code

### 11.1 Canonical Implementation Stack

- **Backend runtime:** Python 3.12 on AWS Lambda
- **Python libraries:** boto3, Pydantic v2, AWS Lambda Powertools, pytest
- **Infrastructure:** TypeScript with AWS CDK v2
- **Frontend and MCP tooling:** TypeScript, React, Vite, Vitest, Playwright
- **Launch SDKs:** Python and Node.js

This keeps the initial system to two languages instead of splitting the backend across Python and PHP. Laravel remains a possible future choice for a different service, but it should not shape the launch platform.

### 11.2 CDK Stack Structure

```
cdk/lib/
  ├── network-stack.ts       # VPC, subnets, security groups, endpoints
  ├── data-stack.ts          # DynamoDB table + GSIs, S3 buckets
  ├── cache-stack.ts         # ElastiCache Redis
  ├── email-stack.ts         # SES rules, configuration sets
  ├── api-stack.ts           # API Gateway, Lambda functions, authorizer
  ├── compute-stack.ts       # Lambda functions, shared layers, SQS queues
  ├── events-stack.ts        # Kinesis, EventBridge, WebSocket API
  ├── ai-stack.ts            # Bedrock config, OpenSearch Serverless, Step Functions
  ├── marketplace-stack.ts   # Marketplace integration (metering, SNS)
  └── observability-stack.ts # CloudWatch dashboards, alarms, X-Ray
```

### 11.3 Deployment Strategy

- **CI/CD tool:** GitHub Actions only
- **AWS auth from CI:** GitHub OIDC federation, no long-lived deploy keys
- **Staging:** auto-deploy on merge to `main`
- **Production:** protected-environment approval and promotion of a commit already deployed to staging
- **Rollback:** automatic for Lambda aliases and manual environment rollback playbook for broader failures

### 11.4 Testing Strategy

- **Python unit tests:** `pytest` on handlers, services, MIME parsing, quota logic, and metering
- **Python integration tests:** Local AWS emulation for DynamoDB, S3, SQS, SES, and EventBridge-compatible flows
- **Frontend unit tests:** `vitest` for the console and MCP-adjacent TypeScript packages
- **Browser smoke tests:** Playwright against staging for signup, inbox creation, send/receive basics, and domain onboarding
- **Infrastructure tests:** CDK synth plus assertion and snapshot tests for every stack

Coverage standards:

- backend coverage floor: **85%**
- critical modules target: **90%+**
- frontend coverage floor: **80%**
- bug fixes require regression tests

### 11.5 Multi-Region Plan

| Phase | Regions | Strategy |
|-------|---------|----------|
| Phase 1 | us-east-1 | Single region |
| Phase 2 | + eu-west-1 | Active-passive, DynamoDB global tables, S3 cross-region replication |
| Phase 3 | + us-west-2 | Active-active, Route 53 latency-based routing |

---

## 12. Cost Analysis

### 12.1 Startup Scale (100K inboxes, 100K messages/day, 50 orgs)

| Category | Monthly Cost |
|----------|-------------|
| SES (send + receive) | $600 |
| API Gateway + Lambda | $350 |
| DynamoDB | $500 |
| S3 | $100 |
| ElastiCache Redis | $600 |
| AI/ML (Bedrock + OpenSearch) | $1,800 |
| Event system (Kinesis + SQS) | $500 |
| ECS Fargate | $200 |
| CloudWatch + misc | $200 |
| **Total** | **~$4,850/mo** |

### 12.2 Growth Scale (1M inboxes, 1M messages/day, 500 orgs)

| Category | Monthly Cost |
|----------|-------------|
| SES | $6,000 |
| API Gateway + Lambda | $3,500 |
| DynamoDB | $10,000 |
| S3 | $2,500 |
| ElastiCache Redis | $1,200 |
| AI/ML | $24,000 |
| Event system | $3,000 |
| ECS Fargate | $2,000 |
| CloudWatch + misc | $1,000 |
| **Total** | **~$53,000/mo** |

### 12.3 Full Scale (10M inboxes, 10M messages/day, 5,000 orgs)

| Category | Monthly Cost |
|----------|-------------|
| SES | $87,000 |
| API/Compute (migrate hot paths to ECS) | $60,000 |
| DynamoDB (switch to provisioned + reserved) | $90,000 |
| S3 | $25,000 |
| ElastiCache Redis | $5,000 |
| AI/ML | $90,000 |
| Event system | $25,000 |
| ECS Fargate | $10,000 |
| CloudWatch + misc | $5,000 |
| **Total** | **~$397,000/mo** |

### 12.4 Unit Economics

| Scale | Cost/message | Cost/inbox/month | Revenue target/msg |
|-------|-------------|------------------|--------------------|
| Startup | $0.0016 | $0.048 | $0.003-0.005 |
| Growth | $0.0018 | $0.053 | $0.003-0.005 |
| Full | $0.0013 | $0.040 | $0.002-0.004 |

At $0.003/message average revenue, gross margins are 60-70% at scale.

---

## 13. Phased Implementation Roadmap

### Phase 0: Foundation
- CDK bootstrap and shared repository structure
- GitHub Actions CI with OIDC-based staging deployment
- Python Lambda package layout and shared test harnesses
- SES verification for `victorymail.dev`

### Phase 1: Free SaaS MVP
- Cognito onboarding and API key issuance
- SES send and receive pipelines
- DynamoDB and S3 data model for orgs, inboxes, messages, threads, and domains
- custom domains, webhooks, `wait`, `otp`, and MCP
- developer console plus Python and Node.js SDKs

### Phase 2: Public Beta Hardening
- coverage and smoke-test enforcement
- abuse controls, quotas, alerts, and retention jobs
- operational runbooks and repeatable staging deploys

### Phase 3: Pro + Paid AI
- single Pro plan
- AI features gated behind paid plans
- Bedrock/OpenSearch cost controls and billing regression coverage

### Phase 4: Marketplace Beyond Pro
- customer migration flow from SaaS to Marketplace
- entitlement sync, `LicenseArn` storage, metering, and private offers

### Phase 5: Scale and Enterprise
- IMAP/SMTP
- multi-region
- enterprise compliance packaging
- dedicated infrastructure where justified

---

## Key Architecture Decisions Summary

| Decision | Chose | Over | Rationale |
|----------|-------|------|-----------|
| Backend runtime | Python 3.12 on Lambda | Laravel/PHP, ECS-first backend | Matches the AWS-native serverless design and keeps launch complexity low |
| API layer | API Gateway + Lambda | ALB + ECS | Built-in auth, throttling, usage plans at lower initial cost |
| Primary DB | DynamoDB single-table | Aurora PostgreSQL | Auto-scaling, natural tenant isolation, no connection management |
| Message storage | DynamoDB (metadata) + S3 (blobs) | All-in-one DB | Keeps items <4KB, avoids 400KB limit, tiered cost |
| Event bus | Kinesis Data Streams | EventBridge / SNS | Ordering, replay, enhanced fan-out per consumer |
| Webhook delivery | Lambda + SQS | ECS Fargate workers | Simpler, auto-scaling, sufficient for <10s timeout deliveries |
| WebSocket | API Gateway WebSocket | AppSync Events | Better API-key auth model, more control |
| Vector search | OpenSearch Serverless | pgvector / Pinecone | Native AWS, auto-scaling, billion-scale, hybrid search |
| Embedding model | Titan V2 (512d) | Cohere / self-hosted | 5-50x cheaper, native Bedrock, sufficient quality |
| Categorization | Haiku default + Sonnet upgrade | Always Sonnet | 10x cost difference; most emails need simple classification |
| IaC | CDK (TypeScript) | Terraform | Higher-level constructs for AWS-native stack |
| Deployment | Canary (CodeDeploy) | Blue/green | Gradual rollout, auto-rollback on error spike |
| Marketplace model | SaaS Contracts + Consumption | Pure SaaS subscription | Supports both committed and pay-as-you-go customers |
| IMAP/SMTP | Deferred to Phase 3 | Phase 1 | REST API is primary; IMAP/SMTP is compatibility feature |

---

## Security Considerations

- **Encryption at rest:** DynamoDB (AWS-owned key), S3 (SSE-S3, KMS for enterprise), Redis (at-rest encryption)
- **Encryption in transit:** TLS 1.2+ everywhere, HTTPS-only APIs, SMTPS/IMAPS
- **API key storage:** Hashed (SHA-256) in DynamoDB, plaintext shown only once at creation
- **Webhook secrets:** Encrypted with KMS, never exposed via API after creation
- **S3 access:** VPC endpoint only, pre-signed URLs for attachment downloads (15-min expiry)
- **IAM:** Least-privilege Lambda execution roles, `dynamodb:LeadingKeys` condition for tenant isolation
- **WAF:** Rate limiting, SQL injection protection, bot detection
- **Audit:** CloudTrail for all API calls, DynamoDB Streams for data change audit
