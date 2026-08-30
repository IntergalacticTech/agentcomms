# System Architecture

## High-Level Architecture Diagram

```
                                    +---------------------------+
                                    |    AWS Marketplace        |
                                    |  Metering & Entitlement   |
                                    +---------------------------+
                                                 |
                                                 | (billing/auth)
                                                 v
+-------------------+          +------------------------------------------+
|                   |          |            API LAYER                      |
|   AI Agent /      |  HTTPS   |  +------------------------------------+  |
|   SDK Client      +--------->|  |  API Gateway (REST)               |  |
|                   |          |  |  - Rate limiting (WAF)             |  |
+-------------------+          |  |  - API key validation             |  |
                               |  |  - Request routing                |  |
+-------------------+          |  +------------------------------------+  |
|                   |  WSS     |  +------------------------------------+  |
|   WebSocket       +--------->|  |  API Gateway (WebSocket)          |  |
|   Client          |          |  |  - Connection management          |  |
|                   |          |  |  - Per-inbox subscriptions         |  |
+-------------------+          |  +------------------------------------+  |
                               +------------------------------------------+
                                                 |
                                                 | (invoke)
                                                 v
+------------------------------------------+     +---------------------------+
|              COMPUTE LAYER               |     |     CACHE LAYER           |
|  +------------------------------------+  |     |  +---------------------+  |
|  |  AWS Lambda Functions              |  |<--->|  |  ElastiCache Redis  |  |
|  |  - API handlers (CRUD)            |  |     |  |  - Session/state    |  |
|  |  - Email processors               |  |     |  |  - Rate limiting    |  |
|  |  - Webhook delivery               |  |     |  |  - Hot data cache   |  |
|  |  - AI orchestration               |  |     |  |  - WebSocket state  |  |
|  |  - Metering reporters             |  |     |  |  - Pub/Sub fanout   |  |
|  +------------------------------------+  |     |  +---------------------+  |
|  +------------------------------------+  |     +---------------------------+
|  |  ECS Fargate (IMAP/SMTP)          |  |
|  |  - IMAP server                    |  |
|  |  - SMTP server                    |  |
|  |  - Protocol translation           |  |
|  +------------------------------------+  |
+------------------------------------------+
         |              |              |
         v              v              v
+------------------------------------------+     +---------------------------+
|              DATA LAYER                  |     |     EVENT LAYER           |
|  +------------------------------------+  |     |  +---------------------+  |
|  |  DynamoDB                          |  |     |  |  Kinesis Data       |  |
|  |  - Organizations, Pods, Inboxes   |  |     |  |  Streams            |  |
|  |  - Messages, Threads, Drafts      |  |     |  |  - Inbound email    |  |
|  |  - Domains, API Keys              |  |     |  |  - Outbound events  |  |
|  |  - Webhooks, Lists, Metrics       |  |     |  |  - AI processing    |  |
|  +------------------------------------+  |     |  +---------------------+  |
|  +------------------------------------+  |     |  +---------------------+  |
|  |  S3                                |  |     |  |  EventBridge        |  |
|  |  - Email bodies (raw MIME)        |  |     |  |  - Scheduled tasks  |  |
|  |  - Attachments                    |  |     |  |  - Cross-service    |  |
|  |  - SES inbound email              |  |     |  |    orchestration    |  |
|  |  - Backup/archive                 |  |     |  +---------------------+  |
|  +------------------------------------+  |     |  +---------------------+  |
+------------------------------------------+     |  |  SQS                |  |
                                                 |  |  - Webhook DLQ      |  |
+------------------------------------------+     |  |  - Processing DLQ   |  |
|              AI LAYER                    |     |  +---------------------+  |
|  +------------------------------------+  |     |  +---------------------+  |
|  |  Amazon Bedrock                    |  |     |  |  SNS                |  |
|  |  - Claude 3.5 Haiku (categorize)  |  |     |  |  - Bounce/complaint |  |
|  |  - Claude 3.5 Sonnet (extract)    |  |     |  |    notifications    |  |
|  |  - Titan Embeddings v2 (search)   |  |     |  +---------------------+  |
|  +------------------------------------+  |     +---------------------------+
|  +------------------------------------+  |
|  |  OpenSearch Serverless             |  |
|  |  - Vector index (embeddings)      |  |
|  |  - Full-text index (email bodies) |  |
|  |  - Hybrid search (semantic + kw)  |  |
|  +------------------------------------+  |
+------------------------------------------+

+------------------------------------------+     +---------------------------+
|           TRANSPORT LAYER                |     |    OBSERVABILITY LAYER    |
|  +------------------------------------+  |     |  +---------------------+  |
|  |  Amazon SES                        |  |     |  |  CloudWatch         |  |
|  |  - Outbound email sending         |  |     |  |  - Metrics          |  |
|  |  - DKIM signing                   |  |     |  |  - Logs             |  |
|  |  - Bounce/complaint handling      |  |     |  |  - Alarms           |  |
|  |  - Inbound email receiving        |  |     |  |  - Dashboards       |  |
|  |  - Receipt rules -> S3 -> Lambda  |  |     |  +---------------------+  |
|  +------------------------------------+  |     |  +---------------------+  |
|  +------------------------------------+  |     |  |  X-Ray              |  |
|  |  Route 53                          |  |     |  |  - Distributed      |  |
|  |  - Custom domain DNS              |  |     |  |    tracing          |  |
|  |  - MX records for inbound         |  |     |  |  - Service map      |  |
|  |  - Domain verification TXT records|  |     |  |  - Latency analysis |  |
|  +------------------------------------+  |     |  +---------------------+  |
+------------------------------------------+     +---------------------------+

+------------------------------------------+
|           SECURITY LAYER                 |
|  +------------------------------------+  |
|  |  WAF          | Secrets Manager    |  |
|  |  KMS          | IAM                |  |
|  |  CloudFront   | VPC                |  |
|  +------------------------------------+  |
+------------------------------------------+
```

