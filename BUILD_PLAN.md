# VictoryMail Build Plan

## Project Context

**Product**: VictoryMail (based on the AgentMail architecture) -- an API-first email platform for AI agents
**Domain**: `victorymail.dev` (Route53 zone `Z07936581A0X84A25A306`)
**AWS Account**: `933022096014` (user `jwc-non-root-intergalactic`)
**Region**: `us-east-1` (primary)
**IaC**: AWS CDK (TypeScript)
**Lambda Runtime**: Python 3.12
**SES Status**: Production access GRANTED, 50K/day send quota, 14/sec send rate

### What Already Exists
- Route53 hosted zone for `victorymail.dev` (NS + SOA records only)
- SES production access enabled (previously granted for pepstackr.com)
- SES identity verified for `pepstackr.com` (not yet for `victorymail.dev`)
- No infrastructure deployed yet for this project

### Key Naming Decision
The architecture docs reference "agentmail" throughout. We are building this as **VictoryMail** using domain `victorymail.dev`. All resource prefixes will use `victorymail` instead of `agentmail`. The API will be at `api.victorymail.dev`.

---

## Build Phases Overview

```
Phase 0 (NOW)      Project scaffolding, CDK bootstrap, SES domain setup
Phase 1 (Core)     Network, data, cache, email, API, Lambda handlers -- send/receive email
Phase 2 (Product)  Webhooks, custom domains, auth polish, SDK generation
Phase 3 (AI)       Bedrock integration, OpenSearch, semantic search, categorization
Phase 4 (Scale)    WebSocket, Kinesis events, IMAP/SMTP, Marketplace, SaaS billing
```

Each phase is designed so that at its completion, the platform is usable at that level. Phase 1 alone gives you a working email API.

---

## Phase 0: Project Scaffolding & SES Domain Setup

**Goal**: CDK project initialized, CI pipeline running, `victorymail.dev` verified in SES with DKIM/SPF/DMARC/MX records, CDK bootstrapped in account.

### 0.1 CDK Project Initialization
- [ ] Create `cdk/` directory with `cdk init app --language typescript`
- [ ] Configure `tsconfig.json` for strict mode
- [ ] Set up CDK context: `stage` (dev/staging/prod), `region`, `domainName`
- [ ] Create `cdk/bin/victorymail.ts` entry point
- [ ] Create placeholder stack files in `cdk/lib/`:
  - `network-stack.ts`
  - `data-stack.ts`
  - `cache-stack.ts`
  - `email-stack.ts`
  - `api-stack.ts`
  - `compute-stack.ts`
- [ ] Install CDK dependencies: `aws-cdk-lib`, `constructs`, `@types/node`
- [ ] Run `cdk bootstrap aws://933022096014/us-east-1`

### 0.2 Lambda Project Structure
- [ ] Create `lambdas/` directory tree:
  ```
  lambdas/
    shared/
      dynamo_client.py
      redis_client.py
      logger.py
      response.py
      exceptions.py
    authorizer/
      index.py
    api-handlers/
      inboxes/
      messages/
      threads/
      organizations/
      api-keys/
    inbound-processor/
      index.py
      mime_parser.py
      thread_resolver.py
    send-worker/
      index.py
      mime_builder.py
  ```
- [ ] Create `requirements.txt` files for each Lambda group
- [ ] Create shared Lambda layer structure

### 0.3 SES Domain Verification for victorymail.dev
- [ ] Call `ses:CreateEmailIdentity` for `victorymail.dev` with Easy DKIM (RSA 2048)
- [ ] Add DKIM CNAME records to Route53 (3 records)
- [ ] Add SPF TXT record: `v=spf1 include:amazonses.com ~all`
- [ ] Add DMARC TXT record: `v=DMARC1; p=quarantine; rua=mailto:dmarc@victorymail.dev`
- [ ] Add MX record: `10 inbound-smtp.us-east-1.amazonaws.com`
- [ ] Verify DKIM status reaches `SUCCESS`
- [ ] Create default SES configuration set: `victorymail-default`

