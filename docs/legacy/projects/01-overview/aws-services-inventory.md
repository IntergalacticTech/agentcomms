# AWS Services Inventory

Complete inventory of every AWS service used in the AgentMail platform, with purpose, configuration, cost estimates, alternatives considered, and documentation links.

## Cost Tier Definitions

| Tier | Inboxes | Messages/Day | API Calls/Day | Monthly AWS Spend |
|------|---------|-------------|---------------|-------------------|
| **Startup** | Up to 100,000 | Up to 500,000 | Up to 2,000,000 | ~$2,000 |
| **Growth** | Up to 1,000,000 | Up to 3,000,000 | Up to 10,000,000 | ~$15,000 |
| **Full Scale** | 10,000,000 | 10,000,000 | 50,000,000 | ~$80,000 |

---

## 1. Amazon Simple Email Service (SES)

### Purpose
Primary email transport layer. Handles all outbound email delivery (SMTP relay, DKIM signing, bounce/complaint processing) and all inbound email receiving (receipt rules, spam filtering, S3 delivery).

### Configuration Details

**Outbound:**
- Region: us-east-1 (primary), us-west-2 (failover)
- Sending mode: Production (sandbox removed during setup)
- DKIM: 2048-bit RSA keys, auto-generated per verified domain
- Configuration sets: One per organization for isolated reputation tracking
- Sending rate: Request increase to 500/sec (startup), 5,000/sec (full scale)
- Dedicated IPs: None initially; add pool of 4-8 at growth tier for reputation control
- Suppression list: Account-level, automatically manages bounced addresses
- Event destinations: SNS topics for bounce, complaint, delivery, open, click

**Inbound:**
- Receipt rule set: Single active rule set with rules per verified domain
- Rule actions chain: S3 (store raw) -> Lambda (process) or S3 -> SNS -> Lambda
- Spam/virus scanning: Enabled (SES built-in)
- TLS: Required for inbound connections (TLS policy: Require)
- IP address filtering: None (accept all, filter at application layer via allow/block lists)

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Outbound sending ($0.10/1K) | $15/mo (150K/mo) | $90/mo (900K/mo) | $300/mo (3M/mo) |
| Inbound receiving ($0.10/1K) | $10/mo (100K/mo) | $60/mo (600K/mo) | $200/mo (2M/mo) |
| Dedicated IPs ($24.95/IP/mo) | $0 | $100/mo (4 IPs) | $200/mo (8 IPs) |
| **SES Total** | **~$25/mo** | **~$250/mo** | **~$700/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **Postfix/SMTP on EC2** | Massive operational overhead; IP reputation management; deliverability challenges; reinventing what SES does natively |
| **SendGrid** | External dependency; higher cost; no inbound receiving; AWS Marketplace billing complications |
| **Mailgun** | External dependency; no inbound processing; separate vendor relationship |