---

## Architecture Layers - Detailed Description

### 1. Transport Layer (Amazon SES + Route 53)

The transport layer handles all raw email movement into and out of the platform.

**Amazon SES** operates in two modes:

- **Outbound**: Lambda functions call the SES `SendRawEmail` API with pre-signed DKIM headers. SES handles SMTP delivery, retry logic, bounce processing, and feedback loops. Each organization's sending is isolated via SES configuration sets for reputation tracking.
- **Inbound**: SES receipt rules are configured per verified domain. Inbound email is written to S3, then a Lambda function is invoked to process it. The receipt rule chain applies: spam/virus scanning -> S3 storage -> Lambda notification.

**Route 53** manages DNS for:
- Platform domain (agentmail.com) with MX records pointing to SES inbound
- Custom domains added by customers (programmatic hosted zone creation)
- DKIM CNAME records for email authentication
- SPF TXT records
- Domain verification TXT records
- Health checks for IMAP/SMTP endpoints

### 2. API Layer (API Gateway)

Two API Gateway instances serve different protocols:

**REST API Gateway**:
- Routes all HTTPS API requests to Lambda functions
- API key validation via usage plans
- Request throttling: per-key and per-endpoint limits
- Request/response transformation and validation
- Custom domain mapping (api.agentmail.com)
- Stage variables for environment configuration
- CloudFront distribution in front for global edge caching of GET requests

**WebSocket API Gateway**:
- Manages persistent WebSocket connections for real-time events
- Routes: $connect, $disconnect, $default, subscribe, unsubscribe
- Connection state tracked in ElastiCache Redis
- Lambda integrations for each route
- Scales automatically with connection count

**AWS WAF** sits in front of both gateways:
- Rate limiting rules (prevent abuse beyond API key limits)
- IP reputation filtering
- SQL injection / XSS protection (defense in depth)
- Geo-blocking (if needed for compliance)
- Bot detection

### 3. Compute Layer (Lambda + ECS Fargate)

**AWS Lambda** handles all request-response and event-driven compute:

| Function Group | Count | Purpose | Memory | Timeout |
|---------------|-------|---------|--------|---------|
| API Handlers | ~20 | CRUD operations for all resources | 256-512MB | 30s |
| Inbound Email Processor | 1 | Parse inbound email from S3, store in DynamoDB | 1024MB | 60s |
| Outbound Email Sender | 1 | Construct MIME message, call SES | 512MB | 30s |
| Webhook Dispatcher | 1 | Deliver webhooks to customer endpoints | 256MB | 30s |
| AI Categorizer | 1 | Call Bedrock for email categorization | 512MB | 60s |
| AI Extractor | 1 | Call Bedrock for structured data extraction | 512MB | 60s |
| Embedding Generator | 1 | Call Bedrock Titan for embeddings, index in OpenSearch | 512MB | 30s |
| Metering Reporter | 1 | Report usage to AWS Marketplace Metering API | 256MB | 30s |
| WebSocket Manager | 3 | Handle connect/disconnect/message for WebSocket API | 256MB | 10s |
| Scheduled Jobs | 3 | Domain verification checks, metric aggregation, cleanup | 256MB | 300s |
| Bounce Processor | 1 | Process SES bounce/complaint notifications | 256MB | 30s |