### 0.4 GitHub Actions CI
- [ ] Create `.github/workflows/ci.yml`: lint, test, `cdk synth` on every PR
- [ ] Create `.github/workflows/deploy-dev.yml`: auto-deploy on merge to `main`
- [ ] Add GitHub secrets for AWS credentials (or set up OIDC federation)

### 0.5 Developer Tooling
- [ ] Create `Makefile` or `scripts/` with common commands:
  - `make synth` -- CDK synthesize
  - `make deploy-dev` -- deploy dev stack
  - `make test` -- run all tests
  - `make lint` -- lint Python + TypeScript

**Phase 0 Exit Criteria**:
- `cdk synth` runs cleanly
- `victorymail.dev` is DKIM-verified in SES
- MX record points to SES inbound
- CI pipeline runs on PRs

---

## Phase 1: Core Platform -- Send & Receive Email via API

**Goal**: A developer can create an org, get an API key, create an inbox, send an email, receive a reply, and list messages -- all via REST API at `api.victorymail.dev`.

### 1.1 NetworkStack
- [ ] VPC with 2 AZs, public + private subnets
- [ ] NAT Gateway (single, to save cost in dev)
- [ ] Security groups:
  - `sg-lambda`: outbound all, no inbound
  - `sg-redis`: inbound 6379 from `sg-lambda`
- [ ] VPC endpoints for: DynamoDB, S3, SES, SQS, Secrets Manager
- [ ] Export VPC ID, subnet IDs, security group IDs

### 1.2 DataStack
- [ ] **DynamoDB single table** (`victorymail-dev`):
  - Partition key: `PK` (String)
  - Sort key: `SK` (String)
  - On-demand capacity
  - Point-in-time recovery enabled
  - DynamoDB Streams: `NEW_AND_OLD_IMAGES`
  - GSIs:
    - `GSI1`: `GSI1PK` / `GSI1SK` (org-based queries)
    - `GSI2`: `GSI2PK` / `GSI2SK` (inbox-based queries)
    - `GSI3`: `GSI3PK` / `GSI3SK` (thread queries)
    - `GSI4`: `GSI4PK` / `GSI4SK` (email address lookups)
- [ ] **S3 buckets** (all SSE-KMS, block public access):
  - `victorymail-dev-raw-email` -- raw MIME storage
  - `victorymail-dev-attachments` -- parsed attachments
  - `victorymail-dev-bodies` -- parsed email bodies (HTML/text)
  - `victorymail-dev-exports` -- data export files
- [ ] S3 lifecycle rules:
  - Raw email: transition to IA after 90 days
  - Attachments: transition to IA after 90 days, Glacier after 365 days
- [ ] Write shared DynamoDB client (`lambdas/shared/dynamo_client.py`):
  - Single-table helpers: `put_item`, `get_item`, `query`, `update_item`, `delete_item`
  - Entity-specific helpers: `create_org`, `create_inbox`, `store_message`
  - Cursor-based pagination helpers

### 1.3 CacheStack
- [ ] ElastiCache Redis (Serverless or single-node `cache.t4g.micro` for dev)
  - AUTH token stored in Secrets Manager
  - In private subnet, `sg-redis` security group
- [ ] Write shared Redis client (`lambdas/shared/redis_client.py`):
  - Connection pool management
  - API key cache (get/set with TTL)
  - Rate limit counter (sliding window)
  - Inbox routing cache

### 1.4 EmailStack
- [ ] SES email identity for `victorymail.dev` (import existing, or verify via CDK)
- [ ] SES Receipt Rule Set: catch-all rule for `victorymail.dev`
  - S3 action: store to `victorymail-dev-raw-email`
  - Lambda action: trigger inbound processor (async)
- [ ] SES configuration set: `victorymail-default`
  - Event destinations via SNS: bounces, complaints, deliveries
- [ ] SNS topics: `victorymail-dev-bounces`, `victorymail-dev-complaints`, `victorymail-dev-deliveries`
- [ ] Activate the Receipt Rule Set