### AWS Documentation
- [SES Developer Guide](https://docs.aws.amazon.com/ses/latest/dg/)
- [SES Inbound Email](https://docs.aws.amazon.com/ses/latest/dg/receiving-email.html)
- [SES Configuration Sets](https://docs.aws.amazon.com/ses/latest/dg/using-configuration-sets.html)
- [SES Pricing](https://aws.amazon.com/ses/pricing/)

---

## 2. Amazon API Gateway

### Purpose
Managed API endpoint for all REST API and WebSocket connections. Handles request routing, authentication, throttling, and protocol management without any server infrastructure.

### Configuration Details

**REST API:**
- Type: Regional REST API (not HTTP API -- need request validation, usage plans, API key management)
- Stages: dev, staging, prod
- Authentication: API key via `x-api-key` header, validated against usage plans
- Usage plans: Per-organization plans with throttle (rate limit + burst) and quota (monthly request limit)
- Default throttle: 1,000 req/sec (burst: 2,000)
- Request validation: JSON Schema validation on all POST/PUT bodies
- Binary media types: `multipart/form-data` (for attachment upload), `application/octet-stream`
- Custom domain: api.agentmail.com via Route 53 alias
- Logging: Access logging to CloudWatch (JSON format with request ID, latency, status)
- Caching: CloudFront layer handles caching; API Gateway caching disabled to avoid double-caching costs

**WebSocket API:**
- Routes: $connect (auth + register), $disconnect (cleanup), subscribe (topic registration), unsubscribe, $default
- Integration: Lambda proxy for all routes
- Connection timeout: 10 minutes idle (maximum), heartbeat every 5 minutes
- Connection ID tracked in Redis for message routing

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| REST API calls ($3.50/M) | $210/mo (60M/mo) | $1,050/mo (300M/mo) | $5,250/mo (1.5B/mo) |
| WebSocket messages ($1.00/M) | $10/mo (10M/mo) | $100/mo (100M/mo) | $500/mo (500M/mo) |
| WebSocket connection-min ($0.25/M) | $5/mo | $50/mo | $250/mo |
| **API Gateway Total** | **~$225/mo** | **~$1,200/mo** | **~$6,000/mo** |

**Note:** At full scale, consider migrating to HTTP API ($1.00/M) if usage plan features can be replicated at the application layer. This would reduce REST API costs by ~70%.

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **ALB + ECS** | Requires managing compute; no built-in API key management; no usage plans; higher fixed cost |
| **API Gateway HTTP API** | Cheaper per-request but lacks usage plans, API key validation, and request validation features needed for multi-tenant SaaS |
| **Kong/Apigee** | External dependency; additional vendor; higher complexity; no native AWS integration |
| **AppSync** | GraphQL-oriented; REST API is the standard for email platforms; unnecessary complexity |

### AWS Documentation
- [REST API Developer Guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-rest-api.html)
- [WebSocket API](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api.html)
- [Usage Plans](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-api-usage-plans.html)
- [API Gateway Pricing](https://aws.amazon.com/api-gateway/pricing/)

---

## 3. AWS Lambda

### Purpose
All request-response compute and event-driven processing. Every API handler, email processor, AI orchestrator, webhook dispatcher, and metering reporter runs as a Lambda function.

### Configuration Details

**Runtime:** Node.js 20.x (primary), Python 3.12 (for AI/ML functions if needed)

**Function inventory:**

| Function | Memory | Timeout | Concurrency | Trigger |
|----------|--------|---------|-------------|---------|
| `api-inboxes` | 512MB | 30s | 500 | API Gateway |
| `api-messages` | 512MB | 30s | 500 | API Gateway |
| `api-threads` | 256MB | 30s | 200 | API Gateway |
| `api-drafts` | 256MB | 30s | 100 | API Gateway |
| `api-domains` | 256MB | 30s | 50 | API Gateway |
| `api-pods` | 256MB | 30s | 100 | API Gateway |
| `api-webhooks` | 256MB | 30s | 50 | API Gateway |
| `api-search` | 512MB | 30s | 200 | API Gateway |
| `api-keys` | 256MB | 30s | 50 | API Gateway |
| `api-metrics` | 256MB | 30s | 100 | API Gateway |
| `api-lists` | 256MB | 30s | 50 | API Gateway |
| `api-orgs` | 256MB | 30s | 50 | API Gateway |
| `api-attachments` | 512MB | 30s | 100 | API Gateway |
| `api-categorization` | 256MB | 30s | 50 | API Gateway |
| `api-extraction` | 256MB | 30s | 50 | API Gateway |
| `ws-connect` | 256MB | 10s | 200 | WebSocket API |
| `ws-disconnect` | 256MB | 10s | 200 | WebSocket API |
| `ws-message` | 256MB | 10s | 200 | WebSocket API |
| `inbound-processor` | 1024MB | 60s | 500 | Kinesis (inbound-email) |
| `outbound-sender` | 512MB | 30s | 500 | Direct invoke |
| `webhook-dispatcher` | 256MB | 30s | 200 | Kinesis (outbound-events) |
| `websocket-pusher` | 256MB | 10s | 200 | Kinesis (outbound-events) |
| `ai-categorizer` | 512MB | 60s | 200 | Kinesis (ai-processing) |
| `ai-extractor` | 512MB | 60s | 200 | Kinesis (ai-processing) |
| `embedding-generator` | 512MB | 30s | 200 | Kinesis (ai-processing) |
| `bounce-processor` | 256MB | 30s | 50 | SNS (bounce/complaint) |
| `metering-reporter` | 256MB | 30s | 10 | Step Functions |
| `domain-verifier` | 256MB | 60s | 10 | EventBridge (5 min) |
| `metric-aggregator` | 512MB | 300s | 5 | EventBridge (hourly) |
| `draft-cleanup` | 256MB | 300s | 2 | EventBridge (daily) |
| `marketplace-subscription` | 256MB | 30s | 5 | SNS (Marketplace) |

**Provisioned concurrency:** Enabled for `api-inboxes`, `api-messages`, `inbound-processor` at growth tier to eliminate cold starts.

**Layers:**
- `shared-utils`: Common code (auth, validation, DynamoDB client, error handling)
- `email-parser`: MIME parsing library (mailparser)
- `clamav`: Virus scanning binary (for attachment scanning)

**VPC:** Lambda functions that access ElastiCache or OpenSearch run in VPC with private subnets and NAT Gateway for internet access (SES, Marketplace APIs).

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Invocations ($0.20/M) | $12/mo (60M/mo) | $60/mo (300M/mo) | $300/mo (1.5B/mo) |
| Duration (GB-sec, $0.0000166667) | $100/mo | $600/mo | $3,000/mo |
| Provisioned concurrency | $0 | $200/mo | $800/mo |
| NAT Gateway ($0.045/hr + data) | $35/mo | $100/mo | $300/mo |
| **Lambda Total** | **~$150/mo** | **~$960/mo** | **~$4,400/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **ECS Fargate (for all compute)** | Higher baseline cost; no scale-to-zero; doesn't match bursty API workload pattern |
| **EC2 Auto Scaling** | Operational overhead; slower scaling; fixed minimum cost; over-provisioning waste |
| **App Runner** | Less control over scaling; no Kinesis event source mapping; limited VPC support |

### AWS Documentation
- [Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/)
- [Lambda with Kinesis](https://docs.aws.amazon.com/lambda/latest/dg/with-kinesis.html)
- [Lambda Pricing](https://aws.amazon.com/lambda/pricing/)
- [Lambda in VPC](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html)

---

## 4. Amazon DynamoDB

### Purpose
Primary database for all metadata: organizations, pods, inboxes, messages, threads, drafts, domains, API keys, webhooks, lists, and metrics. Single-table design optimized for the platform's access patterns.

### Configuration Details

**Table:** `agentmail-main`
- Billing mode: On-demand (pay-per-request)
- Partition key: `PK` (String)
- Sort key: `SK` (String)
- Encryption: AWS-managed key (aws/dynamodb)
- Point-in-time recovery: Enabled
- TTL attribute: `expiresAt` (for drafts, temporary tokens, cached entitlements)
- Stream: Enabled (NEW_AND_OLD_IMAGES) for change data capture

**Global Secondary Indexes:**

| GSI | PK | SK | Purpose | Projection |
|-----|----|----|---------|-----------|
| GSI1 | `GSI1PK` | `GSI1SK` | List inboxes by pod, messages by inbox (time-sorted) | ALL |
| GSI2 | `GSI2PK` | `GSI2SK` | List messages by thread (time-sorted) | ALL |
| GSI3 | `GSI3PK` | `GSI3SK` | Lookup inbox by email address (for inbound routing) | KEYS_ONLY |
| GSI4 | `GSI4PK` | `GSI4SK` | Lookup organization by API key hash | KEYS_ONLY |
| GSI5 | `GSI5PK` | `GSI5SK` | List domains by verification status (for polling) | ALL |

**Item types and access patterns:**

| Item Type | PK | SK | Size Est. |
|-----------|----|----|-----------|
| Organization | `ORG#{orgId}` | `ORG#{orgId}` | 500B |
| Pod | `ORG#{orgId}` | `POD#{podId}` | 300B |
| Inbox | `INB#{inboxId}` | `INB#{inboxId}` | 500B |
| Inbox-in-Pod | `POD#{podId}` | `INB#{inboxId}` | 200B (sparse) |
| Message | `INB#{inboxId}` | `MSG#{timestamp}#{msgId}` | 1-2KB |
| Thread | `INB#{inboxId}` | `THR#{threadId}` | 500B |
| Message-in-Thread | `THR#{threadId}` | `MSG#{timestamp}#{msgId}` | 200B (sparse) |
| Draft | `INB#{inboxId}` | `DRF#{draftId}` | 1KB |
| Domain | `ORG#{orgId}` | `DOM#{domainId}` | 500B |
| API Key | `KEY#{keyHash}` | `KEY#{keyHash}` | 300B |
| Webhook | `ORG#{orgId}` | `WHK#{webhookId}` | 400B |
| Allow/Block List | `INB#{inboxId}` | `LST#{type}` | 1-5KB |
| Metric Record | `MET#{orgId}#{dimension}` | `#{period}#{timestamp}` | 200B |

**Capacity estimates:**

| Tier | Read Units/sec | Write Units/sec | Storage |
|------|---------------|-----------------|---------|
| Startup | ~500 | ~200 | 50GB |
| Growth | ~5,000 | ~2,000 | 500GB |
| Full Scale | ~50,000 | ~20,000 | 5TB |

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Read request units ($0.25/M) | $10/mo | $100/mo | $1,000/mo |
| Write request units ($1.25/M) | $8/mo | $75/mo | $750/mo |
| Storage ($0.25/GB/mo) | $13/mo | $125/mo | $1,250/mo |
| PITR backup ($0.20/GB/mo) | $10/mo | $100/mo | $1,000/mo |
| DynamoDB Streams | $2/mo | $20/mo | $200/mo |
| On-demand backup (weekly) | $5/mo | $50/mo | $500/mo |
| **DynamoDB Total** | **~$50/mo** | **~$470/mo** | **~$4,700/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **Amazon Aurora (PostgreSQL)** | Fixed cost (minimum ~$60/mo); scaling requires instance changes; connection pooling complexity with Lambda; doesn't align with consumption-based model |
| **Amazon Aurora Serverless v2** | Better scaling but still minimum ~$45/mo; SQL overhead for simple key-value patterns; connection limits with high Lambda concurrency |
| **MongoDB Atlas** | External dependency; separate billing; no AWS Marketplace integration; operational overhead |
| **Amazon Keyspaces (Cassandra)** | Similar to DynamoDB but less mature serverless story; fewer integrations; less community knowledge |

### AWS Documentation
- [DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/)
- [Single-Table Design](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-general-nosql-design.html)
- [On-Demand Pricing](https://aws.amazon.com/dynamodb/pricing/on-demand/)
- [DynamoDB Streams](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html)

---

## 5. Amazon S3

### Purpose
Storage for all large and binary data: raw email bodies (MIME), attachments, SES inbound email deposits, DynamoDB backups, and application logs.

### Configuration Details

**Buckets:**

| Bucket | Region | Versioning | Encryption | Public |
|--------|--------|-----------|------------|--------|
| `agentmail-email-bodies` | us-east-1 | Disabled | SSE-S3 | No |
| `agentmail-attachments` | us-east-1 | Disabled | SSE-S3 | No |
| `agentmail-ses-inbound` | us-east-1 | Disabled | SSE-S3 | No |
| `agentmail-backups` | us-east-1 | Enabled | SSE-KMS | No |
| `agentmail-logs` | us-east-1 | Disabled | SSE-S3 | No |

**Lifecycle policies:**

| Bucket | Rule | Transition/Expiration |
|--------|------|----------------------|
| `agentmail-email-bodies` | Standard -> IA | 90 days |
| `agentmail-email-bodies` | IA -> Glacier IR | 365 days |
| `agentmail-email-bodies` | Glacier IR -> expire | 2,555 days (7 years) |
| `agentmail-attachments` | Standard -> IA | 90 days |
| `agentmail-attachments` | IA -> Glacier IR | 365 days |
| `agentmail-ses-inbound` | Expire | 7 days (processed and deleted) |
| `agentmail-backups` | Standard -> Glacier | 30 days |
| `agentmail-backups` | Glacier -> Deep Archive | 365 days |
| `agentmail-logs` | Expire | 90 days |

**Object key structure:**
- Email bodies: `{orgId}/{inboxId}/{messageId}/body.mime`
- Attachments: `{orgId}/{inboxId}/{messageId}/attachments/{attachmentId}/{filename}`
- SES inbound: `{ruleset}/{ruleId}/{messageId}` (SES default)

**Access:**
- Presigned URLs for attachment upload (PUT, 1-hour expiry) and download (GET, 1-hour expiry)
- Bucket policies restrict access to Lambda execution roles only
- No public access (block all public access enabled)
- CORS configured for presigned URL uploads from client browsers

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| S3 Standard storage ($0.023/GB) | $12/mo (500GB) | $115/mo (5TB) | $1,150/mo (50TB) |
| S3 IA storage ($0.0125/GB) | $0 (not yet) | $25/mo (2TB archived) | $250/mo (20TB) |
| PUT requests ($0.005/1K) | $2/mo | $15/mo | $75/mo |
| GET requests ($0.0004/1K) | $2/mo | $12/mo | $60/mo |
| Data transfer (to Lambda, free in-region) | $0 | $0 | $0 |
| **S3 Total** | **~$16/mo** | **~$167/mo** | **~$1,535/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **EFS** | Unnecessary filesystem abstraction; higher cost per GB; designed for shared compute, not object storage |
| **DynamoDB (large items)** | 400KB item limit; much higher cost per GB for storage; not designed for binary data |
| **External object storage (Cloudflare R2)** | External dependency; egress savings not relevant (internal traffic); adds operational complexity |

### AWS Documentation
- [S3 User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/)
- [Presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html)
- [Lifecycle Policies](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- [S3 Pricing](https://aws.amazon.com/s3/pricing/)

---

## 6. Amazon ElastiCache (Redis)

### Purpose
In-memory data store for API response caching, rate limiting, WebSocket connection state management, pub/sub for real-time event fan-out, and idempotency key tracking.

### Configuration Details

**Startup tier:**
- Engine: Redis 7.x
- Node type: cache.r7g.large (2 vCPU, 13.07 GB)
- Configuration: Single node (no replication)
- Cluster mode: Disabled
- Subnet group: Private subnets (2 AZs)
- Security group: Allow inbound 6379 from Lambda security group only
- Auth: AUTH token via Secrets Manager
- Encryption: In-transit (TLS) and at-rest enabled
- Parameter group: Custom (maxmemory-policy: allkeys-lru)

**Growth tier:**
- Node type: cache.r7g.xlarge (4 vCPU, 26.32 GB)
- Replication: 1 replica (Multi-AZ)
- Automatic failover: Enabled

**Full scale tier:**
- Cluster mode: Enabled
- Shards: 4 (each with 1 replica)
- Node type: cache.r7g.xlarge per shard
- Total memory: ~105 GB

**Key namespace design:**

| Key Pattern | TTL | Purpose |
|-------------|-----|---------|
| `cache:org:{orgId}` | 300s | Organization config cache |
| `cache:inbox:{inboxId}` | 60s | Inbox metadata cache |
| `cache:entitlement:{orgId}` | 300s | Marketplace entitlement cache |
| `rl:{orgId}:{endpoint}:{window}` | Dynamic | Rate limit counters (sliding window) |
| `ws:conn:{connectionId}` | 600s | WebSocket connection -> subscription mapping |
| `ws:inbox:{inboxId}` | None | Set of connection IDs subscribed to inbox |
| `ws:pod:{podId}` | None | Set of connection IDs subscribed to pod |
| `idempotency:{requestId}` | 3600s | Request deduplication |

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| On-demand node hours | $130/mo (r7g.large) | $520/mo (r7g.xlarge x2) | $2,080/mo (r7g.xlarge x8) |
| Backup storage | $5/mo | $15/mo | $50/mo |
| Data transfer (cross-AZ) | $2/mo | $10/mo | $50/mo |
| **ElastiCache Total** | **~$137/mo** | **~$545/mo** | **~$2,180/mo** |

**Note:** Consider ElastiCache Serverless at startup tier for simpler management and pay-per-use, though per-GB-hour pricing may be more expensive for sustained workloads.

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **DynamoDB DAX** | Only caches DynamoDB reads; cannot do rate limiting, pub/sub, or WebSocket state |
| **MemoryDB for Redis** | More durable but 2x cost; durability not needed for cache data |
| **ElastiCache Serverless** | Good alternative for startup; evaluate when available in target region; may be cost-competitive |
| **Application-level caching (Lambda /tmp)** | Not shared across invocations; no pub/sub; no rate limiting |

### AWS Documentation
- [ElastiCache for Redis Guide](https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/)
- [ElastiCache Best Practices](https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/BestPractices.html)
- [ElastiCache Pricing](https://aws.amazon.com/elasticache/pricing/)

---

## 7. Amazon Kinesis Data Streams

### Purpose
Ordered event streaming backbone. Decouples producers (API handlers, inbound email processor) from consumers (webhook dispatcher, WebSocket pusher, AI processor, metering). Provides replay capability for failed processing.

### Configuration Details

**Streams:**

| Stream | Shards (Startup) | Shards (Growth) | Shards (Full) | Retention | Consumers |
|--------|------------------|-----------------|---------------|-----------|-----------|
| `inbound-email` | 2 | 8 | 32 | 7 days | inbound-processor, ai-processor |
| `outbound-events` | 2 | 4 | 16 | 24 hours | webhook-dispatcher, websocket-pusher |
| `ai-processing` | 2 | 8 | 32 | 24 hours | ai-categorizer, ai-extractor, embedding-generator |

**Configuration per stream:**
- Mode: Provisioned (for predictable costs and performance)
- Enhanced fan-out: Enabled for streams with multiple consumers (dedicated 2MB/sec per consumer)
- Encryption: AWS-managed KMS key
- Metrics: Enhanced shard-level metrics enabled

**Lambda event source mappings:**
- Batch size: 100 records (inbound-email), 50 records (ai-processing), 200 records (outbound-events)
- Batch window: 5 seconds
- Parallelization factor: 10 (process 10 batches per shard concurrently)
- Starting position: TRIM_HORIZON (on deployment), LATEST (normal operation)
- Bisect on function error: Enabled
- Max retry attempts: 3 (then send to SQS DLQ)
- Destination on failure: SQS dead-letter queue

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Shard hours ($0.015/hr) | $65/mo (6 shards) | $216/mo (20 shards) | $864/mo (80 shards) |
| PUT payload units ($0.014/M) | $5/mo | $30/mo | $150/mo |
| Enhanced fan-out ($0.013/consumer-shard-hr) | $20/mo | $85/mo | $340/mo |
| Extended retention (+$0.014/shard-hr for >24h) | $10/mo | $30/mo | $120/mo |
| **Kinesis Total** | **~$100/mo** | **~$361/mo** | **~$1,474/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **Amazon SQS** | No ordering guarantees (standard queues); FIFO queues limited to 3K msg/sec; no replay; no fan-out |
| **Amazon MSK (Kafka)** | Minimum cost ~$150/mo for smallest cluster; operational overhead; overkill for initial scale |
| **Amazon EventBridge Pipes** | Limited throughput; harder to fan-out to multiple consumers; newer service with less battle-testing |
| **DynamoDB Streams** | Good for CDC but not general event streaming; limited to DynamoDB changes only |

### AWS Documentation
- [Kinesis Data Streams Guide](https://docs.aws.amazon.com/streams/latest/dev/)
- [Lambda with Kinesis](https://docs.aws.amazon.com/lambda/latest/dg/with-kinesis.html)
- [Enhanced Fan-Out](https://docs.aws.amazon.com/streams/latest/dev/enhanced-consumers.html)
- [Kinesis Pricing](https://aws.amazon.com/kinesis/data-streams/pricing/)

---

## 8. Amazon EventBridge

### Purpose
Scheduled task execution and cross-service event orchestration. Handles periodic jobs (domain verification, metric aggregation, cleanup) and internal system events (organization created, subscription changed).

### Configuration Details

**Scheduled rules:**

| Rule | Schedule | Target | Purpose |
|------|----------|--------|---------|
| `domain-verification-check` | rate(5 minutes) | Lambda: domain-verifier | Poll DNS for pending domain verifications |
| `metric-aggregation` | rate(1 hour) | Lambda: metric-aggregator | Roll up per-minute metrics into hourly/daily |
| `draft-cleanup` | rate(1 day) | Lambda: draft-cleanup | Delete drafts older than 30 days |
| `stale-connection-cleanup` | rate(15 minutes) | Lambda: ws-cleanup | Remove stale WebSocket connection records |
| `marketplace-metering` | rate(1 hour) | Step Functions: metering-workflow | Trigger hourly metering report |

**Custom event bus:** `agentmail-events`
- Events: `organization.created`, `organization.deleted`, `subscription.activated`, `subscription.cancelled`, `quota.warning`, `quota.exceeded`
- Rules route events to appropriate Lambda handlers

**Archive:** Enabled for audit trail, 90-day retention

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Custom events ($1.00/M) | $1/mo | $5/mo | $20/mo |
| Scheduled invocations | Free (< 14M/mo) | Free | Free |
| Archive storage | $1/mo | $5/mo | $20/mo |
| **EventBridge Total** | **~$2/mo** | **~$10/mo** | **~$40/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **CloudWatch Events** | EventBridge is the successor; same pricing; better features (custom buses, schema registry) |
| **Cron on EC2** | Requires managing an EC2 instance; single point of failure; no built-in retry |
| **Step Functions scheduled** | More expensive for simple scheduled invocations; better for complex workflows (used separately) |

### AWS Documentation
- [EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/)
- [Scheduled Rules](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-create-rule-schedule.html)
- [EventBridge Pricing](https://aws.amazon.com/eventbridge/pricing/)

---

## 9. Amazon OpenSearch Serverless

### Purpose
Powers both semantic (vector) search and full-text keyword search across email messages. Stores embeddings generated by Bedrock Titan and indexes email subjects/bodies for keyword search.

### Configuration Details

**Collections:**

| Collection | Type | Purpose | Index Settings |
|------------|------|---------|---------------|
| `agentmail-vectors` | Vector Search | Semantic search using embeddings | Engine: FAISS, Dimensions: 1024, Distance: Cosine |
| `agentmail-fulltext` | Search | Keyword search on email text | Analyzer: Standard, Fields: subject, body, from, to |

**Index mappings (vector collection):**
```json
{
  "mappings": {
    "properties": {
      "embedding": {"type": "knn_vector", "dimension": 1024, "method": {"name": "hnsw", "engine": "faiss"}},
      "orgId": {"type": "keyword"},
      "inboxId": {"type": "keyword"},
      "messageId": {"type": "keyword"},
      "subject": {"type": "text"},
      "timestamp": {"type": "date"}
    }
  }
}
```

**Access policies:**
- Data access policy: Scoped by org ID (each search query filters by orgId for tenant isolation)
- Network policy: VPC endpoint only (no public access)
- Encryption policy: AWS-managed key

**Capacity:**
- OpenSearch Serverless uses OpenSearch Compute Units (OCUs)
- Minimum: 2 OCUs for indexing + 2 OCUs for search (per collection) -- this is the minimum and a significant baseline cost
- Auto-scales based on workload

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Indexing OCUs ($0.24/OCU-hr, min 2) | $350/mo | $350/mo | $700/mo (4 OCUs) |
| Search OCUs ($0.24/OCU-hr, min 2) | $350/mo | $350/mo | $700/mo (4 OCUs) |
| Storage ($0.024/GB/mo) | $5/mo | $50/mo | $500/mo |
| **OpenSearch Serverless Total** | **~$705/mo** | **~$750/mo** | **~$1,900/mo** |

**Important note:** OpenSearch Serverless has a significant minimum cost (~$700/mo) due to the 2-OCU minimum per collection. At startup tier, this is the single largest line item. Options to mitigate:
1. Start with a single collection for both vector and full-text (reduces to ~$350/mo)
2. Defer semantic search to growth tier and use DynamoDB-based keyword search initially
3. Use a provisioned OpenSearch domain (cheaper at low scale, but requires management)

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **OpenSearch (provisioned domain)** | Lower minimum cost (~$50/mo for t3.small) but requires instance management, capacity planning, and version upgrades |
| **Pinecone** | External dependency; no AWS Marketplace billing integration; separate vendor |
| **pgvector (Aurora)** | Would require Aurora; additional database to manage; less mature vector search |
| **Kendra** | Designed for enterprise document search; too expensive ($810/mo minimum); wrong use case |
| **DynamoDB + application-level search** | No semantic search capability; full-text search requires scan operations; poor performance at scale |

### AWS Documentation
- [OpenSearch Serverless Guide](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)
- [Vector Search](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html)
- [OpenSearch Serverless Pricing](https://aws.amazon.com/opensearch-service/pricing/)

---

## 10. Amazon Bedrock

### Purpose
Managed LLM access for AI-powered email features: categorization (classifying emails), structured data extraction (pulling structured JSON from email content), and embedding generation (for semantic search).

### Configuration Details

**Models in use:**

| Model | Model ID | Use Case | Max Input | Max Output |
|-------|----------|----------|-----------|------------|
| Claude 3.5 Haiku | `anthropic.claude-3-5-haiku-20241022-v1:0` | Email categorization | 200K tokens | 4K tokens |
| Claude 3.5 Sonnet | `anthropic.claude-3-5-sonnet-20241022-v2:0` | Structured data extraction | 200K tokens | 4K tokens |
| Titan Embeddings v2 | `amazon.titan-embed-text-v2:0` | Email embedding generation | 8K tokens | 1024-dim vector |

**Invocation patterns:**

- **Categorization**: System prompt with category definitions + email subject and first 2,000 characters of body. Response: JSON with category name and confidence score. Average ~300 input tokens, ~50 output tokens.
- **Extraction**: System prompt with extraction schema (JSON Schema format) + relevant email sections. Response: JSON matching the defined schema. Average ~500 input tokens, ~200 output tokens.
- **Embedding**: Full email text (subject + body), truncated to 8K tokens. Response: 1024-dimension float vector.

**Throughput:**
- Default: Varies by model and region
- Provisioned throughput: Consider at growth tier for Haiku (most frequently called)
- Cross-region inference: Enabled to handle burst traffic

**Error handling:**
- Retry with exponential backoff (3 attempts)
- Circuit breaker: If error rate > 10% over 5 minutes, stop sending AI requests and queue for later
- Graceful degradation: AI features are non-blocking; email delivery continues without AI processing if Bedrock is unavailable

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Haiku input ($0.00025/1K tokens) | $2/mo | $15/mo | $75/mo |
| Haiku output ($0.00125/1K tokens) | $2/mo | $10/mo | $50/mo |
| Sonnet input ($0.003/1K tokens) | $5/mo | $30/mo | $150/mo |
| Sonnet output ($0.015/1K tokens) | $10/mo | $60/mo | $300/mo |
| Titan Embeddings ($0.0001/1K tokens) | $1/mo | $5/mo | $25/mo |
| **Bedrock Total** | **~$20/mo** | **~$120/mo** | **~$600/mo** |

**Note:** These estimates assume AI features are used for ~30% of incoming messages. Actual costs scale linearly with customer adoption of AI features.

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **Self-hosted models (SageMaker)** | Massive operational overhead; fixed endpoint costs; Bedrock is pay-per-token |
| **OpenAI API** | External dependency; data leaves AWS; no Marketplace billing integration; vendor lock-in |
| **Google Vertex AI** | External dependency; multi-cloud complexity; no AWS integration |
| **Open-source models on ECS** | High GPU cost; operational overhead; worse quality than Claude/Titan |

### AWS Documentation
- [Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/)
- [Bedrock Runtime API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_Operations_Amazon_Bedrock_Runtime.html)
- [Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/)

---

## 11. Amazon Route 53

### Purpose
DNS management for the platform's own domains and for customer custom domains. Handles MX record creation for inbound email routing, DKIM CNAME records, SPF TXT records, and domain verification.

### Configuration Details

**Platform hosted zones:**
- `agentmail.com` -- Platform domain (MX, A, CNAME records)
- `api.agentmail.com` -- API subdomain (ALIAS to CloudFront)
- `*.mail.agentmail.com` -- Wildcard for default inbox domains

**Customer domain flow:**
1. Customer calls `POST /domains` with their domain name
2. Lambda creates SES domain identity (generates DKIM tokens)
3. Lambda returns DNS records customer needs to add:
   - 3x DKIM CNAME records
   - 1x MX record (pointing to SES inbound)
   - 1x SPF TXT record
   - 1x verification TXT record
4. EventBridge triggers domain-verifier Lambda every 5 minutes
5. Lambda checks DNS propagation via Route 53 `TestDNSAnswer` API (or direct DNS query)
6. Once verified, domain status updated in DynamoDB

**For customers using Route 53 (optional):**
- Create hosted zone via API
- Programmatically add all required records
- Full automation, zero customer effort

**Health checks:**
- IMAP endpoint (imap.agentmail.com:993) -- TCP health check
- SMTP endpoint (smtp.agentmail.com:465) -- TCP health check
- API endpoint (api.agentmail.com/health) -- HTTPS health check

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Hosted zones ($0.50/zone/mo) | $5/mo (10 zones) | $50/mo (100 zones) | $500/mo (1K zones) |
| DNS queries ($0.40/M) | $2/mo | $10/mo | $50/mo |
| Health checks ($0.50/check/mo) | $2/mo | $2/mo | $2/mo |
| **Route 53 Total** | **~$9/mo** | **~$62/mo** | **~$552/mo** |

**Note:** Most customers will manage their own DNS and just add CNAME/MX/TXT records. Route 53 hosted zone creation is optional.

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **Cloudflare DNS** | External dependency; not AWS-native; would complicate domain verification flow |
| **Customer-managed DNS only** | Would work but removes ability to automate; worse UX for customers who want full automation |

### AWS Documentation
- [Route 53 Developer Guide](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/)
- [Route 53 Pricing](https://aws.amazon.com/route53/pricing/)

---

## 12. Amazon CloudWatch

### Purpose
Centralized monitoring, logging, metrics collection, alarming, and dashboarding. All Lambda functions, API Gateway, and infrastructure services emit metrics and logs to CloudWatch.

### Configuration Details

**Custom metrics namespace:** `AgentMail`

| Metric | Dimensions | Statistic | Unit |
|--------|-----------|-----------|------|
| `MessagesReceived` | OrgId, InboxId | Sum | Count |
| `MessagesSent` | OrgId, InboxId | Sum | Count |
| `InboxesCreated` | OrgId | Sum | Count |
| `ActiveInboxes` | OrgId | Maximum | Count |
| `ApiLatency` | Endpoint | p50, p99, Average | Milliseconds |
| `ApiErrors` | Endpoint, ErrorType | Sum | Count |
| `BounceRate` | OrgId | Average | Percent |
| `ComplaintRate` | OrgId | Average | Percent |
| `AiCategorizationLatency` | Model | p50, p99 | Milliseconds |
| `WebhookDeliverySuccess` | OrgId | Average | Percent |
| `WebSocketConnections` | - | Maximum | Count |
| `KinesisIteratorAge` | StreamName | Maximum | Milliseconds |

**Alarms:**

| Alarm | Condition | Action |
|-------|-----------|--------|
| API p99 > 500ms | 3 consecutive 5-min periods | SNS -> PagerDuty |
| API error rate > 1% | 2 consecutive 5-min periods | SNS -> PagerDuty |
| Kinesis iterator age > 60s | 1 period | SNS -> PagerDuty |
| Lambda errors > 100/min | 1 period | SNS -> Slack |
| DynamoDB throttle > 0 | 1 period | SNS -> Slack |
| SES bounce rate > 5% | 1 period | SNS -> PagerDuty |
| SES complaint rate > 0.1% | 1 period | SNS -> PagerDuty |

**Log groups:**
- `/aws/lambda/{function-name}` -- One per Lambda function
- `/aws/apigateway/agentmail-rest` -- API Gateway access logs
- `/aws/ecs/agentmail-imap` -- IMAP server logs
- `/aws/ecs/agentmail-smtp` -- SMTP server logs
- `/agentmail/application` -- Custom application logs

**Log retention:** 30 days (dev), 90 days (staging), 365 days (prod)

**Dashboards:**
- Operations dashboard: API latency, error rates, Kinesis lag, Lambda concurrency
- Business dashboard: Messages sent/received, inbox count, AI feature usage, webhook success rate
- Per-customer dashboard: Filterable by org ID

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Custom metrics ($0.30/metric/mo) | $10/mo | $100/mo | $500/mo |
| Log ingestion ($0.50/GB) | $25/mo (50GB) | $150/mo (300GB) | $500/mo (1TB) |
| Log storage ($0.03/GB/mo) | $5/mo | $30/mo | $200/mo |
| Alarms ($0.10/alarm/mo) | $3/mo | $10/mo | $30/mo |
| Dashboards ($3/dashboard/mo) | $9/mo | $12/mo | $15/mo |
| Log Insights queries ($0.005/GB scanned) | $5/mo | $20/mo | $50/mo |
| **CloudWatch Total** | **~$57/mo** | **~$322/mo** | **~$1,295/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **Datadog** | Excellent product but $15-23/host/mo + $0.10/GB logs; external dependency; separate billing |
| **Grafana Cloud** | Good for dashboards but requires separate metric storage; added complexity |
| **ELK Stack (self-managed)** | Massive operational overhead; not serverless; high baseline cost |

### AWS Documentation
- [CloudWatch User Guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/)
- [CloudWatch Metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/working_with_metrics.html)
- [CloudWatch Pricing](https://aws.amazon.com/cloudwatch/pricing/)

---

## 13. AWS X-Ray

### Purpose
Distributed tracing across all Lambda functions and service calls. Enables end-to-end request tracking from API Gateway through Lambda to DynamoDB/S3/SES, identifying latency bottlenecks and error sources.

### Configuration Details

- **Active tracing**: Enabled on all Lambda functions and API Gateway
- **Sampling rules**:
  - Default: 5% of requests sampled
  - Error rule: 100% of requests with errors sampled
  - Slow rule: 100% of requests > 1 second sampled
  - High-priority endpoint rule: 10% for `/inboxes`, `/messages` endpoints
- **Annotations** (indexed, searchable):
  - `orgId`: Organization identifier
  - `podId`: Pod identifier
  - `inboxId`: Inbox identifier
  - `operation`: API operation name
- **Metadata** (non-indexed):
  - Request/response sizes
  - DynamoDB consumed capacity
  - SES message ID
- **Groups**:
  - `errors`: Filter expression `fault = true OR error = true`
  - `slow-requests`: Filter expression `responsetime > 1`
  - `per-org`: Filter expression `annotation.orgId = "specific-org-id"`

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Traces recorded ($5/M) | $15/mo (3M traces) | $75/mo (15M) | $125/mo (25M, sampling reduces volume) |
| Traces retrieved ($0.50/M) | $2/mo | $5/mo | $10/mo |
| **X-Ray Total** | **~$17/mo** | **~$80/mo** | **~$135/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **OpenTelemetry + Jaeger** | Requires self-hosting Jaeger; X-Ray has native Lambda/API Gateway integration |
| **Datadog APM** | External dependency; separate billing; X-Ray sufficient for AWS-native architecture |

### AWS Documentation
- [X-Ray Developer Guide](https://docs.aws.amazon.com/xray/latest/devguide/)
- [X-Ray with Lambda](https://docs.aws.amazon.com/lambda/latest/dg/services-xray.html)
- [X-Ray Pricing](https://aws.amazon.com/xray/pricing/)

---

## 14. AWS WAF (Web Application Firewall)

### Purpose
Protect API Gateway endpoints from abuse, DDoS, and common web exploits. Provides an additional rate limiting layer beyond API Gateway usage plans.

### Configuration Details

**Web ACL:** `agentmail-api-waf`
- Associated with: API Gateway REST API, CloudFront distribution

**Rules (in priority order):**

| Priority | Rule | Action | Purpose |
|----------|------|--------|---------|
| 1 | AWS-AWSManagedRulesAmazonIpReputationList | Block | Block known bad IPs |
| 2 | AWS-AWSManagedRulesCommonRuleSet | Block | OWASP Top 10 protection |
| 3 | AWS-AWSManagedRulesKnownBadInputsRuleSet | Block | Block known exploit patterns |
| 4 | Rate limit: 10,000 req/5min per IP | Block | Prevent IP-based abuse |
| 5 | Rate limit: 1,000 req/5min per API key | Block | Prevent key-based abuse |
| 6 | Geo-blocking (optional) | Block | Compliance restrictions |

**Logging:** WAF logs to CloudWatch Logs (sampled at 10% in production)

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Web ACL ($5/mo) | $5/mo | $5/mo | $5/mo |
| Rules ($1/rule/mo) | $6/mo | $6/mo | $6/mo |
| Requests ($0.60/M) | $36/mo (60M) | $180/mo (300M) | $900/mo (1.5B) |
| **WAF Total** | **~$47/mo** | **~$191/mo** | **~$911/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **Cloudflare** | External dependency; adds latency; complicates architecture; WAF is native to API Gateway |
| **Application-level rate limiting only** | Insufficient for DDoS; no IP reputation; WAF blocks requests before they reach Lambda |

### AWS Documentation
- [WAF Developer Guide](https://docs.aws.amazon.com/waf/latest/developerguide/)
- [WAF Pricing](https://aws.amazon.com/waf/pricing/)

---

## 15. Amazon ECS Fargate

### Purpose
Runs long-lived IMAP and SMTP server processes that cannot run on Lambda (which has 15-minute timeout and no TCP socket support). These servers translate IMAP/SMTP protocol commands into internal API calls.

### Configuration Details

**Cluster:** `agentmail-protocols`

**Services:**

| Service | Image | CPU | Memory | Min Tasks | Max Tasks | Port |
|---------|-------|-----|--------|-----------|-----------|------|
| `imap-server` | `agentmail/imap:latest` | 1 vCPU | 2 GB | 2 | 20 | 993 (IMAPS) |
| `smtp-server` | `agentmail/smtp:latest` | 0.5 vCPU | 1 GB | 2 | 10 | 465 (SMTPS) |

**Auto-scaling:**
- Target tracking: Average CPU utilization 60%
- Custom metric: Active connections per task (target: 500 for IMAP, 200 for SMTP)
- Scale-in cooldown: 300 seconds
- Scale-out cooldown: 60 seconds

**Networking:**
- Tasks in private subnets
- NAT Gateway for outbound internet (DynamoDB, S3, SES API calls)
- NLB in public subnets (TCP pass-through, TLS terminated at Fargate task)
- Security group: Allow inbound 993/465 from NLB only

**Health checks:**
- NLB: TCP health check on service port
- ECS: Custom health check endpoint (HTTP :8080/health internal)

**Logging:** stdout/stderr to CloudWatch Logs via awslogs driver

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| IMAP Fargate (2 tasks) | $60/mo | $150/mo (5 tasks) | $600/mo (20 tasks) |
| SMTP Fargate (2 tasks) | $30/mo | $60/mo (4 tasks) | $150/mo (10 tasks) |
| NLB ($0.0225/hr + LCU) | $18/mo | $25/mo | $50/mo |
| NAT Gateway (shared with Lambda) | (counted under Lambda) | | |
| **ECS Fargate Total** | **~$108/mo** | **~$235/mo** | **~$800/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **EC2 instances** | Requires patching, AMI management; Fargate is fully managed |
| **Lambda (with function URLs)** | No TCP socket support; 15-min timeout; IMAP requires persistent connections |
| **App Runner** | No TCP support; HTTP only; cannot run IMAP/SMTP protocols |
| **Lightsail containers** | Limited scaling; no NLB integration; less mature |

### AWS Documentation
- [ECS Fargate Guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)
- [Fargate Pricing](https://aws.amazon.com/fargate/pricing/)

---

## 16. Network Load Balancer (NLB)

### Purpose
Load balance TCP connections across IMAP and SMTP Fargate tasks. NLB is required because IMAP and SMTP are TCP protocols (not HTTP), which ALB cannot handle at the TCP level.

### Configuration Details

- **Type**: Network Load Balancer (internet-facing)
- **Subnets**: Public subnets in 2 AZs
- **Cross-zone load balancing**: Enabled
- **Listeners**:
  - Port 993 (IMAPS) -> Target group: IMAP Fargate tasks
  - Port 465 (SMTPS) -> Target group: SMTP Fargate tasks
- **TLS termination**: At Fargate task level (NLB is TCP pass-through)
- **Sticky sessions**: Enabled for IMAP (client_ip, 1 hour) -- IMAP connections should persist to same task
- **Health checks**: TCP on service ports, 10-second interval

### Cost Estimates

Included in ECS Fargate section above (~$18-50/mo).

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **ALB** | Does not support raw TCP; only HTTP/HTTPS; cannot load balance IMAP/SMTP |
| **Global Accelerator** | Useful for multi-region but adds cost; not needed initially |

### AWS Documentation
- [NLB Guide](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/)
- [NLB Pricing](https://aws.amazon.com/elasticloadbalancing/pricing/)

---

## 17. Amazon SQS

### Purpose
Dead-letter queues for failed event processing and decoupling for specific async workflows where ordered delivery is not required.

### Configuration Details

**Queues:**

| Queue | Type | Visibility Timeout | Retention | Purpose |
|-------|------|-------------------|-----------|---------|
| `webhook-delivery-dlq` | Standard | 300s | 14 days | Failed webhook deliveries for retry |
| `ai-processing-dlq` | Standard | 300s | 14 days | Failed AI processing for retry |
| `inbound-email-dlq` | Standard | 300s | 14 days | Failed inbound email processing |
| `bounce-processing-dlq` | Standard | 300s | 14 days | Failed bounce handling |

**DLQ redrive:**
- Maximum receives before DLQ: 3 (configured on Kinesis event source mapping)
- DLQ alarm: If message count > 0, alert to investigate
- Periodic redrive: Lambda on EventBridge schedule checks DLQ and redrives to Kinesis (with backoff)

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Requests ($0.40/M) | $1/mo | $5/mo | $20/mo |
| **SQS Total** | **~$1/mo** | **~$5/mo** | **~$20/mo** |

### AWS Documentation
- [SQS Developer Guide](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/)
- [SQS Pricing](https://aws.amazon.com/sqs/pricing/)

---

## 18. Amazon SNS

### Purpose
Receive SES feedback notifications (bounces, complaints, deliveries) and route AWS Marketplace subscription lifecycle events to Lambda handlers.

### Configuration Details

**Topics:**

| Topic | Subscriptions | Purpose |
|-------|-------------|---------|
| `ses-bounces` | Lambda: bounce-processor | Process email bounces |
| `ses-complaints` | Lambda: bounce-processor | Process spam complaints |
| `ses-deliveries` | Lambda: delivery-tracker (optional) | Track successful deliveries |
| `marketplace-subscription` | Lambda: marketplace-subscription | Handle subscribe/unsubscribe events |
| `ops-alerts` | Email, PagerDuty | Operational alerts from CloudWatch alarms |
| `ops-notifications` | Slack webhook | Non-critical operational notifications |

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Notifications ($0.50/M) | $1/mo | $5/mo | $20/mo |
| Lambda deliveries | Free (first 1M) | $1/mo | $5/mo |
| **SNS Total** | **~$1/mo** | **~$6/mo** | **~$25/mo** |

### AWS Documentation
- [SNS Developer Guide](https://docs.aws.amazon.com/sns/latest/dg/)
- [SNS Pricing](https://aws.amazon.com/sns/pricing/)

---

## 19. AWS Step Functions

### Purpose
Orchestrate the hourly metering workflow that reports usage to AWS Marketplace. Step Functions ensure exactly-once execution, handle retries, and maintain state across the multi-step metering process.

### Configuration Details

**State machine:** `agentmail-metering-workflow`

**Workflow steps:**
1. **Query usage** -- Lambda reads hourly usage from DynamoDB (per-org, per-dimension)
2. **Validate data** -- Check for anomalies (sudden 10x spike = possible error)
3. **Report to Marketplace** -- Lambda calls `BatchMeterUsage` API
4. **Record result** -- Lambda writes metering record to DynamoDB (for audit trail)
5. **Handle failure** -- On any step failure, write to DLQ and alert

**Execution frequency:** Hourly (triggered by EventBridge)

**Type:** Standard (not Express) -- metering requires at-most-once execution guarantees and audit trail

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| State transitions ($0.025/1K) | $1/mo (~730 executions x 5 steps) | $5/mo | $10/mo |
| **Step Functions Total** | **~$1/mo** | **~$5/mo** | **~$10/mo** |

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **Lambda-only (chained)** | No built-in state management; harder to debug; no visual workflow; retry logic is manual |
| **EventBridge Pipes** | Designed for event routing, not orchestration; no branching/error handling |

### AWS Documentation
- [Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/)
- [Step Functions Pricing](https://aws.amazon.com/step-functions/pricing/)

---

## 20. AWS Marketplace Metering Service

### Purpose
Report customer usage to AWS Marketplace for consumption-based billing. The Metering Service is the bridge between our usage tracking and AWS's billing system.

### Configuration Details

**API:** `BatchMeterUsage`
- Called hourly via Step Functions workflow
- Reports usage for all active customers in a single batch (up to 25 records per call)
- Dimensions must match those registered in the Marketplace listing

**Metering dimensions:**

| Dimension Key | Unit | Description |
|---------------|------|-------------|
| `active_inboxes` | Count | Number of active inboxes at time of report |
| `messages_sent` | Count | Messages sent in the hour |
| `messages_received` | Count | Messages received in the hour |
| `ai_categorizations` | Count | AI categorizations performed |
| `ai_extractions` | Count | AI extractions performed |
| `semantic_searches` | Count | Semantic search queries |
| `storage_gb` | Count | GB of storage used (rounded up) |

**Idempotency:** Each metering record includes a unique `UsageRecordId` to prevent duplicate billing.

### Cost Estimates

No direct cost for the Metering Service API. AWS takes a revenue share (3-5%) on total Marketplace revenue.

### AWS Documentation
- [Marketplace Metering API](https://docs.aws.amazon.com/marketplacemetering/latest/APIReference/)
- [SaaS Metering](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-metering.html)

---

## 21. AWS Marketplace Entitlement Service

### Purpose
Validate customer subscriptions and check what they are entitled to (tier, included quantities, overage pricing) before processing API requests.

### Configuration Details

**API:** `GetEntitlements`
- Called on every API request (result cached in Redis for 5 minutes)
- Returns customer's active contract dimensions and quantities
- Used to enforce quotas and determine pricing tier

**Integration flow:**
1. API request arrives with API key
2. Lambda resolves API key -> organization ID (DynamoDB lookup, cached in Redis)
3. Lambda checks entitlement cache in Redis
4. If cache miss, calls `GetEntitlements` API
5. Validates request against entitlement (e.g., inbox count within limit)
6. If over limit, returns 429 with upgrade message

**Subscription lifecycle (via SNS):**
- `subscribe-success`: Create organization, enable API access
- `unsubscribe-pending`: Warn customer, start 30-day grace period
- `unsubscribe-success`: Disable API access, schedule data deletion (90 days)

### Cost Estimates

No direct cost for the Entitlement Service API.

### AWS Documentation
- [Marketplace Entitlement API](https://docs.aws.amazon.com/marketplaceentitlement/latest/APIReference/)
- [SaaS Contracts](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-contracts.html)

---

## 22. AWS Secrets Manager

### Purpose
Securely store and automatically rotate sensitive credentials: Redis AUTH tokens, SES SMTP credentials (for IMAP/SMTP Fargate tasks), internal API keys, and DKIM private keys.

### Configuration Details

**Secrets:**

| Secret | Rotation | Consumers |
|--------|----------|-----------|
| `agentmail/redis-auth-token` | 90 days | All Lambda functions, ECS tasks |
| `agentmail/ses-smtp-credentials` | 90 days | SMTP Fargate tasks |
| `agentmail/internal-api-key` | 180 days | Service-to-service auth |
| `agentmail/marketplace-signing-key` | Never (AWS-provided) | Marketplace Lambda |
| `agentmail/webhook-signing-key` | 90 days | Webhook dispatcher |

**Rotation:** Lambda-based rotation functions, triggered by Secrets Manager

**Access:** IAM policies grant read access to specific secrets per Lambda function/ECS task (least privilege)

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Secrets ($0.40/secret/mo) | $2/mo | $3/mo | $5/mo |
| API calls ($0.05/10K) | $1/mo | $5/mo | $20/mo |
| **Secrets Manager Total** | **~$3/mo** | **~$8/mo** | **~$25/mo** |

### AWS Documentation
- [Secrets Manager User Guide](https://docs.aws.amazon.com/secretsmanager/latest/userguide/)
- [Secrets Manager Pricing](https://aws.amazon.com/secrets-manager/pricing/)

---

## 23. AWS KMS (Key Management Service)

### Purpose
Manage encryption keys for data at rest. KMS provides the master keys used by DynamoDB, S3, SQS, Kinesis, OpenSearch, and Secrets Manager for server-side encryption.

### Configuration Details

**Keys:**

| Key | Alias | Usage |
|-----|-------|-------|
| AWS-managed DynamoDB key | `aws/dynamodb` | DynamoDB table encryption |
| AWS-managed S3 key | `aws/s3` | S3 default encryption (SSE-S3 uses Amazon-managed, not KMS) |
| Customer-managed key | `agentmail/data` | Backups, sensitive S3 objects, Secrets Manager |
| AWS-managed Kinesis key | `aws/kinesis` | Kinesis stream encryption |

**Note:** Using AWS-managed keys where possible to minimize KMS API call costs. Customer-managed key only for backup encryption and audit requirements.

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Customer-managed keys ($1/key/mo) | $1/mo | $1/mo | $2/mo |
| API calls ($0.03/10K) | $3/mo | $15/mo | $60/mo |
| **KMS Total** | **~$4/mo** | **~$16/mo** | **~$62/mo** |

### AWS Documentation
- [KMS Developer Guide](https://docs.aws.amazon.com/kms/latest/developerguide/)
- [KMS Pricing](https://aws.amazon.com/kms/pricing/)

---

## 24. AWS IAM (Identity and Access Management)

### Purpose
Define least-privilege access policies for all services. Every Lambda function, ECS task, and service has a dedicated IAM role with only the permissions it needs.

### Configuration Details

**Key roles:**

| Role | Attached To | Key Permissions |
|------|-------------|----------------|
| `agentmail-api-handler-role` | API Lambda functions | DynamoDB (CRUD on main table), S3 (GetObject, PutObject), ElastiCache (read/write), SES (SendRawEmail) |
| `agentmail-inbound-processor-role` | Inbound processor Lambda | S3 (GetObject on SES bucket), DynamoDB (write), Kinesis (PutRecord) |
| `agentmail-ai-processor-role` | AI Lambda functions | Bedrock (InvokeModel), OpenSearch (index, search), DynamoDB (read/write) |
| `agentmail-webhook-role` | Webhook dispatcher Lambda | DynamoDB (read webhooks), SQS (send to DLQ) |
| `agentmail-metering-role` | Metering Lambda | DynamoDB (read metrics), Marketplace Metering (BatchMeterUsage) |
| `agentmail-imap-task-role` | IMAP ECS task | DynamoDB (read), S3 (GetObject), SecretsManager (GetSecretValue) |
| `agentmail-smtp-task-role` | SMTP ECS task | DynamoDB (read/write), S3 (PutObject), SES (SendRawEmail), SecretsManager (GetSecretValue) |

**Key policies:**
- All roles use `Condition` blocks to restrict resource access by ARN pattern (e.g., DynamoDB table ARN, S3 bucket ARN)
- No `*` resource permissions except for CloudWatch Logs (CreateLogGroup/CreateLogStream/PutLogEvents)
- Service-linked roles for ElastiCache, OpenSearch Serverless, ECS

**SCPs (if using AWS Organizations):**
- Deny: Creating IAM users (service accounts only)
- Deny: Disabling CloudTrail
- Deny: Public S3 bucket creation

### Cost Estimates

No direct cost (IAM is free).

### AWS Documentation
- [IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/)
- [IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)

---

## 25. Amazon CloudFront

### Purpose
CDN and edge protection layer in front of API Gateway. Provides DDoS protection (Shield Standard included), edge caching for GET requests, and a single global endpoint.

### Configuration Details

- **Distribution**: api.agentmail.com
- **Origin**: API Gateway regional endpoint
- **Cache behavior**:
  - GET requests: Cache with TTL based on Cache-Control headers from API Gateway
  - POST/PUT/DELETE: Forward to origin (no caching)
  - OPTIONS: Cache for 24 hours (CORS preflight)
- **SSL/TLS**: ACM certificate for api.agentmail.com, TLS 1.2 minimum
- **Price class**: PriceClass_100 (US, Canada, Europe) -- expand as needed
- **WAF**: Web ACL associated (same WAF as API Gateway for defense in depth)
- **Compression**: Gzip and Brotli enabled for JSON responses

### Cost Estimates

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|------------|
| Data transfer ($0.085/GB) | $10/mo | $50/mo | $250/mo |
| Requests ($0.01/10K HTTPS) | $60/mo (60M req) | $300/mo | $1,500/mo |
| **CloudFront Total** | **~$70/mo** | **~$350/mo** | **~$1,750/mo** |

**Note:** CloudFront cost may not justify itself at startup. Consider adding at growth tier when global latency optimization becomes important.

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| **API Gateway edge-optimized** | Uses CloudFront internally but no cache control; might be sufficient at startup |
| **Cloudflare** | External dependency; complicates SSL and WAF setup; not AWS-native |

### AWS Documentation
- [CloudFront Developer Guide](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/)
- [CloudFront Pricing](https://aws.amazon.com/cloudfront/pricing/)

---

## 26. AWS CodeDeploy

### Purpose
Manage Lambda function deployments with traffic shifting (canary and linear) to minimize risk of bad deployments.

### Configuration Details

- **Deployment type**: Lambda (CodeDeploy manages Lambda alias traffic shifting)
- **Deployment configuration**:
  - Dev/staging: `CodeDeployDefault.LambdaAllAtOnce`
  - Production: `CodeDeployDefault.LambdaCanary10Percent5Minutes`
- **Pre-traffic hook**: Lambda that validates new function version (smoke tests)
- **Post-traffic hook**: Lambda that checks CloudWatch alarms after traffic shift
- **Automatic rollback**: Enabled on CloudWatch alarm trigger (error rate, latency)

**Integration with CI/CD:**
- GitHub Actions triggers CodeDeploy after successful build/test
- SAM/CDK handles CodeDeploy integration via `AutoPublishAlias` and `DeploymentPreference`

### Cost Estimates

No direct cost for CodeDeploy with Lambda.

### AWS Documentation
- [CodeDeploy with Lambda](https://docs.aws.amazon.com/codedeploy/latest/userguide/welcome.html)
- [SAM Deployment Preferences](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/automating-updates-to-serverless-apps.html)

---

## Total Cost Summary

### Startup Tier (~100K inboxes, ~500K messages/day)

| Service | Monthly Cost |
|---------|-------------|
| SES | $25 |
| API Gateway | $225 |
| Lambda | $150 |
| DynamoDB | $50 |
| S3 | $16 |
| ElastiCache | $137 |
| Kinesis | $100 |
| EventBridge | $2 |
| OpenSearch Serverless | $705 |
| Bedrock | $20 |
| Route 53 | $9 |
| CloudWatch | $57 |
| X-Ray | $17 |
| WAF | $47 |
| ECS Fargate + NLB | $108 |
| SQS | $1 |
| SNS | $1 |
| Step Functions | $1 |
| Secrets Manager | $3 |
| KMS | $4 |
| CloudFront | $70 |
| CodeDeploy | $0 |
| IAM | $0 |
| Marketplace APIs | $0 |
| **TOTAL** | **~$1,748/mo** |

### Growth Tier (~1M inboxes, ~3M messages/day)

| Service | Monthly Cost |
|---------|-------------|
| SES | $250 |
| API Gateway | $1,200 |
| Lambda | $960 |
| DynamoDB | $470 |
| S3 | $167 |
| ElastiCache | $545 |
| Kinesis | $361 |
| EventBridge | $10 |
| OpenSearch Serverless | $750 |
| Bedrock | $120 |
| Route 53 | $62 |
| CloudWatch | $322 |
| X-Ray | $80 |
| WAF | $191 |
| ECS Fargate + NLB | $235 |
| SQS | $5 |
| SNS | $6 |
| Step Functions | $5 |
| Secrets Manager | $8 |
| KMS | $16 |
| CloudFront | $350 |
| **TOTAL** | **~$6,113/mo** |

### Full Scale Tier (~10M inboxes, ~10M messages/day)

| Service | Monthly Cost |
|---------|-------------|
| SES | $700 |
| API Gateway | $6,000 |
| Lambda | $4,400 |
| DynamoDB | $4,700 |
| S3 | $1,535 |
| ElastiCache | $2,180 |
| Kinesis | $1,474 |
| EventBridge | $40 |
| OpenSearch Serverless | $1,900 |
| Bedrock | $600 |
| Route 53 | $552 |
| CloudWatch | $1,295 |
| X-Ray | $135 |
| WAF | $911 |
| ECS Fargate + NLB | $800 |
| SQS | $20 |
| SNS | $25 |
| Step Functions | $10 |
| Secrets Manager | $25 |
| KMS | $62 |
| CloudFront | $1,750 |
| **TOTAL** | **~$29,114/mo** |

**Note:** The full-scale estimate of ~$29K/mo is well under the $80K target in the master README, leaving substantial headroom for:
- Reserved capacity purchases (reduce on-demand costs)
- Additional redundancy (multi-region)
- Unexpected traffic spikes
- Growth beyond 10M inboxes
- Additional features requiring more compute/storage

### Top Cost Drivers by Tier

**Startup:** OpenSearch Serverless (40%), API Gateway (13%), Lambda (9%)
- Action: Consider deferring OpenSearch Serverless; use DynamoDB-based search initially

**Growth:** API Gateway (20%), Lambda (16%), OpenSearch Serverless (12%)
- Action: Evaluate HTTP API migration; optimize Lambda memory/duration

**Full Scale:** API Gateway (21%), DynamoDB (16%), Lambda (15%)
- Action: API Gateway HTTP API migration, DynamoDB reserved capacity, Lambda Graviton2 optimization