**ECS Fargate** runs long-lived IMAP and SMTP servers:

- **IMAP Server**: Custom Node.js IMAP server (based on wildduck or custom implementation) that translates IMAP commands into DynamoDB/S3 queries. Runs behind NLB on port 993 (IMAPS).
- **SMTP Server**: Custom Node.js SMTP server (based on Haraka or nodemailer-smtp-server) that translates SMTP submission into internal API calls. Runs behind NLB on port 465 (SMTPS).
- Auto-scaling based on connection count (target: 1,000 connections per task)
- Tasks run in private subnets, NLB in public subnets

### 4. Data Layer (DynamoDB + S3)

**DynamoDB** is the primary database, using a single-table design with the following access patterns:

| Access Pattern | PK | SK | Notes |
|---------------|-----|-----|-------|
| Get organization | ORG#{orgId} | ORG#{orgId} | |
| List pods in org | ORG#{orgId} | POD#{podId} | |
| Get inbox | INB#{inboxId} | INB#{inboxId} | |
| List inboxes in pod | POD#{podId} | INB#{inboxId} | GSI1 |
| Get message | INB#{inboxId} | MSG#{timestamp}#{msgId} | Sorted by time |
| List messages in thread | THR#{threadId} | MSG#{timestamp}#{msgId} | GSI2 |
| Lookup by email address | EMAIL#{address} | INB#{inboxId} | GSI3 |
| List domains in org | ORG#{orgId} | DOM#{domainId} | |
| Get API key | KEY#{keyHash} | KEY#{keyHash} | GSI4 |

- **Billing mode**: Pay-per-request (on-demand) to match consumption-based model
- **Encryption**: AWS-managed KMS key (aws/dynamodb)
- **Backup**: Point-in-time recovery enabled, daily on-demand backups to S3
- **TTL**: Used for draft expiration, temporary tokens

**Amazon S3** stores all large/binary data:

| Bucket | Content | Lifecycle | Encryption |
|--------|---------|-----------|------------|
| `agentmail-email-bodies` | Raw MIME messages | 90 days -> IA, 365 days -> Glacier | SSE-S3 |
| `agentmail-attachments` | Email attachments | 90 days -> IA, 365 days -> Glacier | SSE-S3 |
| `agentmail-ses-inbound` | SES inbound email (raw) | 7 days -> delete (processed) | SSE-S3 |
| `agentmail-backups` | DynamoDB backups | 30 days -> Glacier, 365 days -> Deep Archive | SSE-KMS |

### 5. Cache Layer (ElastiCache Redis)

A single ElastiCache Redis cluster (or Serverless) provides:

- **API Response Caching**: Cache frequently-read data (inbox metadata, org config) with 60s TTL
- **Rate Limiting**: Token bucket algorithm using Redis INCR + EXPIRE for per-key API rate limits
- **WebSocket Connection State**: Map of connectionId -> inboxId/podId subscriptions
- **Pub/Sub**: Fan out real-time events to multiple WebSocket connections subscribed to the same inbox
- **Session Data**: Temporary data for multi-step operations (domain verification, bulk operations)
- **Idempotency Keys**: Track recent API request IDs to prevent duplicate processing

Configuration:
- Instance: cache.r7g.large (startup), cache.r7g.xlarge (growth), cluster mode (full scale)
- Deployed in private subnets across 2 AZs
- Encryption in transit and at rest
- Auth token rotation via Secrets Manager

### 6. Event Layer (Kinesis + EventBridge + SQS + SNS)

**Kinesis Data Streams** is the backbone for ordered event processing:

| Stream | Shards (startup) | Shards (full) | Purpose |
|--------|-----------------|---------------|---------|
| `inbound-email` | 2 | 32 | Inbound email processing pipeline |
| `outbound-events` | 2 | 16 | Events for webhook/WebSocket delivery |
| `ai-processing` | 2 | 32 | Queue for AI categorization/extraction |

- Lambda event source mappings consume from each stream
- Shard count scales with message volume (each shard handles 1,000 records/sec or 1MB/sec)
- 24-hour retention (7 days for the inbound stream to allow replay)