### 1.5 ApiStack
- [ ] API Gateway REST API (regional): `victorymail-dev-api`
- [ ] Custom domain: `api-dev.victorymail.dev` with ACM certificate
- [ ] Route53 alias record for `api-dev.victorymail.dev` -> API Gateway
- [ ] Lambda authorizer: request-based, extracts `Authorization: Bearer <key>`
- [ ] Enable X-Ray tracing
- [ ] Enable CloudWatch access logging
- [ ] CORS: allow all origins (API key auth, not cookie-based)
- [ ] Routes (Phase 1):
  ```
  POST   /v1/organizations
  GET    /v1/organizations/{org_id}
  POST   /v1/api-keys
  GET    /v1/api-keys
  DELETE /v1/api-keys/{key_id}
  POST   /v1/inboxes
  GET    /v1/inboxes
  GET    /v1/inboxes/{inbox_id}
  PATCH  /v1/inboxes/{inbox_id}
  DELETE /v1/inboxes/{inbox_id}
  POST   /v1/inboxes/{inbox_id}/messages
  GET    /v1/inboxes/{inbox_id}/messages
  GET    /v1/inboxes/{inbox_id}/messages/{message_id}
  GET    /v1/inboxes/{inbox_id}/threads
  GET    /v1/inboxes/{inbox_id}/threads/{thread_id}
  GET    /v1/inboxes/{inbox_id}/messages/{message_id}/attachments/{attachment_id}
  ```

### 1.6 ComputeStack -- Lambda Functions
- [ ] **Shared Lambda Layer**: `boto3`, shared utils (`dynamo_client`, `redis_client`, `logger`, `response`, `exceptions`)
- [ ] **Authorizer Lambda** (`authorizer/index.py`):
  - Extract API key from `Authorization: Bearer` header
  - Check Redis cache (5-min TTL)
  - Fallback to DynamoDB lookup
  - Return IAM policy with `org_id` in context
- [ ] **Organization Handlers**:
  - `POST /v1/organizations`: create org, generate first admin API key, return both
  - `GET /v1/organizations/{org_id}`: return org details
- [ ] **API Key Handlers**:
  - `POST /v1/api-keys`: generate key (`vm_live_<random>`), hash + store
  - `GET /v1/api-keys`: list keys (masked)
  - `DELETE /v1/api-keys/{key_id}`: revoke key, invalidate Redis cache
- [ ] **Inbox Handlers**:
  - `POST /v1/inboxes`: create inbox, assign `{random}@victorymail.dev` address, store in DynamoDB + Redis
  - `GET /v1/inboxes`: list by org, cursor pagination
  - `GET /v1/inboxes/{inbox_id}`: get inbox details
  - `PATCH /v1/inboxes/{inbox_id}`: update display_name, status
  - `DELETE /v1/inboxes/{inbox_id}`: soft delete
- [ ] **Inbound Processor Lambda** (`inbound-processor/index.py`):
  - Triggered by SES Receipt Rule (Lambda action)
  - Parse SES notification, extract recipient address
  - Look up inbox by email address (GSI4 or Redis cache)
  - If not found: return bounce disposition
  - Parse MIME: headers, text body, HTML body, attachments
  - Compute thread (Message-ID / In-Reply-To / References)
  - Store message metadata in DynamoDB
  - Store parsed body in S3 (bodies bucket)
  - Store attachments in S3 (attachments bucket)
  - Publish placeholder event (SQS for now)
- [ ] **Send Worker Lambda** (`send-worker/index.py`):
  - Triggered by SQS `victorymail-dev-send-queue`
  - Build MIME message (text + HTML + attachments)
  - Call SES v2 `SendEmail` with configuration set
  - On success: update message status to `sent`
  - On SES throttle: return to SQS with backoff
  - On permanent failure: update status to `failed`
- [ ] **Message Handlers**:
  - `POST /v1/inboxes/{inbox_id}/messages`: validate, store as `queued`, enqueue to SQS
  - `GET /v1/inboxes/{inbox_id}/messages`: list with cursor pagination, filter by direction/date
  - `GET /v1/inboxes/{inbox_id}/messages/{message_id}`: metadata + body (presigned URL or inline)
- [ ] **Thread Handlers**:
  - `GET /v1/inboxes/{inbox_id}/threads`: list threads with message count
  - `GET /v1/inboxes/{inbox_id}/threads/{thread_id}`: all messages in thread
