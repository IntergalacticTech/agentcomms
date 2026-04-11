# Implementation Roadmap

This document lays out the complete 12-month implementation plan for AgentMail, divided into four phases. Each phase has month-by-month task breakdowns, deliverables, team requirements, and success criteria. The timeline assumes a start date of **July 2026** with production launch targeted for **September 2027**.

All dates are estimates. The critical path runs through Phase 1 (core email operations must work before anything else). Phases 2-4 have some flexibility in ordering.

---

## Table of Contents

- [Timeline Overview](#timeline-overview)
- [Phase 1: Core Platform (Months 1-3)](#phase-1-core-platform-months-1-3)
- [Phase 2: AI + Marketplace (Months 4-6)](#phase-2-ai--marketplace-months-4-6)
- [Phase 3: Advanced Features (Months 7-9)](#phase-3-advanced-features-months-7-9)
- [Phase 4: Scale + Multi-Region (Months 10-12)](#phase-4-scale--multi-region-months-10-12)
- [Risk Register](#risk-register)
- [Dependencies](#dependencies)
- [Success Metrics](#success-metrics)

---

## Timeline Overview

```
2026                                              2027
Jul    Aug    Sep    Oct    Nov    Dec    Jan    Feb    Mar    Apr    May    Jun
|------|------|------|------|------|------|------|------|------|------|------|------|
|  Phase 1: Core Platform  |  Phase 2: AI + Mktpl |  Phase 3: Advanced   |  Phase 4: Scale     |
|  M1     M2     M3        |  M4     M5     M6    |  M7     M8     M9    |  M10    M11    M12  |
|                          |                      |                      |                     |
| Infrastructure           | AI features          | Real-time events     | EU region           |
| Email ops                | Custom domains       | IMAP/SMTP            | Optimization        |
| API completion           | Marketplace          | Deliverability       | Enterprise          |
|                          |                      | Polish               |                     |
|                          |                      |                      |                     |
| ● Staging env            | ● AI search live     | ● WebSocket live     | ● Multi-region      |
| ● First API calls        | ● Mktpl limited      | ● IMAP/SMTP live     | ● SOC 2 prep        |
|                          |                      | ● Mktpl public       | ● Enterprise offers |
```

---

## Phase 1: Core Platform (Months 1-3)

**Goal**: Build the foundation -- a functional API that can create inboxes, send email, receive email, and deliver webhooks. By the end of Phase 1, a developer can integrate AgentMail and send/receive email programmatically.

**Team size**: 3-4 engineers (2 backend, 1 infrastructure, 1 full-stack)

### Month 1: Infrastructure Foundation (July 2026)

**Week 1 (Jul 1-4): Project Setup**
- [ ] Initialize CDK project with TypeScript configuration
- [ ] Set up GitHub repository with branch protection, CODEOWNERS, PR template
- [ ] Configure GitHub Actions CI pipeline (lint, test, CDK synth)
- [ ] Set up AWS Organizations with dev, staging, production accounts
- [ ] Configure IAM Identity Center for developer access
- [ ] Set up shared tooling: Python 3.12, Node.js 20, AWS CLI v2, CDK CLI

**Week 2 (Jul 7-11): Network + Data Layer**
- [ ] Deploy NetworkStack: VPC (2 AZs, public/private subnets), security groups, VPC endpoints (DynamoDB, S3, SES, SQS, Secrets Manager)
- [ ] Deploy DataStack: DynamoDB single table (on-demand capacity), 4 S3 buckets (raw-email, attachments, bodies, exports) with server-side encryption (SSE-KMS)
- [ ] Configure S3 bucket policies, CORS, and lifecycle rules (basic: 90-day transition to IA)
- [ ] Create DynamoDB table with GSIs: GSI1 (org_id-based queries), GSI2 (inbox-based queries), GSI3 (thread queries)
- [ ] Enable DynamoDB Streams (NEW_AND_OLD_IMAGES)
- [ ] Write shared DynamoDB client library (`lambdas/shared/dynamo_client.py`) with single-table helper functions

**Week 3 (Jul 14-18): SES Configuration + Cache**
- [ ] Deploy EmailStack: SES email identity for platform domain (agentmail.dev), Easy DKIM configuration, SPF/DMARC DNS records
- [ ] Request SES production access (exit sandbox) -- submit support ticket with use case description
- [ ] Configure SES Receipt Rule Set with catch-all rule: S3 action (store raw MIME) + Lambda action (inbound router placeholder)
- [ ] Set up MX records for agentmail.dev pointing to SES inbound endpoint
- [ ] Create default SES configuration set with event destinations (SNS topics for bounce, complaint, delivery)
- [ ] Deploy CacheStack: ElastiCache Redis (1 shard, 1 replica, cache.r7g.medium) with AUTH token
- [ ] Write shared Redis client library (`lambdas/shared/redis_client.py`) with connection pooling

**Week 4 (Jul 21-25): API Gateway + Authorizer**
- [ ] Deploy ApiStack: API Gateway REST API (regional), custom domain mapping (api-dev.agentmail.dev), request validation
- [ ] Implement Lambda authorizer: API key extraction from `Authorization: Bearer` header, Redis cache lookup (5-minute TTL), DynamoDB fallback, return IAM policy with org_id in context
- [ ] Create initial route stubs: `POST /v1/inboxes`, `GET /v1/inboxes`, `GET /v1/inboxes/{id}`
- [ ] Implement structured JSON logger (`lambdas/shared/logger.py`) with org_id, request_id, trace_id on every line
- [ ] Implement error handling middleware with standard error response format
- [ ] Write unit tests for authorizer (moto mocks for DynamoDB, mock Redis)
- [ ] Enable X-Ray tracing on API Gateway and Lambda

**Month 1 Deliverables:**
- VPC, DynamoDB, S3, Redis, SES, API Gateway all deployed in dev environment
- Authorizer working with API key authentication
- CI pipeline running on every PR (lint, unit test, CDK synth)
- Structured logging in place

### Month 2: Email Operations (August 2026)

**Week 5 (Jul 28 - Aug 1): Inbox CRUD**
- [ ] Implement `POST /v1/inboxes` (create inbox): generate inbox_id, assign email address ({random}@agentmail.dev), store in DynamoDB, cache in Redis
- [ ] Implement `GET /v1/inboxes/{id}` (get inbox): Redis cache check, DynamoDB fallback
- [ ] Implement `GET /v1/inboxes` (list inboxes): DynamoDB query on org_id GSI with pagination (cursor-based, 50 per page)
- [ ] Implement `PATCH /v1/inboxes/{id}` (update inbox): display_name, status (active/disabled)
- [ ] Implement `DELETE /v1/inboxes/{id}` (delete inbox): soft delete (mark as deleted), scheduled hard delete after 30 days
- [ ] Write integration tests for inbox CRUD against DynamoDB Local
- [ ] Implement organization CRUD endpoints (`POST /v1/organizations`, `GET /v1/organizations/{id}`)
- [ ] Implement API key management (`POST /v1/api-keys`, `GET /v1/api-keys`, `DELETE /v1/api-keys/{id}`)

**Week 6 (Aug 4-8): Inbound Email Processing**
- [ ] Implement Lambda inbound router: parse SES notification, extract recipient address, resolve inbox from address, reject if inbox not found (bounce with 550)
- [ ] Implement MIME parsing library (`lambdas/inbound-processor/mime_parser.py`): extract headers, text body, HTML body, attachments, inline images
- [ ] Implement thread computation (`lambdas/inbound-processor/thread_resolver.py`): Message-ID/In-Reply-To/References header parsing, thread resolution algorithm, new thread creation with atomic UID counter
- [ ] Store message metadata in DynamoDB (PK: INBOX#{inbox_id}, SK: MSG#{timestamp}#{message_id})
- [ ] Store raw MIME in S3 (raw-email bucket), parsed body in S3 (bodies bucket)
- [ ] Store attachments in S3 (attachments bucket) with content-type metadata
- [ ] Publish `message.received` event to Kinesis (placeholder: SQS for now, Kinesis in Phase 3)
- [ ] Write integration tests: send real email to SES sandbox address, verify DynamoDB + S3 storage

**Week 7 (Aug 11-15): Outbound Sending**
- [ ] Implement `POST /v1/inboxes/{id}/messages` (send message): validate request, build MIME message, queue to SQS
- [ ] Implement SQS send worker Lambda: dequeue message, construct MIME (text + HTML + attachments), call SES v2 `SendEmail` with configuration set, store sent message metadata in DynamoDB
- [ ] Implement MIME builder (`lambdas/send-worker/mime_builder.py`): multipart/alternative (text + HTML), multipart/mixed (with attachments), proper header encoding (RFC 2047)
- [ ] Add SES message tags for tracking: org_id, inbox_id, message_id
- [ ] Implement CC, BCC, Reply-To header support
- [ ] Implement send rate limiting per organization (Redis counter, configurable limit)
- [ ] Store outbound message metadata in DynamoDB with `direction: outbound`
- [ ] Write unit tests for MIME builder, integration tests for full send flow

**Week 8 (Aug 18-22): Message CRUD + Threading**
- [ ] Implement `GET /v1/inboxes/{id}/messages` (list messages): paginated query, filter by direction (inbound/outbound), filter by date range
- [ ] Implement `GET /v1/inboxes/{id}/messages/{msg_id}` (get message): metadata from DynamoDB, body from S3 (presigned URL or inline)
- [ ] Implement `GET /v1/inboxes/{id}/threads` (list threads): query threads for inbox, include message count and last activity
- [ ] Implement `GET /v1/inboxes/{id}/threads/{thread_id}` (get thread): return all messages in thread, ordered chronologically
- [ ] Implement attachment download: `GET /v1/inboxes/{id}/messages/{msg_id}/attachments/{att_id}` returns presigned S3 URL
- [ ] Implement attachment upload for outbound messages: presigned PUT URL workflow
- [ ] Implement text extraction from email bodies: strip HTML tags, extract reply content (strip quoted text), provide `text_content` field on message response
- [ ] Add webhook delivery (basic): SQS queue + Lambda, POST event payload to registered webhook URL, 3 retries with exponential backoff

**Week 9 (Aug 25-29): Webhook Foundation + Polish**
- [ ] Implement `POST /v1/webhooks` (register webhook): URL, events to subscribe, optional secret for HMAC
- [ ] Implement `GET /v1/webhooks`, `PATCH /v1/webhooks/{id}`, `DELETE /v1/webhooks/{id}`
- [ ] Implement webhook delivery Lambda: POST JSON payload to URL, include `X-AgentMail-Signature` header (HMAC-SHA256), retry on 5xx or timeout (3 retries, 30s/60s/120s backoff)
- [ ] Store webhook delivery logs in DynamoDB (last 100 deliveries per webhook)
- [ ] Wire inbound processor to trigger webhook delivery for `message.received` events
- [ ] Wire send worker to trigger webhook delivery for `message.sent` events
- [ ] Deploy all Month 2 work to staging environment
- [ ] Run end-to-end test: create inbox → send message → receive reply → verify webhook delivery

**Month 2 Deliverables:**
- Complete email send/receive pipeline working end-to-end
- Message CRUD, thread listing, attachment handling
- Basic webhook delivery for message events
- All deployed to staging environment

### Month 3: API Completion (September 2026)

**Week 10 (Sep 1-5): Remaining CRUD Endpoints**
- [ ] Implement draft endpoints: `POST /v1/inboxes/{id}/drafts` (create), `GET /v1/inboxes/{id}/drafts` (list), `PATCH /v1/inboxes/{id}/drafts/{draft_id}` (update), `DELETE /v1/inboxes/{id}/drafts/{draft_id}` (delete), `POST /v1/inboxes/{id}/drafts/{draft_id}/send` (send draft)
- [ ] Implement pod endpoints: `POST /v1/pods` (create pod), `GET /v1/pods` (list), `GET /v1/pods/{id}` (get), `PATCH /v1/pods/{id}` (update), assign inboxes to pods
- [ ] Implement allow/block list endpoints: `PUT /v1/inboxes/{id}/lists/allow`, `PUT /v1/inboxes/{id}/lists/block`, `GET /v1/inboxes/{id}/lists`
- [ ] Implement basic metrics endpoint: `GET /v1/metrics` (messages sent/received counts, inbox count, API call count for current billing period)

**Week 11 (Sep 8-12): SDK Generation + Text Processing**
- [ ] Finalize OpenAPI 3.1 specification (`api/openapi.yaml`) with all endpoints, request/response schemas, and examples
- [ ] Set up OpenAPI Generator for Python SDK: async support, Pydantic models, retry logic
- [ ] Generate Python SDK, write integration tests against staging API
- [ ] Set up OpenAPI Generator for Node.js SDK: TypeScript types, ESM/CJS dual build
- [ ] Generate Node.js SDK, write integration tests against staging API
- [ ] Publish Python SDK to internal PyPI (testpypi initially)
- [ ] Publish Node.js SDK to internal npm registry
- [ ] Implement reply text stripping: detect quoted text patterns ("> " lines, "On ... wrote:" blocks, Outlook-style "-----Original Message-----"), return clean reply text in API response

**Week 12 (Sep 15-19): CI/CD Pipeline + Observability**
- [ ] Configure GitHub Actions deploy-staging.yml: auto-deploy on merge to main, smoke tests after deploy
- [ ] Configure GitHub Actions deploy-prod.yml: manual trigger, approval gate, canary deployment with CodeDeploy
- [ ] Set up CloudWatch dashboards: platform health (API errors, latency, SES metrics), email volume, webhook health
- [ ] Configure P0 alarms: API error rate >5%, SES bounce rate >5%, Lambda concurrency >80%
- [ ] Configure P1 alarms: API P99 >2s, SQS depth >10K, webhook failure >20%
- [ ] Set up PagerDuty integration for P0 alarms, Slack integration for P1 alarms
- [ ] Write deployment runbook: pre-deployment checklist, rollback procedure, post-deployment verification

**Week 13 (Sep 22-26): Staging Hardening + Documentation**
- [ ] Full staging environment testing: create 1,000 inboxes, send 10,000 messages, verify all endpoints
- [ ] Fix all bugs found during staging testing
- [ ] Write API documentation (auto-generated from OpenAPI spec + hand-written guides)
- [ ] Write quickstart guide: create account, get API key, create inbox, send first email (Python and Node.js examples)
- [ ] Security review: ensure all S3 buckets are private, all Lambda functions have least-privilege IAM roles, all API endpoints require authentication
- [ ] Performance baseline: measure and document P50/P95/P99 latency for all endpoints

**Month 3 Deliverables:**
- All REST API endpoints implemented and tested
- Python and Node.js SDKs published
- CI/CD pipeline with staging auto-deploy and production canary
- CloudWatch dashboards and alarms operational
- Staging environment fully functional

**Phase 1 Exit Criteria:**
- A developer can create an organization, generate an API key, create an inbox, send a message, receive a reply, and get a webhook notification -- all through the REST API or SDK
- API uptime >99% on staging over 7 consecutive days
- All unit and integration tests passing
- Zero P0 alarms firing

---

## Phase 2: AI + Marketplace (Months 4-6)

**Goal**: Add AI-powered email features (semantic search, categorization, extraction), custom domain support, and AWS Marketplace listing. By the end of Phase 2, AgentMail has its first paying customers via Marketplace.

**Team size**: 4-5 engineers (2 backend, 1 AI/ML, 1 infrastructure, 1 full-stack)

### Month 4: AI Features (October 2026)

**Week 14 (Sep 29 - Oct 3): OpenSearch + Embedding Pipeline**
- [ ] Deploy AiStack: OpenSearch Serverless collection with vector search enabled (FAISS engine, 1536 dimensions for Titan Embeddings v2)
- [ ] Configure OpenSearch access policy (VPC-only, IAM authentication)
- [ ] Implement embedding Lambda: receive message from DynamoDB Stream, extract text content, call Bedrock Titan Embeddings v2, store vector in OpenSearch
- [ ] Define OpenSearch index mapping: message_id, inbox_id, org_id, subject, body_text, from, to, date, vector_embedding, thread_id, labels
- [ ] Implement backfill script: process existing messages in staging and generate embeddings
- [ ] Write integration tests: store message → verify embedding in OpenSearch

**Week 15 (Oct 6-10): Semantic Search**
- [ ] Implement `POST /v1/inboxes/{id}/search` endpoint: accept query string, optional filters (date_range, from, has_attachment, thread_id, labels)
- [ ] Implement search flow: embed query via Titan v2 → kNN search in OpenSearch → return ranked results with highlights
- [ ] Implement hybrid search: combine vector similarity (semantic) with BM25 text match (keyword), weighted 70/30
- [ ] Support search across pod (all inboxes in pod) and organization scope
- [ ] Add pagination to search results (limit, offset)
- [ ] Benchmark search latency: target P99 < 500ms for single-inbox search, < 2s for org-wide search
- [ ] Write integration tests and load tests for search

**Week 16 (Oct 13-17): AI Categorization**
- [ ] Implement Step Functions state machine for AI pipeline orchestration: categorize → extract (conditional) → embed (always)
- [ ] Implement categorizer Lambda: receive message text, call Bedrock Claude 3.5 Haiku with categorization prompt, parse response, store category on message in DynamoDB
- [ ] Define default categories: inquiry, notification, marketing, transactional, spam, urgent, other
- [ ] Support custom category definitions per inbox or pod (stored in DynamoDB, loaded by categorizer)
- [ ] Implement `PUT /v1/inboxes/{id}/categorization` (configure custom categories)
- [ ] Wire inbound processor to trigger AI pipeline Step Function for every received message
- [ ] Add `category` field to message response and list filtering
- [ ] Write unit tests with mocked Bedrock responses

**Week 17 (Oct 20-24): AI Extraction + Integration**
- [ ] Implement extractor Lambda: receive message text + extraction schema, call Bedrock Claude 3.5 Sonnet, parse structured JSON response, store extracted data on message
- [ ] Implement `PUT /v1/inboxes/{id}/extraction` (configure extraction schema): accept JSON schema definition for what to extract
- [ ] Add `extracted_data` field to message response
- [ ] Example schemas: invoice (amount, due_date, vendor), shipping (tracking_number, carrier, status), meeting (date, time, location, attendees)
- [ ] Implement extraction caching: if same schema, only extract from new messages
- [ ] End-to-end test: receive invoice email → categorize as "transactional" → extract amount and due date → searchable by "invoices over $1000"
- [ ] Performance optimization: batch categorization requests, Bedrock prompt caching for system prompts

**Month 4 Deliverables:**
- Semantic search working across inboxes
- AI categorization on all inbound messages
- Structured data extraction for configured inboxes
- Step Functions pipeline orchestrating all AI features

### Month 5: Domains + Pods + Webhooks (November 2026)

**Week 18 (Oct 27-31): Custom Domain Support**
- [ ] Implement `POST /v1/domains` (add domain): call SES `CreateEmailIdentity`, return required DNS records (3 DKIM CNAMEs, SPF TXT, DMARC TXT, MX record for inbound, verification TXT)
- [ ] Implement `GET /v1/domains/{id}/verify` (check verification): poll SES `GetEmailIdentity`, return status of each DNS record
- [ ] Implement automated verification polling: EventBridge rule triggers Lambda every 5 minutes to check unverified domains, fire `domain.verified` event when complete
- [ ] Implement `GET /v1/domains` (list domains), `DELETE /v1/domains/{id}` (remove domain)
- [ ] Support inbound email on custom domains: update SES Receipt Rule Set to accept custom domain MX, route to existing inbound pipeline
- [ ] Support outbound sending from custom domains: use domain-specific DKIM keys, per-domain configuration set
- [ ] Implement domain health monitoring: check DNS records periodically, alert if DKIM/SPF/DMARC records are removed or changed
- [ ] Write integration tests: add domain → configure DNS → verify → send email from custom domain

**Week 19 (Nov 3-7): Pods and Scoped API Keys**
- [ ] Enhance pod implementation: per-pod webhook configuration, per-pod categorization config, per-pod extraction schema
- [ ] Implement scoped API keys: create API keys that are restricted to a specific pod or set of inboxes
- [ ] Implement pod-level allow/block lists that cascade to all inboxes in the pod
- [ ] Implement pod-level metrics aggregation
- [ ] Update all list endpoints to support pod filtering: `GET /v1/inboxes?pod_id=xxx`, `GET /v1/messages?pod_id=xxx`
- [ ] Write documentation for multi-tenant usage patterns (one pod per customer)

**Week 20 (Nov 10-14): Advanced Webhook Features**
- [ ] Implement HMAC-SHA256 signing for all webhook deliveries: `X-AgentMail-Signature: sha256=<hex>` computed over request body with webhook secret
- [ ] Implement webhook endpoint validation: on registration, send POST with `challenge` field, endpoint must return the challenge in response body
- [ ] Implement webhook delivery status dashboard data: success rate, average latency, last 10 delivery attempts
- [ ] Implement automatic webhook disabling: if failure rate >90% over 24 hours, disable webhook and notify org admin
- [ ] Implement webhook event types: message.received, message.sent, message.bounced, message.complained, inbox.created, inbox.deleted, domain.verified, domain.failed
- [ ] Implement webhook retry with exponential backoff: 30s, 2min, 10min, 1hr, 6hr, 24hr, 48hr, 72hr (then give up)
- [ ] Implement webhook delivery log export: `GET /v1/webhooks/{id}/deliveries` with pagination

**Week 21 (Nov 17-21): Integration Testing + Fixes**
- [ ] Full integration testing of all Phase 2 features in staging
- [ ] Performance testing: AI pipeline latency, search latency, domain verification flow
- [ ] Fix all bugs and edge cases found during testing
- [ ] Update Python and Node.js SDKs with new endpoints
- [ ] Publish updated SDKs

**Month 5 Deliverables:**
- Custom domain support with automated verification
- Pods with scoped API keys
- Advanced webhook features (HMAC, validation, retry)
- Updated SDKs

### Month 6: Marketplace (December 2026)

**Week 22 (Nov 24-28): Marketplace Seller Setup**
- [ ] Complete AWS Marketplace seller registration: legal entity, tax information, bank account for disbursements
- [ ] Create SaaS product listing: product name, description, highlights, architecture diagram, support contact
- [ ] Define pricing dimensions in Marketplace: inboxes (per unit/month), messages_sent, messages_received, ai_categorizations, ai_extractions, semantic_searches, storage_gb
- [ ] Define contract tiers: Starter ($29/mo), Growth ($99/mo), Scale ($499/mo), Enterprise (custom)
- [ ] Configure free trial: 14 days, 100 inboxes, 5,000 messages included
- [ ] Submit listing for Marketplace review (typically 2-4 weeks for approval)

**Week 23 (Dec 1-5): Metering Pipeline**
- [ ] Deploy MarketplaceStack: metering aggregation DynamoDB table, Kinesis-to-aggregation Lambda, hourly metering Lambda, DLQ for failures
- [ ] Implement usage event collection: every API call that contributes to a billing dimension writes a usage event to Kinesis
- [ ] Implement hourly aggregation Lambda (EventBridge scheduled): read usage events from aggregation table, group by org_id and dimension, compute hourly totals
- [ ] Implement metering submission Lambda: call `BatchMeterUsage` with hourly aggregates, handle `DuplicateRequest` idempotently, send failures to DLQ
- [ ] Implement DLQ reprocessor: manual trigger to replay failed metering records
- [ ] Write integration tests with mocked Marketplace Metering API
- [ ] Implement metering reconciliation: compare submitted records against internal usage tables, alert on discrepancies

**Week 24 (Dec 8-12): Customer Lifecycle**
- [ ] Implement fulfillment Lambda (API Gateway endpoint): receive POST from Marketplace after customer subscribes, call `ResolveCustomer` to get customer_identifier, create organization + API keys, redirect to onboarding page
- [ ] Implement SNS lifecycle handler: subscribe to Marketplace SNS topic, handle `subscribe-success`, `unsubscribe-pending`, `unsubscribe-success` events
- [ ] Implement entitlement checking: on every API call, verify customer has active Marketplace subscription and sufficient entitlements
- [ ] Implement graceful unsubscribe: on `unsubscribe-pending`, disable new inbox creation, allow 30 days data export, then soft-delete on `unsubscribe-success`
- [ ] Write customer onboarding flow: Marketplace purchase → redirect → API key display → quickstart guide
- [ ] Test full lifecycle: subscribe → use API → submit metering → verify Marketplace dashboard shows usage → unsubscribe

**Week 25 (Dec 15-19): Limited Visibility + Testing**
- [ ] Submit product for Limited Visibility (private) listing on Marketplace
- [ ] Create 3-5 private offers for beta customers
- [ ] Onboard 2-3 beta customers: provide white-glove setup, collect feedback
- [ ] Monitor metering pipeline: verify hourly submissions, check Marketplace revenue dashboard
- [ ] Fix any issues found during beta onboarding
- [ ] Prepare for public listing (Phase 3, Month 9)

**Week 26 (Dec 22-26): Holiday Buffer**
- [ ] Buffer week for overflows from previous weeks
- [ ] Documentation updates
- [ ] Technical debt cleanup

**Month 6 Deliverables:**
- AWS Marketplace listing (limited visibility / private)
- Metering pipeline submitting usage hourly
- Customer lifecycle management (subscribe, unsubscribe)
- 2-3 beta customers onboarded

**Phase 2 Exit Criteria:**
- AI features (search, categorization, extraction) working reliably in production
- Custom domains can be added, verified, and used for sending/receiving
- At least 2 paying customers via Marketplace
- Metering pipeline submitting accurately (reconciliation shows <1% discrepancy)
- SDKs updated with all new endpoints

---

## Phase 3: Advanced Features (Months 7-9)

**Goal**: Add real-time events (WebSocket, Kinesis), protocol compatibility (IMAP/SMTP), deliverability management, and polish for public Marketplace listing.

**Team size**: 5-6 engineers (3 backend, 1 infrastructure, 1 AI/ML, 1 full-stack/DevEx)

### Month 7: Real-Time Events (January 2027)

**Week 27 (Jan 5-9): Kinesis Event Bus**
- [ ] Deploy EventsStack: Kinesis Data Stream (4 shards, 7-day retention)
- [ ] Migrate event publishing from SQS to Kinesis: inbound processor, send worker, webhook events, AI pipeline completions, domain verification
- [ ] Implement event schema versioning: each event has `version`, `type`, `timestamp`, `org_id`, `data` fields
- [ ] Implement Kinesis consumer for webhook delivery: replace SQS-based webhook trigger with Kinesis consumer Lambda (event source mapping)
- [ ] Implement Kinesis consumer for AI pipeline: trigger Step Function on `message.received` events
- [ ] Event types: `message.received`, `message.sent`, `message.bounced`, `message.complained`, `message.delivered`, `inbox.created`, `inbox.updated`, `inbox.deleted`, `thread.created`, `thread.updated`, `domain.verified`, `domain.failed`, `webhook.delivered`, `webhook.failed`, `ai.categorized`, `ai.extracted`

**Week 28 (Jan 12-16): WebSocket API**
- [ ] Deploy WebSocket API (API Gateway WebSocket): `$connect`, `$disconnect`, `$default` routes
- [ ] Implement connection management Lambda: on `$connect`, validate API key, store connection_id + org_id + subscriptions in Redis
- [ ] Implement `$default` message handler: parse subscription requests (`subscribe inbox:inb_xyz789`, `subscribe pod:pod_abc123`, `subscribe org:*`)
- [ ] Implement ws-fanout Lambda: Kinesis consumer that reads events, looks up subscribed connections in Redis, pushes events via API Gateway Management API `PostToConnection`
- [ ] Handle stale connections: if `PostToConnection` returns `GoneException`, remove connection from Redis
- [ ] Implement heartbeat: server sends ping every 30 seconds, client must respond with pong within 10 seconds or connection is closed
- [ ] Write integration test: connect WebSocket → subscribe to inbox → send email to inbox → verify event received on WebSocket

**Week 29 (Jan 19-23): Event Replay + Polish**
- [ ] Implement event replay API: `POST /v1/events/replay` with `start_time`, `end_time`, `event_types`, `org_id` parameters
- [ ] Event replay reads from Kinesis extended retention (7 days) and re-publishes to a replay Kinesis stream → triggers webhook delivery
- [ ] Implement event filtering: WebSocket clients can subscribe with filters (`subscribe inbox:inb_xyz789 events:message.received,message.sent`)
- [ ] Implement connection limiting: max 100 WebSocket connections per organization
- [ ] Load test WebSocket: 1,000 concurrent connections, 100 events/second, verify <500ms delivery latency
- [ ] Update SDKs with WebSocket client (Python: `websockets` library, Node.js: built-in `WebSocket`)

**Week 30 (Jan 26-30): Testing + Buffer**
- [ ] Full integration testing of Kinesis + WebSocket pipeline
- [ ] Verify webhook delivery still works correctly with Kinesis backend
- [ ] Performance comparison: SQS-based vs Kinesis-based webhook delivery latency
- [ ] Documentation: WebSocket connection guide, event types reference

**Month 7 Deliverables:**
- Kinesis event bus replacing SQS for event distribution
- WebSocket API for real-time event streaming
- Event replay capability
- SDKs updated with WebSocket client

### Month 8: Protocol Compatibility + Deliverability (February 2027)

**Week 31 (Feb 2-6): IMAP Server Setup**
- [ ] Evaluate Stalwart commercial license terms, sign if needed (or proceed with AGPL evaluation)
- [ ] Build IMAP server Docker image: Stalwart base + custom AgentMail storage backend plugin
- [ ] Implement storage backend: LOGIN → Redis/DynamoDB credential lookup, SELECT → DynamoDB mailbox stats, FETCH → DynamoDB metadata + S3 body retrieval
- [ ] Implement STORE FLAGS → DynamoDB flag updates, SEARCH → DynamoDB filter + OpenSearch full-text, EXPUNGE → DynamoDB/S3 delete
- [ ] Deploy ECS Fargate service for IMAP server (2 tasks minimum)

**Week 32 (Feb 9-13): IMAP Testing + SMTP Setup**
- [ ] Test IMAP server with Thunderbird, Apple Mail, mutt, imapsync
- [ ] Fix compatibility issues found during testing
- [ ] Deploy NLB with TCP listeners for ports 993, 143, 587, 465
- [ ] Configure TLS certificates for imap.agentmail.dev and smtp.agentmail.dev
- [ ] Build SMTP relay Docker image: Haraka + AgentMail auth plugin + SES queue plugin + sender rewrite plugin
- [ ] Deploy ECS Fargate service for SMTP relay (2 tasks minimum)
- [ ] Implement credential generation API: `POST /v1/inboxes/{id}/credentials` returns IMAP/SMTP username + password
- [ ] Configure DNS: A/AAAA records for imap.agentmail.dev and smtp.agentmail.dev, SRV records for auto-discovery

**Week 33 (Feb 16-20): Deliverability Features**
- [ ] Implement dedicated IP pool management: assign IP pools per organization or per sending category
- [ ] Integrate SES Virtual Deliverability Manager (VDM): enable VDM for all configuration sets, expose VDM insights via metrics API
- [ ] Implement reputation monitoring: per-org bounce rate and complaint rate tracking, automatic sending throttle at 3% bounce, automatic suspension at 5% bounce
- [ ] Implement suppression list management: auto-add hard bounces and complaints, API to query/manage suppression list
- [ ] Implement `GET /v1/domains/{id}/health` endpoint: return DKIM status, SPF alignment, DMARC policy, MX record status, reputation score
- [ ] Set up IP warming schedule for new dedicated IPs: start at 200/day, double daily until full volume

**Week 34 (Feb 23-27): IMAP/SMTP Polish**
- [ ] Implement IMAP IDLE for real-time notification: subscribe to Redis pub/sub channel for inbox, push new message notifications to IDLE clients
- [ ] Test IMAP migration workflow: use imapsync to migrate 10,000 messages from Gmail to AgentMail inbox
- [ ] Performance testing: IMAP FETCH 1000 messages, SMTP send 100 messages/minute
- [ ] Implement IMAP/SMTP connection metrics and logging
- [ ] Update documentation: IMAP/SMTP setup guide for popular email clients

**Month 8 Deliverables:**
- IMAP server operational behind NLB
- SMTP relay operational behind NLB
- Dedicated IP pool management
- VDM integration
- Reputation monitoring with automatic throttling

### Month 9: Polish (March 2027)

**Week 35 (Mar 2-6): Metrics API + Lists**
- [ ] Implement comprehensive `GET /v1/metrics` endpoint: time-series data for all usage dimensions, filterable by date range and granularity (hourly, daily, monthly)
- [ ] Implement per-inbox metrics: `GET /v1/inboxes/{id}/metrics`
- [ ] Implement per-pod metrics: `GET /v1/pods/{id}/metrics`
- [ ] Implement organization-level allow/block lists that cascade to all inboxes
- [ ] Implement wildcard domain matching for allow/block lists (e.g., `*.company.com`)
- [ ] Implement list import/export (CSV format)

**Week 36 (Mar 9-13): Draft Management + Go SDK**
- [ ] Enhance draft management: auto-save on update (debounced), draft-to-send with confirmation, draft scheduling (convert to scheduled send)
- [ ] Implement scheduled sending: `send_at` parameter on `POST /v1/inboxes/{id}/messages`, EventBridge scheduled rule triggers send at specified time
- [ ] Set up OpenAPI Generator for Go SDK: Go modules, context-based cancellation, structured errors
- [ ] Generate Go SDK, write tests, publish to GitHub
- [ ] Update all SDK documentation

**Week 37 (Mar 16-20): Production Hardening**
- [ ] Comprehensive load testing on staging: 500 req/sec sustained for 1 hour, verify P99 < 500ms
- [ ] Artillery load test scenarios: create inboxes, send messages, search, mixed workload
- [ ] Identify and fix any performance bottlenecks found during load testing
- [ ] Security audit: review IAM policies, S3 bucket policies, API Gateway WAF rules, encryption at rest and in transit
- [ ] Implement rate limiting per endpoint (not just per org): protect expensive operations (search, AI, send)
- [ ] Implement request size limits: 10 MB max request body, 25 MB max attachment

**Week 38 (Mar 23-27): Marketplace Public Listing**
- [ ] Apply for public Marketplace listing (requires AWS Foundational Technical Review / FTR)
- [ ] Complete FTR checklist: security, reliability, operational excellence, performance
- [ ] Update Marketplace listing: screenshots, architecture diagram, pricing table, support links
- [ ] Create Marketplace marketing materials: product brief, ROI calculator, competitive comparison
- [ ] Submit for public listing approval
- [ ] Announce general availability (blog post, social media, Product Hunt)

**Month 9 Deliverables:**
- Complete metrics API
- Allow/block lists with cascading
- Go SDK published
- Production load-tested
- Marketplace public listing submitted

**Phase 3 Exit Criteria:**
- WebSocket real-time events working with <500ms delivery latency
- IMAP/SMTP operational and tested with major email clients
- Load test passing at 500 req/sec sustained
- Marketplace public listing approved (or submitted and pending)
- 5+ paying customers

---

## Phase 4: Scale + Multi-Region (Months 10-12)

**Goal**: Deploy to EU region for data residency, optimize costs, prepare for enterprise sales, and achieve operational maturity.

**Team size**: 5-6 engineers (2 backend, 1 infrastructure, 1 AI/ML, 1 security/compliance, 1 DevEx)

### Month 10: EU Region (April 2027)

**Week 39 (Mar 30 - Apr 3): CDK Multi-Region Preparation**
- [ ] Parameterize all CDK stacks for multi-region deployment: region-specific configuration, account-specific parameters
- [ ] Create `regionConfig` map with per-region settings: SES availability, certificate ARNs, domain names
- [ ] Configure DynamoDB Global Tables: replicate main table from us-east-1 to eu-west-1
- [ ] Configure S3 Cross-Region Replication: raw-email, bodies, and attachments buckets replicated to eu-west-1
- [ ] Set up ElastiCache Global Datastore: replicate Redis from us-east-1 to eu-west-1

**Week 40 (Apr 6-10): EU Deployment**
- [ ] Deploy all CDK stacks to eu-west-1: NetworkStack, DataStack, CacheStack, EmailStack, ApiStack, ComputeStack, EventsStack, AiStack, MarketplaceStack, ObservabilityStack
- [ ] Configure SES in eu-west-1: verify platform domain, configure receipt rules, verify custom domains (re-verify in new region)
- [ ] Deploy IMAP/SMTP services in eu-west-1 (NLB + ECS Fargate)
- [ ] Configure Route 53 latency-based routing: api.agentmail.dev resolves to nearest region
- [ ] Configure Route 53 health checks: automatic failover if one region is unhealthy

**Week 41 (Apr 13-17): Cross-Region Testing**
- [ ] Test EU deployment end-to-end: create inbox, send message, receive, search, AI features
- [ ] Test cross-region replication: create inbox in eu-west-1, verify data appears in us-east-1 DynamoDB
- [ ] Test failover: simulate us-east-1 failure, verify eu-west-1 handles all traffic
- [ ] Measure cross-region latency: EU users should see <200ms P99 for API calls to eu-west-1
- [ ] Test IMAP/SMTP from EU: verify imap-eu.agentmail.dev and smtp-eu.agentmail.dev work

**Week 42 (Apr 20-24): Data Residency + Compliance**
- [ ] Implement data residency enforcement: EU customers' data stays in eu-west-1 (org-level region setting, API rejects requests routed to wrong region)
- [ ] Update privacy policy and terms of service for EU data handling
- [ ] Document GDPR compliance measures: data deletion API, data export API, consent tracking
- [ ] Implement `DELETE /v1/organizations/{id}/data` (GDPR right to erasure): delete all messages, inboxes, metadata for an organization

**Month 10 Deliverables:**
- eu-west-1 fully operational
- Latency-based routing working
- Data residency enforcement for EU customers
- GDPR compliance features

### Month 11: Optimization (May 2027)

**Week 43 (Apr 27 - May 1): Hot Path Migration**
- [ ] Identify top 5 Lambda functions by invocation count and cost
- [ ] Migrate API handler Lambda functions to ECS Fargate: containerize Python handlers, set up ECS service behind ALB, update API Gateway to use HTTP integration
- [ ] Migrate inbound processor to ECS Fargate: long-running container consuming from SQS
- [ ] Benchmark: compare Lambda vs ECS latency and cost for migrated functions
- [ ] Keep Lambda for low-volume functions (marketplace metering, domain verification polling, etc.)

**Week 44 (May 4-8): DynamoDB + Storage Optimization**
- [ ] Analyze DynamoDB traffic patterns from last 3+ months of CloudWatch metrics
- [ ] Switch to provisioned capacity with auto-scaling: set baseline at 70th percentile, auto-scale up to 200% for burst
- [ ] Purchase 1-year DynamoDB reserved capacity for baseline (40% savings)
- [ ] Implement S3 Intelligent-Tiering for email bodies bucket (automatic lifecycle optimization)
- [ ] Implement S3 Glacier Instant Retrieval for attachments older than 90 days
- [ ] Audit and remove any unused DynamoDB GSIs

**Week 45 (May 11-15): Bedrock + Compute Optimization**
- [ ] Implement Bedrock batch inference for categorization: accumulate 5 minutes of messages, submit batch, 50% cost reduction
- [ ] Enable Bedrock prompt caching for categorization and extraction system prompts
- [ ] Implement model routing: route simple emails to Haiku for extraction (instead of Sonnet), use complexity scoring to decide
- [ ] Replace Step Functions Standard with Express Workflows for AI pipeline (98% cost reduction)
- [ ] Purchase Compute Savings Plan (3-year) for Fargate and Lambda workloads
- [ ] Purchase ElastiCache reserved nodes (1-year, all upfront)

**Week 46 (May 18-22): Observability Enhancement**
- [ ] Implement per-tenant CloudWatch dashboards: automated dashboard creation on organization registration
- [ ] Implement customer-facing metrics page: expose subset of CloudWatch metrics through the API
- [ ] Implement cost allocation tags on all AWS resources: org_id, service, environment
- [ ] Set up AWS Cost Explorer alerts: notify if monthly spend exceeds budget by >20%
- [ ] Create operational runbooks for all P0 and P1 alarms

**Month 11 Deliverables:**
- Hot paths migrated to ECS Fargate
- DynamoDB on provisioned capacity with reserved pricing
- Bedrock optimized (batch, caching, routing)
- Step Functions migrated to Express
- Per-tenant dashboards

### Month 12: Enterprise Readiness (June 2027)

**Week 47 (May 25-29): SOC 2 Preparation**
- [ ] Engage SOC 2 Type II auditor (select firm, sign engagement letter)
- [ ] Implement evidence collection: automated screenshots of AWS security configurations, access logs, change management records
- [ ] Document security controls: access management, encryption, incident response, change management, availability
- [ ] Implement automated compliance checks: AWS Config rules for S3 encryption, DynamoDB encryption, Lambda function configuration
- [ ] Enable AWS CloudTrail in all accounts with S3 log aggregation in security account
- [ ] Enable AWS GuardDuty in all accounts with centralized findings in security account
- [ ] Review and document all IAM policies, ensuring least privilege

**Week 48 (Jun 1-5): ISV Accelerate + Enterprise Features**
- [ ] Apply for AWS ISV Accelerate program: submit application with product listing, customer references, architecture review
- [ ] Complete AWS Foundational Technical Review (FTR) if not already done
- [ ] Implement private offers: create custom pricing for enterprise customers via Marketplace Private Offers
- [ ] Implement CPPO (Channel Partner Private Offers) for reseller partnerships
- [ ] Implement enterprise SSO: support SAML 2.0 and OIDC for API key management portal
- [ ] Implement audit logging: every API call and admin action logged to CloudTrail-like audit table

**Week 49 (Jun 8-12): Documentation + Developer Portal**
- [ ] Build developer documentation site: API reference (auto-generated from OpenAPI), guides, tutorials, SDK documentation
- [ ] Write integration guides for popular AI frameworks: LangChain, CrewAI, AutoGPT, Semantic Kernel
- [ ] Write migration guide: migrating from Gmail/Workspace to AgentMail via IMAP
- [ ] Create video walkthroughs: getting started, advanced features, enterprise setup
- [ ] Set up community support channels: Discord, GitHub Discussions

**Week 50 (Jun 15-19): Final Polish**
- [ ] Full production load test: 1,000 req/sec sustained for 4 hours across both regions
- [ ] Disaster recovery test: simulate us-east-1 outage, verify eu-west-1 handles all traffic within 60 seconds
- [ ] Security penetration test (or schedule with third-party firm)
- [ ] Review all alarms and dashboards: ensure coverage for all critical paths
- [ ] Update all documentation to reflect current state
- [ ] Prepare enterprise sales materials: architecture whitepaper, security whitepaper, compliance documentation

**Weeks 51-52 (Jun 22 - Jul 4): Buffer + Celebration**
- [ ] Buffer for any overflows
- [ ] Retrospective: what worked, what did not, lessons learned
- [ ] Plan Phase 5+ roadmap based on customer feedback

**Month 12 Deliverables:**
- SOC 2 Type II audit in progress
- ISV Accelerate application submitted
- Enterprise private offers available
- Developer documentation site live
- Production hardened and load-tested

**Phase 4 Exit Criteria:**
- Multi-region deployment operational (us-east-1 + eu-west-1)
- Costs optimized by 40-50% from unoptimized baseline
- SOC 2 audit in progress
- ISV Accelerate application submitted
- 20+ paying customers
- API uptime >99.9% over trailing 30 days

---

## Risk Register

| # | Risk | Likelihood | Impact | Mitigation | Owner |
|---|------|-----------|--------|------------|-------|
| 1 | **SES sandbox exit delayed** -- AWS takes longer than expected to approve production SES access | Medium | Critical | Submit request in Week 3 (Month 1). Provide detailed use case, expected volume, anti-spam measures. If delayed >2 weeks, escalate via AWS support and use alternative sending (Mailgun) temporarily. | Infrastructure |
| 2 | **SES sending limits insufficient** -- Production limits too low for customer demand | Medium | High | Request limit increases proactively (before hitting limits). Use multi-region SES to distribute across independent quotas. At Growth scale, engage AWS account team for enterprise limits. | Infrastructure |
| 3 | **Bedrock costs exceed projections** -- AI features used more heavily than modeled, or pricing changes | High | High | Implement model routing early (Haiku vs Sonnet). Enable batch inference. Set per-org AI usage quotas. Monitor Bedrock spend daily. Have kill switch to disable AI features if costs spike. | AI/ML |
| 4 | **Marketplace approval delayed** -- AWS takes longer than expected to approve listing (FTR, security review) | Medium | Medium | Submit listing in Month 6 Week 22. Start FTR preparation in Month 5. Use limited visibility listing to onboard initial customers while public listing is pending. | Full-stack |
| 5 | **DynamoDB hot partition** -- Uneven access patterns cause throttling on specific partitions | Medium | High | Design partition keys to distribute evenly (org_id prefix). Monitor per-partition metrics. If hot partition detected, implement write sharding (add random suffix to PK). | Backend |
| 6 | **IMAP compliance gaps** -- Email clients reject our IMAP implementation due to protocol edge cases | Medium | Medium | Test against top 5 clients during development. Use Dovecot imaptest compliance suite. Defer complex extensions (CONDSTORE, QRESYNC) to avoid scope creep. | Backend |
| 7 | **Key engineer departure** -- Loss of engineer with critical knowledge during development | Low | Critical | Document all architecture decisions in project docs. Pair programming for critical components. No single points of failure in team knowledge. Ensure at least 2 people understand each subsystem. | Leadership |
| 8 | **Security breach / data leak** -- Vulnerability in API or infrastructure exposes customer email data | Low | Critical | Security review at end of each phase. Encryption at rest (KMS) and in transit (TLS). Least-privilege IAM. WAF rules. Regular dependency scanning. Penetration testing in Month 12. Incident response plan documented. | Infrastructure |
| 9 | **Competitor launches identical product** -- AgentMail.to or a larger player (SendGrid, Mailgun) launches competing AI-email-for-agents product | Medium | Medium | Move fast -- Phase 1-2 in 6 months gives us a working product. Differentiate on AWS-native integration and Marketplace distribution. Enterprise features and SOC 2 create moat. | Leadership |
| 10 | **Multi-region replication lag causes consistency issues** -- DynamoDB Global Tables replication lag causes stale reads in EU | Low | Medium | Design for eventual consistency: reads in same region as writes are strongly consistent. Cross-region reads may be 1-2 seconds stale. Document this behavior. Implement read-after-write consistency for critical paths by routing to primary region. | Backend |

---

## Dependencies

### External Dependencies

| Dependency | Required By | Lead Time | Status | Contingency |
|-----------|------------|-----------|--------|-------------|
| SES production access (sandbox exit) | Phase 1 Month 1 | 1-3 business days (typical) | Not started | Use SES sandbox for development, request production access early |
| SES sending limit increase (>50K/day) | Phase 1 Month 3 | 1-5 business days | Not started | Multi-region SES as workaround |
| SES sending limit increase (>500K/day) | Phase 2 Month 5 | 1-2 weeks | Not started | Engage AWS account team |
| AWS Marketplace seller registration | Phase 2 Month 6 | 2-4 weeks | Not started | Start in Month 5 |
| Marketplace listing approval (FTR) | Phase 3 Month 9 | 2-6 weeks | Not started | Submit in Month 6, iterate on feedback |
| Marketplace public listing approval | Phase 3 Month 9 | 2-4 weeks | Not started | Use limited visibility until approved |
| Stalwart commercial license (if needed) | Phase 3 Month 8 | 1-2 weeks | Not started | Fall back to WildDuck or Dovecot |
| SOC 2 Type II auditor engagement | Phase 4 Month 12 | 2-4 weeks to engage, 6-12 months for audit | Not started | Begin auditor selection in Month 10 |
| ISV Accelerate program approval | Phase 4 Month 12 | 4-8 weeks | Not started | Not blocking -- enhances distribution |
| Domain registrar (agentmail.dev) | Phase 1 Month 1 | Already owned (assumed) | Done | N/A |

### Internal Dependencies

| Dependency | Required By | Depends On |
|-----------|------------|-----------|
| OpenAPI spec finalized | Month 3 (SDK generation) | All API endpoints designed (Month 2) |
| DynamoDB schema stable | Month 4 (OpenSearch indexing) | All entity types defined (Month 2) |
| Kinesis event bus | Month 7 | Event schema defined (Month 2) |
| Staging environment | Month 2 | CDK stacks deployed (Month 1) |
| Production environment | Month 3 | CI/CD pipeline configured (Month 3) |

---

## Success Metrics

### Technical Metrics

| Metric | Phase 1 Target | Phase 2 Target | Phase 3 Target | Phase 4 Target |
|--------|---------------|---------------|---------------|---------------|
| API uptime | 99% | 99.5% | 99.9% | 99.9% |
| API P50 latency | <200ms | <150ms | <100ms | <100ms |
| API P99 latency | <1000ms | <750ms | <500ms | <500ms |
| Email delivery rate | >95% | >97% | >98% | >99% |
| Inbound processing latency (P99) | <5s | <3s | <2s | <1s |
| Webhook delivery latency (P99) | <10s | <5s | <3s | <2s |
| AI categorization latency (P99) | N/A | <3s | <2s | <2s |
| Semantic search latency (P99) | N/A | <2s | <1s | <500ms |
| WebSocket event delivery (P99) | N/A | N/A | <500ms | <200ms |
| Unit test coverage | 60% | 70% | 80% | 80% |
| Integration test coverage | 40% | 50% | 60% | 70% |

### Business Metrics

| Metric | Phase 1 Target | Phase 2 Target | Phase 3 Target | Phase 4 Target |
|--------|---------------|---------------|---------------|---------------|
| Active organizations | 0 (internal only) | 5 (beta) | 20 | 50 |
| Active inboxes | 1,000 (test) | 10,000 | 50,000 | 200,000 |
| Messages/month | 10,000 (test) | 100,000 | 1,000,000 | 5,000,000 |
| MRR | $0 | $1,000 | $10,000 | $50,000 |
| AWS Marketplace reviews | 0 | 0 | 3+ | 10+ |
| SDK downloads (monthly) | 0 | 100 | 500 | 2,000 |
| Support tickets/week | 0 | 5 | 10 | 15 |

### Operational Metrics

| Metric | Target |
|--------|--------|
| Mean time to detect (MTTD) | <5 minutes (P0 alarms fire within 5 min) |
| Mean time to acknowledge (MTTA) | <15 minutes (on-call responds within 15 min) |
| Mean time to resolve (MTTR) | <1 hour for P0, <4 hours for P1 |
| Deployment frequency | Daily to staging, weekly to production |
| Deployment failure rate | <5% of production deployments require rollback |
| Change lead time | <24 hours from merge to production |
| P0 incidents/month | <1 |
| P1 incidents/month | <5 |