**EventBridge** handles scheduled and cross-service events:
- Scheduled rules: domain verification checks (every 5 minutes), metric aggregation (hourly), stale draft cleanup (daily)
- Custom events: organization.created, subscription.changed, quota.exceeded

**SQS** provides dead-letter queues and decoupling:
- Webhook delivery DLQ (failed webhook deliveries for retry)
- AI processing DLQ (failed categorizations/extractions)
- Inbound email processing DLQ

**SNS** handles SES feedback:
- Bounce notification topic
- Complaint notification topic
- Delivery notification topic (optional, for delivery tracking)

### 7. AI Layer (Bedrock + OpenSearch Serverless)

**Amazon Bedrock** provides managed LLM access:

| Model | Use Case | Avg Latency | Cost per 1K Tokens |
|-------|----------|-------------|---------------------|
| Claude 3.5 Haiku | Email categorization | 200ms | ~$0.00025 input, ~$0.00125 output |
| Claude 3.5 Sonnet | Structured data extraction | 800ms | ~$0.003 input, ~$0.015 output |
| Titan Embeddings v2 | Generate email embeddings | 50ms | ~$0.0001 per 1K tokens |

Processing pipeline:
1. New email arrives -> written to Kinesis `ai-processing` stream
2. Lambda consumer reads from stream
3. For categorization: sends email subject + first 2K chars of body to Haiku with org's category prompt
4. For extraction: sends relevant email sections to Sonnet with org's extraction schema
5. For search indexing: sends email subject + body to Titan Embeddings, indexes vector in OpenSearch
6. Results stored in DynamoDB alongside message metadata

**OpenSearch Serverless** provides search capabilities:

| Collection | Index Type | Purpose |
|------------|-----------|---------|
| `agentmail-vectors` | Vector search (FAISS) | Semantic search using Titan embeddings (1024 dimensions) |
| `agentmail-fulltext` | Full-text search | Keyword search across email subjects and bodies |

- Hybrid search: combines vector similarity score with BM25 keyword relevance
- Access policies scoped per organization (data isolation)
- Serverless: automatically scales compute and storage

### 8. DNS Layer (Route 53)

Route 53 manages all DNS operations:

- **Platform domains**: MX records for `*.agentmail.com` pointing to SES inbound endpoints
- **Custom domains**: When a customer adds a domain:
  1. Create a hosted zone (or verify records in customer's existing DNS)
  2. Generate DKIM key pair via SES
  3. Create three DKIM CNAME records
  4. Create MX record pointing to SES
  5. Provide SPF TXT record to customer
  6. Poll for DNS propagation and verify
- **API domain**: api.agentmail.com -> CloudFront -> API Gateway
- **IMAP/SMTP endpoints**: imap.agentmail.com, smtp.agentmail.com -> NLB

### 9. Observability Layer (CloudWatch + X-Ray)

**CloudWatch**:
- Custom metrics for all business KPIs (messages/sec, inbox count, API latency by endpoint)
- Lambda function logs with structured JSON logging
- Composite alarms for SLO tracking (e.g., API p99 < 200ms AND error rate < 0.1%)
- Dashboard per environment (dev, staging, prod)
- Metric math for derived metrics (bounce rate = bounces / sends)
- Log Insights queries for debugging

**X-Ray**:
- Distributed tracing across all Lambda functions
- Service map showing dependencies and latency
- Trace groups for isolating specific customer traffic
- Annotations for organization ID, pod ID, inbox ID (enables per-customer debugging)
- Sampling rules: 100% for errors, 5% for normal requests

### 10. Marketplace Layer

**Marketplace Metering Service**:
- Lambda function reports usage hourly via `BatchMeterUsage` API
- Dimensions: inboxes_active, messages_sent, messages_received, ai_categorizations, ai_extractions, semantic_searches, storage_gb
- Records stored in DynamoDB before reporting (for retry and audit)
- Step Functions orchestrate the metering workflow to ensure exactly-once reporting

**Marketplace Entitlement Service**:
- API handlers check customer entitlements on every request via `GetEntitlements` API
- Entitlement data cached in Redis (5-minute TTL)
- Subscription lifecycle events (subscribe, unsubscribe, renewal) handled via SNS topic from Marketplace
- Lambda processes subscription changes and updates organization status in DynamoDB

---

## Data Flow Diagrams

### Outbound Email Flow

```
SDK Client                API Gateway        Lambda              SES              Recipient
    |                         |                 |                  |                   |
    |  POST /inboxes/{id}/    |                 |                  |                   |
    |  messages               |                 |                  |                   |
    |  {to, subject, body}    |                 |                  |                   |
    +------------------------>|                 |                  |                   |
    |                         |  Validate       |                  |                   |
    |                         |  API key        |                  |                   |
    |                         |  Check rate     |                  |                   |
    |                         |  limit (WAF)    |                  |                   |
    |                         +---------------->|                  |                   |
    |                         |                 |                  |                   |
    |                         |                 |  1. Validate     |                   |
    |                         |                 |     sender owns  |                   |
    |                         |                 |     inbox        |                   |
    |                         |                 |                  |                   |
    |                         |                 |  2. Check        |                   |
    |                         |                 |     entitlement  |                   |
    |                         |                 |     (Redis cache |                   |
    |                         |                 |      -> Marketplace)                 |
    |                         |                 |                  |                   |
    |                         |                 |  3. Build MIME   |                   |
    |                         |                 |     message      |                   |
    |                         |                 |                  |                   |
    |                         |                 |  4. Store in     |                   |
    |                         |                 |     DynamoDB +   |                   |
    |                         |                 |     S3           |                   |
    |                         |                 |                  |                   |
    |                         |                 |  5. SendRawEmail |                   |
    |                         |                 +----------------->|                   |
    |                         |                 |                  |  DKIM sign        |
    |                         |                 |                  |  SMTP deliver     |
    |                         |                 |                  +------------------>|
    |                         |                 |                  |                   |
    |                         |                 |  6. Write to     |                   |
    |                         |                 |     Kinesis      |                   |
    |                         |                 |     (outbound-   |                   |
    |                         |                 |      events)     |                   |
    |                         |                 |                  |                   |
    |                         |  202 Accepted   |                  |                   |
    |  {messageId, status:    |<----------------+                  |                   |
    |   "queued"}             |                 |                  |                   |
    |<------------------------+                 |                  |                   |
    |                         |                 |                  |                   |
    |                         |    [Async]      |                  |                   |
    |                         |    Kinesis ->   |                  |                   |
    |                         |    Lambda:      |                  |                   |
    |                         |    - Webhook    |                  |                   |
    |                         |      delivery   |                  |                   |
    |                         |      (message.  |                  |                   |
    |                         |       sent)     |                  |                   |
    |                         |    - WebSocket  |                  |                   |
    |                         |      push       |                  |                   |
    |                         |    - Metering   |                  |                   |
    |                         |      increment  |                  |                   |
```

### Inbound Email Flow

```
External           SES                S3              Lambda            DynamoDB/S3
Sender                                               (Processor)
  |                 |                  |                 |                  |
  |  SMTP email     |                  |                 |                  |
  +---------------->|                  |                 |                  |
  |                 |                  |                 |                  |
  |                 | 1. Spam/virus    |                 |                  |
  |                 |    scan          |                 |                  |
  |                 |                  |                 |                  |
  |                 | 2. Receipt rule  |                 |                  |
  |                 |    match (domain |                 |                  |
  |                 |    + address)    |                 |                  |
  |                 |                  |                 |                  |
  |                 | 3. Store raw     |                 |                  |
  |                 |    email in S3   |                 |                  |
  |                 +----------------->|                 |                  |
  |                 |                  |                 |                  |
  |                 | 4. Invoke Lambda |                 |                  |
  |                 |    (or write to  |                 |                  |
  |                 |     Kinesis)     |                 |                  |
  |                 +---------------------------------->|                  |
  |                 |                  |                 |                  |
  |                 |                  |                 | 5. Parse MIME    |
  |                 |                  |                 |    (headers,     |
  |                 |                  |                 |     body, atts)  |
  |                 |                  |                 |                  |
  |                 |                  |                 | 6. Lookup inbox  |
  |                 |                  |                 |    by To address |
  |                 |                  |                 |    (GSI3)        |
  |                 |                  |                 |                  |
  |                 |                  |                 | 7. Check allow/  |
  |                 |                  |                 |    block list    |
  |                 |                  |                 |                  |
  |                 |                  |                 | 8. Detect/create |
  |                 |                  |                 |    thread        |
  |                 |                  |                 |    (In-Reply-To, |
  |                 |                  |                 |     References)  |
  |                 |                  |                 |                  |
  |                 |                  |                 | 9. Store message |
  |                 |                  |                 |    metadata in   |
  |                 |                  |                 |    DynamoDB      |
  |                 |                  |                 +----------------->|
  |                 |                  |                 |                  |
  |                 |                  |                 | 10. Store body   |
  |                 |                  |                 |     + attachments|
  |                 |                  |                 |     in S3        |
  |                 |                  |                 +----------------->|
  |                 |                  |                 |                  |
  |                 |                  |                 | 11. Write to     |
  |                 |                  |                 |     Kinesis      |
  |                 |                  |                 |     streams:     |
  |                 |                  |                 |     - outbound-  |
  |                 |                  |                 |       events     |
  |                 |                  |                 |     - ai-        |
  |                 |                  |                 |       processing |
  |                 |                  |                 |                  |
  |                 |                  |                 |                  |
  |    [Async downstream processing]  |                 |                  |
  |                                   |                 |                  |
  |    Kinesis -> Lambda (Webhook):   deliver webhook to customer URL     |
  |    Kinesis -> Lambda (WebSocket): push to connected WebSocket clients |
  |    Kinesis -> Lambda (AI):        categorize + extract + embed        |
  |    Kinesis -> Lambda (Metering):  increment usage counters            |
```

### API Request Flow (Generic Read)

```
SDK Client        CloudFront      API Gateway      WAF         Lambda        Redis       DynamoDB
    |                 |                |             |            |             |             |
    | GET /inboxes    |                |             |            |             |             |
    +---------------->|                |             |            |             |             |
    |                 |                |             |            |             |             |
    |                 | Cache miss?    |             |            |             |             |
    |                 +--------------->|             |            |             |             |
    |                 |                |             |            |             |             |
    |                 |                | Check rules |            |             |             |
    |                 |                +------------>|            |             |             |
    |                 |                |             |            |             |             |
    |                 |                |             | Pass       |             |             |
    |                 |                |<------------+            |             |             |
    |                 |                |                          |             |             |
    |                 |                | Validate API key         |             |             |
    |                 |                | (usage plan)             |             |             |
    |                 |                |                          |             |             |
    |                 |                | Invoke Lambda            |             |             |
    |                 |                +------------------------->|             |             |
    |                 |                |                          |             |             |
    |                 |                |                          | Check cache  |             |
    |                 |                |                          +------------>|             |
    |                 |                |                          |             |             |
    |                 |                |                          | Cache miss   |             |
    |                 |                |                          |<------------+             |
    |                 |                |                          |             |             |
    |                 |                |                          | Query        |             |
    |                 |                |                          +--------------------------->|
    |                 |                |                          |             |             |
    |                 |                |                          | Results      |             |
    |                 |                |                          |<---------------------------+
    |                 |                |                          |             |             |
    |                 |                |                          | Set cache    |             |
    |                 |                |                          +------------>|             |
    |                 |                |                          |             |             |
    |                 |                |  200 OK                  |             |             |
    |                 |                |  {inboxes: [...]}        |             |             |
    |                 |                |<-------------------------+             |             |
    |                 |                |                          |             |             |
    |                 | Cache + return |                          |             |             |
    |  200 OK         |<---------------+                          |             |             |
    |<----------------+                |                          |             |             |
```

### Real-Time Event Flow

```
[Trigger Event]         Kinesis            Lambda             Redis           WebSocket
(new message,           (outbound-         (Event             (Pub/Sub)       API Gateway
 status change)          events)           Dispatcher)
    |                      |                  |                  |                |
    | Write event          |                  |                  |                |
    +--------------------->|                  |                  |                |
    |                      |                  |                  |                |
    |                      | Event source     |                  |                |
    |                      | mapping          |                  |                |
    |                      +----------------->|                  |                |
    |                      |                  |                  |                |
    |                      |                  | 1. Read event    |                |
    |                      |                  |    payload       |                |
    |                      |                  |                  |                |
    |                      |                  | 2. Lookup        |                |
    |                      |                  |    subscribers   |                |
    |                      |                  |    (webhooks +   |                |
    |                      |                  |     websockets)  |                |
    |                      |                  |                  |                |
    |                      |                  | --- WEBHOOK PATH ---              |
    |                      |                  |                  |                |
    |                      |                  | 3a. HTTP POST    |                |
    |                      |                  |     to webhook   |                |
    |                      |                  |     URL with     |                |
    |                      |                  |     HMAC sig     |                |
    |                      |                  |     (retry on    |                |
    |                      |                  |      failure)    |                |
    |                      |                  |                  |                |
    |                      |                  | --- WEBSOCKET PATH ---            |
    |                      |                  |                  |                |
    |                      |                  | 3b. Publish to   |                |
    |                      |                  |     Redis channel|                |
    |                      |                  +----------------->|                |
    |                      |                  |                  |                |
    |                      |                  |                  | Notify all     |
    |                      |                  |                  | subscribers    |
    |                      |                  |                  | (Lambda        |
    |                      |                  |                  |  instances)    |
    |                      |                  |                  |                |
    |                      |                  | 3c. Get          |                |
    |                      |                  |     connectionIds|                |
    |                      |                  |     from Redis   |                |
    |                      |                  |<-----------------+                |
    |                      |                  |                  |                |
    |                      |                  | 3d. POST to      |                |
    |                      |                  |     @connections |                |
    |                      |                  |     API          |                |
    |                      |                  +---------------------------------->|
    |                      |                  |                  |                |
    |                      |                  |                  |      Push to   |
    |                      |                  |                  |      connected |
    |                      |                  |                  |      clients   |
```

### AI Processing Pipeline Flow

```
Inbound Email       Kinesis           Lambda           Bedrock          OpenSearch      DynamoDB
Processor           (ai-processing)   (AI Worker)                       Serverless
    |                    |                |                |                |              |
    | Write event        |                |                |                |              |
    | {msgId, inboxId,   |                |                |                |              |
    |  orgId, body,      |                |                |                |              |
    |  subject}          |                |                |                |              |
    +------------------->|                |                |                |              |
    |                    |                |                |                |              |
    |                    | Batch (up to   |                |                |              |
    |                    | 100 records)   |                |                |              |
    |                    +--------------->|                |                |              |
    |                    |                |                |                |              |
    |                    |                | For each message:               |              |
    |                    |                |                |                |              |
    |                    |                | === STEP 1: CATEGORIZATION ===  |              |
    |                    |                |                |                |              |
    |                    |                | Load org's     |                |              |
    |                    |                | category prompt|                |              |
    |                    |                | from DynamoDB  |                |              |
    |                    |                +--------------------------------------------->|
    |                    |                |                |                |              |
    |                    |                | Call Haiku     |                |              |
    |                    |                | with prompt +  |                |              |
    |                    |                | email content  |                |              |
    |                    |                +--------------->|                |              |
    |                    |                |                |                |              |
    |                    |                | Response:      |                |              |
    |                    |                | {category:     |                |              |
    |                    |                |  "inquiry",    |                |              |
    |                    |                |  confidence:   |                |              |
    |                    |                |  0.95}         |                |              |
    |                    |                |<---------------+                |              |
    |                    |                |                |                |              |
    |                    |                | === STEP 2: EXTRACTION ===     |              |
    |                    |                |                |                |              |
    |                    |                | Load org's     |                |              |
    |                    |                | extraction     |                |              |
    |                    |                | schema         |                |              |
    |                    |                |                |                |              |
    |                    |                | Call Sonnet    |                |              |
    |                    |                | with schema +  |                |              |
    |                    |                | email content  |                |              |
    |                    |                +--------------->|                |              |
    |                    |                |                |                |              |
    |                    |                | Response:      |                |              |
    |                    |                | {invoice_num:  |                |              |
    |                    |                |  "INV-1234",   |                |              |
    |                    |                |  amount: 99.50}|                |              |
    |                    |                |<---------------+                |              |
    |                    |                |                |                |              |
    |                    |                | === STEP 3: EMBEDDING ===      |              |
    |                    |                |                |                |              |
    |                    |                | Call Titan     |                |              |
    |                    |                | Embeddings     |                |              |
    |                    |                | with subject + |                |              |
    |                    |                | body (truncated|                |              |
    |                    |                | to 8K tokens)  |                |              |
    |                    |                +--------------->|                |              |
    |                    |                |                |                |              |
    |                    |                | Vector (1024d) |                |              |
    |                    |                |<---------------+                |              |
    |                    |                |                |                |              |
    |                    |                | Index in       |                |              |
    |                    |                | OpenSearch     |                |              |
    |                    |                +------------------------------->|              |
    |                    |                |                |                |              |
    |                    |                | === STEP 4: PERSIST ===        |              |
    |                    |                |                |                |              |
    |                    |                | Update message |                |              |
    |                    |                | metadata in    |                |              |
    |                    |                | DynamoDB with  |                |              |
    |                    |                | category,      |                |              |
    |                    |                | extracted data,|                |              |
    |                    |                | embedding ref  |                |              |
    |                    |                +--------------------------------------------->|
    |                    |                |                |                |              |
    |                    |                | === STEP 5: NOTIFY ===         |              |
    |                    |                |                |                |              |
    |                    |                | Write event to |                |              |
    |                    |                | outbound-events|                |              |
    |                    |                | Kinesis stream |                |              |
    |                    |                | (triggers      |                |              |
    |                    |                |  webhooks +    |                |              |
    |                    |                |  WebSocket     |                |              |
    |                    |                |  push)         |                |              |
```

---

## Complete AWS Service Table

| # | Service | Role | Layer | Scaling Model |
|---|---------|------|-------|---------------|
| 1 | Amazon SES | Email send/receive transport | Transport | Automatic (request SES quota increase) |
| 2 | Amazon Route 53 | DNS management, custom domains | Transport | Automatic |
| 3 | API Gateway (REST) | HTTP API endpoint | API | Automatic (10K req/sec default) |
| 4 | API Gateway (WebSocket) | Real-time connections | API | Automatic |
| 5 | AWS WAF | API protection, rate limiting | API | Automatic |
| 6 | Amazon CloudFront | API edge caching, DDoS protection | API | Automatic |
| 7 | AWS Lambda | All compute (API + event processing) | Compute | Automatic (1K-10K concurrency) |
| 8 | ECS Fargate | IMAP/SMTP servers | Compute | Auto-scaling (connection-based) |
| 9 | NLB | Load balancer for IMAP/SMTP | Compute | Automatic |
| 10 | Amazon DynamoDB | Primary metadata database | Data | On-demand (automatic) |
| 11 | Amazon S3 | Email bodies, attachments, backups | Data | Unlimited |
| 12 | Amazon ElastiCache (Redis) | Caching, rate limiting, pub/sub | Cache | Manual (node size + count) |
| 13 | Amazon Kinesis Data Streams | Event streaming backbone | Event | Manual (shard count) |
| 14 | Amazon EventBridge | Scheduled tasks, cross-service events | Event | Automatic |
| 15 | Amazon SQS | Dead-letter queues, decoupling | Event | Automatic |
| 16 | Amazon SNS | SES feedback notifications | Event | Automatic |
| 17 | Amazon Bedrock | LLM for categorization/extraction | AI | Automatic (token-based) |
| 18 | Amazon OpenSearch Serverless | Semantic + full-text search | AI | Automatic (OCU-based) |
| 19 | AWS Step Functions | Metering workflow orchestration | Marketplace | Automatic |
| 20 | Marketplace Metering Service | Usage reporting to Marketplace | Marketplace | N/A (API) |
| 21 | Marketplace Entitlement Service | Subscription validation | Marketplace | N/A (API) |
| 22 | Amazon CloudWatch | Metrics, logs, alarms, dashboards | Observability | Automatic |
| 23 | AWS X-Ray | Distributed tracing | Observability | Automatic |
| 24 | AWS Secrets Manager | API keys, Redis auth, DB credentials | Security | N/A |
| 25 | AWS KMS | Encryption key management | Security | N/A |
| 26 | AWS IAM | Service roles, policies | Security | N/A |
| 27 | AWS CodeDeploy | Lambda deployment (canary/linear) | CI/CD | N/A |

---

## Cross-Cutting Concerns

### Multi-Tenancy Isolation

Every layer enforces tenant isolation:
- **API**: API key maps to organization ID; all queries scoped by org
- **DynamoDB**: Partition keys include org/pod/inbox IDs; no cross-tenant queries possible
- **S3**: Object keys prefixed with org ID; bucket policies enforce isolation
- **OpenSearch**: Document-level security scoped by org ID
- **Kinesis**: Events tagged with org ID; consumers filter accordingly
- **Redis**: Key namespace includes org ID prefix
- **SES**: Configuration sets per organization for reputation isolation

### Encryption

- **At rest**: All data encrypted (DynamoDB: aws/dynamodb KMS key, S3: SSE-S3, Redis: at-rest encryption, OpenSearch: AWS-managed key)
- **In transit**: TLS 1.2+ enforced everywhere (API Gateway, Redis, OpenSearch, SES, all internal service calls)
- **API keys**: Stored as SHA-256 hashes in DynamoDB; plaintext only shown once at creation

### Disaster Recovery

- **RPO**: < 1 hour (DynamoDB PITR, S3 versioning, Kinesis replay)
- **RTO**: < 4 hours (infrastructure-as-code redeployment)
- **Multi-AZ**: All stateful services deployed across 2+ AZs
- **Cross-region**: Not initially required; can be added via DynamoDB global tables and S3 cross-region replication