- [ ] **Attachment Handler**:
  - `GET /v1/.../attachments/{attachment_id}`: generate presigned S3 URL
- [ ] **SQS Queues**:
  - `victorymail-dev-send-queue` + DLQ
  - `victorymail-dev-webhook-queue` + DLQ (placeholder for Phase 2)

### 1.7 Observability (Minimal)
- [ ] CloudWatch log groups for all Lambdas (14-day retention for dev)
- [ ] Structured JSON logging in all functions
- [ ] X-Ray tracing enabled on API Gateway + Lambdas
- [ ] Basic CloudWatch alarms:
  - API Gateway 5xx error rate > 5%
  - SES bounce rate > 3%
  - Lambda error rate > 5%
  - SQS DLQ message count > 0

**Phase 1 Exit Criteria**:
- Create org + API key via API
- Create inbox, get a `xyz@victorymail.dev` address
- Send email from that inbox, verify delivery
- Receive email to that inbox, verify it appears in GET messages
- Thread grouping works for reply chains
- All via `api-dev.victorymail.dev`

---

## Phase 2: Webhooks, Custom Domains, SDK

**Goal**: Event-driven integrations via webhooks, customers can bring their own domains, Python + Node.js SDKs published.

### 2.1 Webhook System
- [ ] `POST /v1/webhooks`: register URL, select events, optional HMAC secret
- [ ] `GET /v1/webhooks`, `PATCH /v1/webhooks/{id}`, `DELETE /v1/webhooks/{id}`
- [ ] Webhook delivery Lambda (SQS consumer):
  - POST JSON payload to registered URL
  - `X-VictoryMail-Signature: sha256=<hmac>` header
  - Retry: 30s, 2min, 10min, 1hr, 6hr, 24hr (then give up)
  - Store delivery log (last 100 per webhook)
- [ ] `GET /v1/webhooks/{id}/deliveries`: delivery log with status
- [ ] Webhook endpoint validation on registration (challenge-response)
- [ ] Auto-disable webhook after 90% failure rate over 24h
- [ ] Wire events: `message.received`, `message.sent`, `message.bounced`, `inbox.created`, `inbox.deleted`

### 2.2 Custom Domain Support
- [ ] `POST /v1/domains`: call SES `CreateEmailIdentity`, return DNS records
- [ ] `GET /v1/domains/{id}/verify`: check verification status
- [ ] `GET /v1/domains`, `DELETE /v1/domains/{id}`
- [ ] Automated verification polling: EventBridge every 5 min for pending domains
- [ ] Update SES Receipt Rule to accept custom domains
- [ ] Support sending from custom domains with per-domain DKIM
- [ ] Optional Route53 auto-setup (if domain is in same AWS account)

### 2.3 Additional API Endpoints
- [ ] Draft endpoints: create, list, update, delete, send
- [ ] Pod endpoints: create, list, get, update, assign inboxes
- [ ] Allow/block list endpoints: per-inbox and per-pod
- [ ] Scoped API keys: restricted to specific pod or inbox set
- [ ] Basic metrics endpoint: `GET /v1/metrics`

### 2.4 OpenAPI Spec & SDK Generation
- [ ] Finalize OpenAPI 3.1 spec (`api/openapi.yaml`)
- [ ] Python SDK: async, Pydantic models, retry logic, publish to PyPI
- [ ] Node.js SDK: TypeScript, ESM/CJS, publish to npm
- [ ] Integration tests for both SDKs against dev API

**Phase 2 Exit Criteria**:
- Webhooks fire on message events with HMAC signatures
- Custom domain can be added, verified, and used for send/receive
- SDKs usable for creating inboxes + sending email

---

## Phase 3: AI Features

**Goal**: Semantic search, AI categorization, and structured data extraction on all emails.

### 3.1 OpenSearch Serverless + Embedding Pipeline
- [ ] Deploy OpenSearch Serverless collection (vector search, FAISS, 1536 dims)
- [ ] Embedding Lambda: DynamoDB Stream trigger -> extract text -> Bedrock Titan Embeddings v2 -> store vector
- [ ] Backfill script for existing messages

### 3.2 Semantic Search
- [ ] `POST /v1/inboxes/{inbox_id}/search`: query string + filters
- [ ] Hybrid search: 70% vector similarity + 30% BM25 keyword
- [ ] Search across inbox, pod, or org scope
- [ ] Target P99 < 500ms for single-inbox search

### 3.3 AI Categorization
- [ ] Step Functions state machine: categorize -> extract (conditional) -> embed
- [ ] Categorizer Lambda: Bedrock Claude Haiku, parse response, store category
- [ ] Default categories: inquiry, notification, marketing, transactional, spam, urgent
- [ ] `PUT /v1/inboxes/{inbox_id}/categorization`: custom categories
- [ ] Auto-trigger on every inbound message

### 3.4 Structured Data Extraction
- [ ] Extractor Lambda: Bedrock Claude Sonnet, JSON schema -> structured output
- [ ] `PUT /v1/inboxes/{inbox_id}/extraction`: configure schema
- [ ] `extracted_data` field on message responses

**Phase 3 Exit Criteria**:
- Search returns semantically relevant results
- Inbound emails are auto-categorized
- Extraction returns structured JSON per configured schema

---

## Phase 4: Scale, Real-Time, Marketplace

**Goal**: WebSocket real-time events, IMAP/SMTP compatibility, AWS Marketplace listing, SaaS billing via Stripe.

### 4.1 Kinesis Event Bus
- [ ] Kinesis Data Stream (4 shards, 7-day retention)
- [ ] Migrate all event publishing from SQS to Kinesis
- [ ] Kinesis consumers for: webhook delivery, AI pipeline, analytics

### 4.2 WebSocket API
- [ ] API Gateway WebSocket: `wss://ws.victorymail.dev`
- [ ] Connection management in Redis
- [ ] Subscription model: per-inbox, per-pod, per-org
- [ ] ws-fanout Lambda: Kinesis -> filter -> PostToConnection
- [ ] Heartbeat/ping-pong, stale connection cleanup

### 4.3 IMAP/SMTP (ECS Fargate)
- [ ] IMAP server (Stalwart) with custom DynamoDB/S3 storage backend
- [ ] SMTP relay (Haraka) with SES queue plugin
- [ ] NLB with TCP listeners: 993, 143, 587, 465
- [ ] TLS certs for `imap.victorymail.dev`, `smtp.victorymail.dev`
- [ ] Credential generation API: `POST /v1/inboxes/{id}/credentials`

### 4.4 SaaS Platform & Billing
- [ ] Stripe integration: subscription management, usage metering
- [ ] Free tier: 5 inboxes, 1,000 emails/month
- [ ] Paid tiers: Pro $29, Business $99, Scale $299
- [ ] Developer console web app (Next.js or similar)
- [ ] User auth (Cognito or Auth0)

### 4.5 AWS Marketplace
- [ ] Seller registration
- [ ] Metering pipeline: usage events -> hourly aggregation -> BatchMeterUsage
- [ ] Customer lifecycle: subscribe, entitlement check, unsubscribe
- [ ] Private listing -> public listing

**Phase 4 Exit Criteria**:
- WebSocket delivers events in < 500ms
- IMAP/SMTP work with standard email clients
- Stripe billing operational
- Marketplace listing live

---

## DynamoDB Entity Design (Single Table)

Reference for all Lambda implementations:

| Entity | PK | SK | GSI1PK | GSI1SK |
|--------|----|----|--------|--------|
| Organization | `ORG#<org_id>` | `META` | -- | -- |
| API Key | `ORG#<org_id>` | `KEY#<key_id>` | `KEYHASH#<hash>` | `META` |
| Inbox | `ORG#<org_id>` | `INB#<inbox_id>` | `ORG#<org_id>` | `INB#<inbox_id>` |
| Message | `INB#<inbox_id>` | `MSG#<timestamp>#<msg_id>` | `ORG#<org_id>` | `MSG#<timestamp>` |
| Thread | `INB#<inbox_id>` | `THR#<thread_id>` | `ORG#<org_id>` | `THR#<last_activity>` |
| Domain | `ORG#<org_id>` | `DOM#<domain_id>` | `DOMAIN#<domain>` | `META` |
| Webhook | `ORG#<org_id>` | `WHK#<webhook_id>` | -- | -- |
| Pod | `ORG#<org_id>` | `POD#<pod_id>` | -- | -- |
| Email Lookup | `EMAIL#<address>` | `META` | -- | -- |

**GSI4**: `GSI4PK` = `EMAIL#<address>`, `GSI4SK` = `META` -- for inbound email routing by address.

---

## Infrastructure Cost Estimates (Dev Environment)

| Service | Config | Est. Monthly Cost |
|---------|--------|-------------------|
| VPC + NAT Gateway | 1 NAT GW | $32 |
| DynamoDB | On-demand, low traffic | $5-10 |
| S3 | 4 buckets, minimal data | $1-2 |
| ElastiCache Redis | cache.t4g.micro | $12 |
| Lambda | Pay-per-use, low traffic | $1-5 |
| API Gateway | Pay-per-request | $1-5 |
| SES | 50K/day quota (usage-based) | $1-10 |
| Route53 | Hosted zone + queries | $1 |
| CloudWatch | Logs + metrics | $5-10 |
| ACM | Free | $0 |
| **Total Dev** | | **~$60-85/month** |

---

## Immediate Next Steps (What to Build First)

When we resume, the build order is:

1. **Phase 0.1-0.2**: Initialize CDK project + Lambda directory structure
2. **Phase 0.3**: Verify `victorymail.dev` in SES (can do immediately via AWS CLI)
3. **Phase 0.4**: GitHub Actions CI pipeline
4. **Phase 1.1**: Deploy NetworkStack
5. **Phase 1.2**: Deploy DataStack
6. **Phase 1.3**: Deploy CacheStack
7. **Phase 1.4**: Deploy EmailStack (SES receipt rules)
8. **Phase 1.5**: Deploy ApiStack (API Gateway + authorizer)
9. **Phase 1.6**: Deploy ComputeStack (all Lambda functions)
10. **Phase 1.7**: Basic observability

Each step builds on the previous. Steps 1-3 have no dependencies and can happen in parallel. Steps 4-9 must be sequential (each stack depends on outputs from prior stacks).

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| IaC | CDK TypeScript | Type safety, L2/L3 constructs, documented in architecture |
| Lambda runtime | Python 3.12 | AI/ML ecosystem, documented in architecture |
| Database | DynamoDB single table | Predictable perf at any scale, documented design |
| Cache | ElastiCache Redis | Sub-ms for auth, rate limiting, routing |
| Email transport | SES | Already have production access, integrated with AWS |
| API auth | API key (Bearer token) | No OAuth complexity, AI-agent friendly |
| Domain | victorymail.dev | Purchased, Route53 zone active |
| Naming prefix | `victorymail` | Replaces `agentmail` from architecture docs |
| Dev environment | Single AWS account, `dev` stage | Simplify initial deployment |

---

## Files to Reference During Build

| Topic | File |
|-------|------|
| System architecture | `Projects/01-overview/system-architecture.md` |
| Inbound email flow | `Projects/02-email-transport/inbound-receiving.md` |
| Outbound email flow | `Projects/02-email-transport/outbound-sending.md` |
| Custom domains | `Projects/02-email-transport/custom-domains.md` |
| DKIM/SPF/DMARC | `Projects/02-email-transport/deliverability.md` |
| Threading algorithm | `Projects/02-email-transport/threading.md` |
| API endpoint design | `Projects/03-api-platform/api-design.md` |
| Auth flow | `Projects/03-api-platform/authentication.md` |
| Rate limiting | `Projects/03-api-platform/rate-limiting.md` |
| DynamoDB table design | `Projects/04-database/dynamodb-design.md` |
| S3 bucket design | `Projects/04-database/s3-storage.md` |
| Redis caching | `Projects/04-database/caching.md` |
| CDK stack architecture | `Projects/11-cicd/README.md` |
| Full implementation roadmap | `Projects/13-implementation-roadmap/README.md` |
| Security & IAM | `Projects/14-security/README.md` |
