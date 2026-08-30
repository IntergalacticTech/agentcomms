# Cost Analysis

This document provides a detailed cost breakdown for AgentMail at three scales of operation: Startup (100K inboxes), Growth (1M inboxes), and Full Scale (10M inboxes). Every AWS service used in the platform is enumerated with its pricing calculation. The analysis then derives unit economics, revenue projections, margins, and cost optimization strategies.

All prices are based on us-east-1 on-demand pricing as of early 2026. Prices are rounded to the nearest dollar for readability. Reserved capacity and savings plan discounts are modeled separately in the optimization section.

---

## Table of Contents

- [Scale Definitions](#scale-definitions)
- [Per-Service Cost Breakdown](#per-service-cost-breakdown)
- [Cost Summary by Scale](#cost-summary-by-scale)
- [Unit Economics](#unit-economics)
- [Revenue Model](#revenue-model)
- [Cost Optimization Levers](#cost-optimization-levers)
- [Break-Even Analysis](#break-even-analysis)
- [AWS Enterprise Discount Program](#aws-enterprise-discount-program)
- [Marketplace Fee Impact](#marketplace-fee-impact)

---

## Scale Definitions

| Metric | Startup | Growth | Full Scale |
|--------|---------|--------|-----------|
| Active inboxes | 100,000 | 1,000,000 | 10,000,000 |
| Organizations (tenants) | 50 | 500 | 5,000 |
| Messages sent/day | 50,000 | 500,000 | 5,000,000 |
| Messages received/day | 50,000 | 500,000 | 5,000,000 |
| Total messages/day | 100,000 | 1,000,000 | 10,000,000 |
| Total messages/month | 3,000,000 | 30,000,000 | 300,000,000 |
| Average message size | 25 KB body + 5 KB metadata | 25 KB + 5 KB | 25 KB + 5 KB |
| Attachments (10% of messages) | 300,000/mo | 3,000,000/mo | 30,000,000/mo |
| Average attachment size | 500 KB | 500 KB | 500 KB |
| AI categorizations (50% of inbound) | 750,000/mo | 7,500,000/mo | 75,000,000/mo |
| AI extractions (10% of inbound) | 150,000/mo | 1,500,000/mo | 15,000,000/mo |
| Semantic searches | 300,000/mo | 3,000,000/mo | 30,000,000/mo |
| Webhook deliveries (80% of messages) | 2,400,000/mo | 24,000,000/mo | 240,000,000/mo |
| WebSocket connections (concurrent) | 500 | 5,000 | 50,000 |
| API calls/month | 15,000,000 | 150,000,000 | 1,500,000,000 |
| Storage (cumulative after 12 months) | 1 TB | 10 TB | 100 TB |

---

## Free Tier Cost Model

The direct SaaS product includes a permanent free tier (5 inboxes, 1,000 emails/month, 30-day retention, no AI features). Understanding the cost of free users is critical to ensuring the growth funnel is economically sustainable.

### Per-User Cost Breakdown (Free Tier at Limit)

A free-tier user consuming their full allocation (5 inboxes, 1,000 emails/month) costs:

| Service | Calculation | Monthly Cost |
|---------|-------------|-------------|
| **Amazon SES** | 1,000 emails x $0.10/1K (send) + 1,000 x $0.10/1K (receive) | $0.20 |
| **Amazon S3** | 1,000 msgs x 25KB = 25 MB storage + PUTs | $0.003 |
| **Amazon DynamoDB** | 1,000 msgs x 5 WCU + reads + metadata | $0.01 |
| **AWS Lambda** | ~3,000 invocations (API + processing) x 512MB x 200ms | $0.001 |
| **Other** (API Gateway, CloudWatch, Redis share) | Amortized | ~$0.006 |
| **Total** | | **~$0.22/month** |

Most free users will not hit their full allocation. Typical usage is expected to be 30-50% of limits, bringing the effective cost to ~$0.07-$0.11/user/month.

### Aggregate Cost Projections

| Free Users | Monthly Cost (at limit) | Monthly Cost (typical 40%) | Annual Cost (typical) |
|------------|------------------------|---------------------------|----------------------|
| 1,000 | $220 | $88 | $1,056 |
| 10,000 | $2,200 | $880 | $10,560 |
| 100,000 | $22,000 | $8,800 | $105,600 |

### Why This Is Acceptable

The free tier is a growth funnel. At a 5% conversion rate to Pro ($29/month):

- **10,000 free users** -> 500 paying users -> $14,500/month revenue vs ~$2,200/month cost (6.6x return)
- **100,000 free users** -> 5,000 paying users -> $145,000/month revenue vs ~$22,000/month cost (6.6x return)

Even at a conservative 2% conversion rate, 10,000 free users yield 200 paying users = $5,800/month revenue, still well above the $2,200 cost.

### Break-Even Analysis

To cover the cost of 10,000 free users ($2,200/month), we need:

- At $29/month (Pro): **76 paid users** (0.76% conversion rate)
- At $99/month (Business): **23 paid users** (0.23% conversion rate)
- At $299/month (Scale): **8 paid users** (0.08% conversion rate)

The break-even conversion rate of 0.76% is well below typical developer-tool free-to-paid conversion rates of 2-5%.

### Cost Guardrails

Free-tier users are subject to hard limits that cap infrastructure cost:

| Guardrail | Limit | Purpose |
|-----------|-------|---------|
| Inboxes | 5 max | Caps SES configuration and DynamoDB metadata |
| Emails | 1,000/month hard cap | Prevents runaway SES and storage costs |
| Retention | 30 days | S3 lifecycle auto-deletes after 30 days, keeping storage bounded |
| AI features | Disabled | Eliminates Bedrock and OpenSearch costs entirely |
| Rate limiting | 10 req/sec, 20 burst | Prevents Lambda concurrency abuse |
| Attachment size | 5 MB max | Limits S3 storage per message |
| Custom domains | 1 max | Limits Route 53 and SES domain verification overhead |

### Alert Thresholds

| Threshold | Monthly Free-Tier Spend | Action |
|-----------|------------------------|--------|
| **Review** | $5,000 | Analyze conversion funnel efficiency, check for abuse patterns |
| **Concern** | $15,000 | Tighten rate limits, evaluate free tier limits, accelerate conversion experiments |
| **Action Required** | $25,000 | Reduce free tier limits, require credit card on sign-up, or introduce usage-based free tier |

---

## Per-Service Cost Breakdown

### 1. Amazon DynamoDB

**Pricing**: On-demand mode: $1.25 per million WCUs, $0.25 per million RCUs. Storage: $0.25/GB/month.

**Write operations per message**: ~5 WCUs (message item + thread update + inbox counter + GSI writes)
**Read operations per API call**: ~2 RCUs average (inbox lookup + message query)

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Write capacity (messages) | 3M msgs x 5 WCU = 15M WCU x $1.25/M = **$19** | 30M x 5 = 150M WCU = **$188** | 300M x 5 = 1.5B WCU = **$1,875** |
| Write capacity (other ops) | 5M WCU = **$6** | 50M WCU = **$63** | 500M WCU = **$625** |
| Read capacity (API calls) | 15M calls x 2 RCU = 30M RCU x $0.25/M = **$8** | 150M x 2 = 300M RCU = **$75** | 1.5B x 2 = 3B RCU = **$750** |
| Read capacity (internal) | 10M RCU = **$3** | 100M RCU = **$25** | 1B RCU = **$250** |
| Storage | 50 GB x $0.25 = **$13** | 500 GB x $0.25 = **$125** | 5 TB x $0.25 = **$1,250** |
| DynamoDB Streams | 3M records x $0.02/100K = **$1** | 30M = **$6** | 300M = **$60** |
| Global Tables (replication, Phase 4) | $0 | $0 | WCU replicated: ~**$2,500** |
| **DynamoDB Total** | **$50** | **$482** | **$7,310** |

### 2. Amazon S3

**Pricing**: Standard: $0.023/GB/month. PUT: $0.005/1K. GET: $0.0004/1K. Lifecycle to IA: $0.0125/GB. Lifecycle to Glacier IR: $0.004/GB.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Raw email storage (bodies) | 3M x 25KB = 75 GB x $0.023 = **$2** | 750 GB = **$17** | 7.5 TB = **$173** |
| Attachment storage | 300K x 500KB = 150 GB x $0.023 = **$3** | 1.5 TB = **$35** | 15 TB = **$345** |
| Cumulative storage (12 mo) | 1 TB Standard x $0.023 = **$23** | 5 TB Std + 5 TB IA = **$178** | 20 TB Std + 40 TB IA + 40 TB Glacier = **$1,020** |
| PUT requests | 3.3M x $0.005/1K = **$17** | 33M = **$165** | 330M = **$1,650** |
| GET requests | 15M x $0.0004/1K = **$6** | 150M = **$60** | 1.5B = **$600** |
| Data transfer (to internet) | Minimal (presigned URLs) = **$5** | **$50** | **$500** |
| Cross-region replication (Phase 4) | $0 | $0 | ~**$800** |
| **S3 Total** | **$56** | **$505** | **$5,088** |

### 3. Amazon SES

**Pricing**: Sending: $0.10/1,000 emails. Receiving: $0.10/1,000 emails (first 1,000 free). Dedicated IPs: $24.95/IP/month.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Outbound sending | 1.5M/mo x $0.10/1K = **$150** | 15M = **$1,500** | 150M = **$15,000** |
| Inbound receiving | 1.5M/mo x $0.10/1K = **$150** | 15M = **$1,500** | 150M = **$15,000** |
| Dedicated IPs | 2 IPs x $24.95 = **$50** | 5 IPs = **$125** | 20 IPs = **$499** |
| VDM (Virtual Deliverability Manager) | $0.07/1K emails x 3M = **$210** | 30M = **$2,100** | Negotiated: ~**$15,000** |
| **SES Total** | **$560** | **$5,225** | **$45,499** |

### 4. AWS Lambda

**Pricing**: $0.20/1M invocations. Duration: $0.0000166667/GB-second (ARM64). Provisioned concurrency: $0.0000041667/GB-second.

Average invocation: 512 MB, 200ms duration.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| API handler invocations | 15M x $0.20/M = **$3** | 150M = **$30** | 1.5B = **$300** |
| API handler duration | 15M x 0.2s x 0.5 GB x $0.0000166667 = **$25** | **$250** | **$2,500** |
| Inbound processor | 1.5M x $0.20/M + duration = **$5** | **$50** | **$500** |
| Send worker | 1.5M x $0.20/M + duration = **$5** | **$50** | **$500** |
| Webhook delivery | 2.4M x $0.20/M + duration = **$8** | **$80** | **$800** |
| AI pipeline (categorizer) | 750K x $0.20/M + duration (500ms avg) = **$4** | **$40** | **$400** |
| AI pipeline (extractor) | 150K x $0.20/M + duration (1s avg) = **$2** | **$16** | **$160** |
| AI pipeline (embedder) | 1.5M x $0.20/M + duration (300ms avg) = **$5** | **$50** | **$500** |
| Other functions | **$10** | **$50** | **$300** |
| Provisioned concurrency (prod) | $0 (not needed yet) | 50 x 512MB x 730h = **$109** | 200 x 512MB = **$437** |
| **Lambda Total** | **$67** | **$725** | **$6,397** |

### 5. Amazon API Gateway

**Pricing**: REST API: $3.50/million requests (first 333M), $2.80/M (next 667M), $2.38/M (over 1B). WebSocket: $1.00/M connection minutes + $1.00/M messages.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| REST API requests | 15M x $3.50/M = **$53** | 150M x $3.50/M = **$525** | 1B x $3.50 + 500M x $2.80 = **$4,900** |
| WebSocket connection minutes | 500 conn x 730h x 60min = 21.9M min x $1/M = **$22** | 219M min = **$219** | 2.19B min = **$2,190** |
| WebSocket messages | 3M/mo x $1/M = **$3** | 30M = **$30** | 300M = **$300** |
| **API Gateway Total** | **$78** | **$774** | **$7,390** |

### 6. ElastiCache (Redis)

**Pricing**: cache.r7g.large (2 vCPU, 13.07 GB): $0.252/hour on-demand.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Cluster size | 1 shard x 2 nodes (primary + replica) | 2 shards x 2 nodes = 4 nodes | 4 shards x 3 nodes = 12 nodes |
| Instance type | cache.r7g.medium ($0.126/hr) | cache.r7g.large ($0.252/hr) | cache.r7g.large ($0.252/hr) |
| Compute | 2 x $0.126 x 730 = **$184** | 4 x $0.252 x 730 = **$736** | 12 x $0.252 x 730 = **$2,208** |
| Data transfer | **$5** | **$20** | **$100** |
| **ElastiCache Total** | **$189** | **$756** | **$2,308** |

### 7. Amazon OpenSearch Serverless

**Pricing**: Indexing OCU: $0.24/OCU/hour. Search OCU: $0.24/OCU/hour. Storage: $0.024/GB/month. Minimum: 2 indexing OCU + 2 search OCU.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Indexing OCUs | 2 OCU x $0.24 x 730 = **$350** | 4 OCU = **$701** | 10 OCU = **$1,752** |
| Search OCUs | 2 OCU x $0.24 x 730 = **$350** | 4 OCU = **$701** | 10 OCU = **$1,752** |
| Storage | 10 GB x $0.024 = **$0** | 100 GB = **$2** | 1 TB = **$24** |
| **OpenSearch Total** | **$700** | **$1,404** | **$3,528** |

### 8. Amazon Kinesis Data Streams

**Pricing**: On-demand: $0.08/GB ingested + $0.04/hour/shard (provisioned). Provisioned: $0.015/shard/hour + PUT payload: $0.014/1M.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Shards (provisioned) | 2 x $0.015 x 730 = **$22** | 4 shards = **$44** | 16 shards = **$175** |
| PUT payload | 3M records x 1KB avg / 25KB per unit = minimal = **$1** | **$6** | **$60** |
| Extended retention (7 days) | 2 x $0.02 x 730 = **$29** | 4 = **$58** | 16 = **$234** |
| **Kinesis Total** | **$52** | **$108** | **$469** |

### 9. Amazon Bedrock

**Pricing**: Claude 3.5 Haiku: $0.25/1M input tokens, $1.25/1M output tokens. Claude 3.5 Sonnet: $3/1M input, $15/1M output. Titan Embeddings v2: $0.02/1M input tokens.

Average email: ~500 tokens input. Categorization output: ~50 tokens. Extraction output: ~200 tokens. Embedding: ~500 tokens input.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Categorization (Haiku) input | 750K x 500 tokens = 375M tokens x $0.25/M = **$94** | 3.75B = **$938** | 37.5B = **$9,375** |
| Categorization (Haiku) output | 750K x 50 tokens = 37.5M x $1.25/M = **$47** | 375M = **$469** | 3.75B = **$4,688** |
| Extraction (Sonnet) input | 150K x 500 tokens = 75M x $3/M = **$225** | 750M = **$2,250** | 7.5B = **$22,500** |
| Extraction (Sonnet) output | 150K x 200 tokens = 30M x $15/M = **$450** | 300M = **$4,500** | 3B = **$45,000** |
| Embeddings (Titan v2) | 1.5M x 500 tokens = 750M x $0.02/M = **$15** | 7.5B = **$150** | 75B = **$1,500** |
| Semantic search embeddings | 300K x 100 tokens = 30M x $0.02/M = **$1** | 300M = **$6** | 3B = **$60** |
| **Bedrock Total** | **$832** | **$8,313** | **$83,123** |

### 10. Amazon SQS

**Pricing**: $0.40/1M requests (first 1B), $0.30/M thereafter. Free tier: 1M requests/month.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Send queue | 3M msgs x 3 operations (send, receive, delete) = 9M x $0.40/M = **$4** | 90M = **$36** | 900M = **$360** |
| Webhook queue | 2.4M x 3 = 7.2M = **$3** | 72M = **$29** | 720M = **$288** |
| DLQ operations | Minimal = **$0** | **$1** | **$5** |
| **SQS Total** | **$7** | **$66** | **$653** |

### 11. AWS Step Functions

**Pricing**: Standard: $0.025/1,000 state transitions. Express: $0.00001667/GB-second.

Used for AI orchestration (categorize + extract + embed pipeline). ~5 transitions per execution.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| State transitions | 1.5M executions x 5 = 7.5M x $0.025/1K = **$188** | 75M = **$1,875** | 750M = **$18,750** |
| **Step Functions Total** | **$188** | **$1,875** | **$18,750** |

**Note**: At Full Scale, Step Functions Express Workflows should replace Standard Workflows for the AI pipeline. Express pricing: ~$300/mo at Full Scale (98% reduction). This is captured in the optimization section.

### 12. Amazon CloudWatch

**Pricing**: Custom metrics: $0.30/metric/month (first 10K). Logs: $0.50/GB ingested. Logs Insights: $0.0050/GB scanned. Alarms: $0.10/alarm/month. Dashboards: $3/dashboard/month.

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| Custom metrics (~200 metrics) | 200 x $0.30 = **$60** | 500 x $0.30 = **$150** | 1000 x $0.30 = **$300** |
| Log ingestion | 20 GB/mo x $0.50 = **$10** | 200 GB = **$100** | 2 TB = **$1,000** |
| Log storage (30 days) | 20 GB x $0.03 = **$1** | 200 GB = **$6** | 2 TB = **$60** |
| Log Insights queries | **$5** | **$20** | **$50** |
| Alarms (~50) | 50 x $0.10 = **$5** | 80 x $0.10 = **$8** | 120 x $0.10 = **$12** |
| Dashboards | 5 x $3 = **$15** | 10 x $3 = **$30** | 20 x $3 = **$60** |
| X-Ray traces | 300K x $5/M = **$2** | 3M = **$15** | 30M = **$150** |
| **CloudWatch Total** | **$98** | **$329** | **$1,632** |

### 13. Networking (VPC, NLB, NAT)

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| NAT Gateway (2 AZs) | 2 x $32.85 + data = **$80** | **$120** | **$300** |
| NLB (IMAP/SMTP, Phase 3+) | $0 (not yet) | 1 x $16.43 + LCU = **$50** | **$80** |
| VPC Endpoints (6 endpoints) | 6 x $7.30 x 2 AZ = **$88** | **$88** | **$88** |
| Data transfer (inter-AZ) | **$10** | **$50** | **$200** |
| **Networking Total** | **$178** | **$308** | **$668** |

### 14. ECS Fargate (IMAP/SMTP, Phase 3+)

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| IMAP service | $0 (Phase 3) | 2 tasks x 1vCPU x 2GB = **$66** | 10 tasks = **$330** |
| SMTP service | $0 (Phase 3) | 2 tasks x 0.5vCPU x 1GB = **$36** | 10 tasks = **$180** |
| Webhook heavy processor (ECS) | $0 | 2 tasks x 0.5vCPU x 1GB = **$36** | 6 tasks = **$108** |
| **ECS Fargate Total** | **$0** | **$138** | **$618** |

### 15. Other AWS Services

| Component | Startup | Growth | Full Scale |
|-----------|---------|--------|-----------|
| AWS Secrets Manager | 10 secrets x $0.40 = **$4** | 20 = **$8** | 30 = **$12** |
| Amazon ECR | 2 GB images = **$0** | 5 GB = **$1** | 10 GB = **$1** |
| AWS WAF | 1 WebACL + 5 rules = **$11** | **$11** | **$11** |
| Route 53 | 2 hosted zones + queries = **$5** | **$10** | **$25** |
| AWS Certificate Manager | Free | Free | Free |
| AWS CodeDeploy | Free (Lambda deployments) | Free | Free |
| EventBridge | 3M events x $1/M = **$3** | 30M = **$30** | 300M = **$300** |
| SNS (alarm notifications) | **$1** | **$2** | **$5** |
| **Other Total** | **$24** | **$62** | **$354** |

---

## Cost Summary by Scale

| Service | Startup | Growth | Full Scale |
|---------|---------|--------|-----------|
| DynamoDB | $50 | $482 | $7,310 |
| S3 | $56 | $505 | $5,088 |
| SES | $560 | $5,225 | $45,499 |
| Lambda | $67 | $725 | $6,397 |
| API Gateway | $78 | $774 | $7,390 |
| ElastiCache | $189 | $756 | $2,308 |
| OpenSearch Serverless | $700 | $1,404 | $3,528 |
| Kinesis | $52 | $108 | $469 |
| Bedrock | $832 | $8,313 | $83,123 |
| SQS | $7 | $66 | $653 |
| Step Functions | $188 | $1,875 | $18,750 |
| CloudWatch | $98 | $329 | $1,632 |
| Networking | $178 | $308 | $668 |
| ECS Fargate | $0 | $138 | $618 |
| Other | $24 | $62 | $354 |
| **Total Monthly Cost** | **$3,079** | **$21,070** | **$183,787** |
| **Total Annual Cost** | **$36,948** | **$252,840** | **$2,205,444** |

### Cost Distribution (Full Scale)

```
Bedrock (AI):        $83,123  (45.2%)  ◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆◆
SES:                 $45,499  (24.8%)  ◆◆◆◆◆◆◆◆◆◆◆◆◆
Step Functions:      $18,750  (10.2%)  ◆◆◆◆◆
DynamoDB:             $7,310   (4.0%)  ◆◆
API Gateway:          $7,390   (4.0%)  ◆◆
Lambda:               $6,397   (3.5%)  ◆◆
S3:                   $5,088   (2.8%)  ◆
OpenSearch:           $3,528   (1.9%)  ◆
ElastiCache:          $2,308   (1.3%)  ◆
Everything else:      $4,394   (2.4%)  ◆
```

**Key insight**: At Full Scale, Bedrock (AI features) and SES (email transport) account for 70% of total cost. These are the two services where pricing negotiation and optimization have the highest impact.

---

## Unit Economics

### Cost Per Message

| Metric | Startup | Growth | Full Scale |
|--------|---------|--------|-----------|
| Total cost/month | $3,079 | $21,070 | $183,787 |
| Total messages/month | 3,000,000 | 30,000,000 | 300,000,000 |
| **Cost per message** | **$0.00103** | **$0.00070** | **$0.00061** |

### Cost Per Inbox Per Month

| Metric | Startup | Growth | Full Scale |
|--------|---------|--------|-----------|
| Total cost/month | $3,079 | $21,070 | $183,787 |
| Active inboxes | 100,000 | 1,000,000 | 10,000,000 |
| **Cost per inbox/month** | **$0.031** | **$0.021** | **$0.018** |

### Marginal Cost Breakdown Per Message

What does it cost to process one additional message (send or receive)?

| Cost Component | Per Message |
|---------------|------------|
| SES (send or receive) | $0.000100 |
| DynamoDB (5 WCU + 2 RCU) | $0.000007 |
| S3 (store body + 1 PUT + 1 GET) | $0.000006 |
| Lambda (200ms x 512MB) | $0.000002 |
| SQS (3 operations) | $0.000001 |
| Kinesis (1 record) | $0.000001 |
| **Subtotal (base message)** | **$0.000117** |
| Bedrock categorization (Haiku, 50% of inbound) | $0.000094 |
| Bedrock embedding (Titan v2) | $0.000010 |
| Webhook delivery (80% of messages) | $0.000002 |
| **Subtotal (with AI)** | **$0.000223** |

The base cost of sending or receiving one message is ~$0.00012. With AI features enabled (categorization + embedding), it rises to ~$0.00022.

---

## Revenue Model

### Pricing Assumptions

Based on the pricing tiers in the overview document:

| Dimension | Average Price (blended across tiers) |
|-----------|--------------------------------------|
| Per inbox/month | $0.10 |
| Per message sent | $0.001 |
| Per message received | $0.0005 |
| Per AI categorization | $0.002 |
| Per AI extraction | $0.01 |
| Per semantic search | $0.005 |
| Per GB storage/month | $0.25 |

### Revenue Projections

| Revenue Line | Startup | Growth | Full Scale |
|-------------|---------|--------|-----------|
| Inbox fees | 100K x $0.10 = **$10,000** | 1M x $0.10 = **$100,000** | 10M x $0.10 = **$1,000,000** |
| Messages sent | 1.5M x $0.001 = **$1,500** | 15M x $0.001 = **$15,000** | 150M x $0.001 = **$150,000** |
| Messages received | 1.5M x $0.0005 = **$750** | 15M x $0.0005 = **$7,500** | 150M x $0.0005 = **$75,000** |
| AI categorizations | 750K x $0.002 = **$1,500** | 7.5M x $0.002 = **$15,000** | 75M x $0.002 = **$150,000** |
| AI extractions | 150K x $0.01 = **$1,500** | 1.5M x $0.01 = **$15,000** | 15M x $0.01 = **$150,000** |
| Semantic searches | 300K x $0.005 = **$1,500** | 3M x $0.005 = **$15,000** | 30M x $0.005 = **$150,000** |
| Storage | 1 TB x $0.25 = **$250** | 10 TB x $0.25 = **$2,500** | 100 TB x $0.25 = **$25,000** |
| **Total Monthly Revenue** | **$17,000** | **$170,000** | **$1,700,000** |
| **Total Annual Revenue** | **$204,000** | **$2,040,000** | **$20,400,000** |

### Margin Analysis

| Metric | Startup | Growth | Full Scale |
|--------|---------|--------|-----------|
| Monthly Revenue | $17,000 | $170,000 | $1,700,000 |
| Monthly AWS Cost | $3,079 | $21,070 | $183,787 |
| **Gross Profit** | **$13,921** | **$148,930** | **$1,516,213** |
| **Gross Margin** | **81.9%** | **87.6%** | **89.2%** |
| Marketplace Fee (3%) | $510 | $5,100 | $51,000 |
| **Net Margin (after Marketplace)** | **78.9%** | **84.6%** | **86.2%** |

### Revenue Per Message (Blended)

| Scale | Revenue/Message | Cost/Message | Margin/Message |
|-------|----------------|--------------|----------------|
| Startup | $0.00567 | $0.00103 | $0.00464 (82%) |
| Growth | $0.00567 | $0.00070 | $0.00497 (88%) |
| Full Scale | $0.00567 | $0.00061 | $0.00506 (89%) |

---

## Cost Optimization Levers

### 1. DynamoDB: Provisioned Capacity + Reserved Capacity

**Current**: On-demand pricing ($1.25/M WCU, $0.25/M RCU)
**Optimized**: Provisioned capacity with auto-scaling + 1-year reserved capacity

| Scale | On-Demand Cost | Provisioned + Reserved | Savings |
|-------|---------------|----------------------|---------|
| Startup | $50 | $35 | 30% |
| Growth | $482 | $290 | 40% |
| Full Scale | $7,310 | $4,386 | 40% |

**How**: At Growth scale, traffic patterns become predictable. Reserve baseline capacity (70th percentile) with auto-scaling for bursts.

### 2. Lambda to ECS Migration for Hot Paths

**Current**: All compute on Lambda
**Optimized**: Migrate high-volume handlers (API handlers, inbound processor, send worker) to ECS Fargate

At Full Scale, the top 5 Lambda functions account for 80% of Lambda cost. Running these on always-on Fargate tasks is cheaper when invocation rate exceeds ~50/second sustained.

| Scale | Lambda Cost | After ECS Migration | Savings |
|-------|-------------|-------------------|---------|
| Startup | $67 | N/A (not worth it) | 0% |
| Growth | $725 | $500 | 31% |
| Full Scale | $6,397 | $3,200 | 50% |

### 3. S3 Lifecycle Policies

**Current**: All objects in S3 Standard
**Optimized**: Tiered storage with lifecycle rules

```
Day 0-30:    S3 Standard ($0.023/GB)    -- active emails
Day 31-90:   S3 Standard-IA ($0.0125/GB) -- recent archive
Day 91-365:  S3 Glacier Instant ($0.004/GB) -- cold archive
Day 366+:    S3 Glacier Deep ($0.00099/GB) -- regulatory hold
```

| Scale | Current Storage Cost | With Lifecycle | Savings |
|-------|---------------------|---------------|---------|
| Full Scale (100 TB cumulative) | $2,300/mo | $920/mo | 60% |

### 4. SES Enterprise Pricing

At high volume, SES pricing is negotiable. AWS offers enterprise SES pricing for customers sending >10M emails/month.

| Scale | Standard SES Cost | Enterprise (estimated) | Savings |
|-------|-------------------|----------------------|---------|
| Growth | $5,225 | $4,180 | 20% |
| Full Scale | $45,499 | $31,849 | 30% |

Requires: AWS Solutions Architect engagement, volume commitment, Enterprise Support plan.

### 5. Bedrock Optimization

Bedrock is the single largest cost driver at scale. Three optimization strategies:

**a) Batch Inference (50% discount)**

For non-real-time AI features (categorization can tolerate 5-minute delay), use Bedrock batch inference:
- Accumulate emails in SQS for 5 minutes
- Submit batch to Bedrock
- 50% discount on per-token pricing

| Scale | Real-time Cost | Batch (50% of volume) | Savings |
|-------|---------------|----------------------|---------|
| Growth | $8,313 | $6,235 | 25% |
| Full Scale | $83,123 | $62,342 | 25% |

**b) Prompt Caching (30% savings on repeated prompts)**

Bedrock prompt caching stores system prompts and few-shot examples. Our categorization prompt is identical for all emails within an org. Cache hit rate: ~80%.

| Scale | Without Caching | With Caching | Savings |
|-------|----------------|-------------|---------|
| Growth | $8,313 | $5,819 | 30% |
| Full Scale | $83,123 | $58,186 | 30% |

**c) Model Routing (Haiku for simple, Sonnet for complex)**

Route emails based on complexity. Short, simple emails (< 200 tokens, single intent) use Haiku for both categorization AND extraction. Complex emails (long, multi-intent, structured data) use Sonnet.

Estimated split: 70% Haiku, 30% Sonnet (vs. current 100% Sonnet for extraction).

| Scale | Current Extraction Cost | With Routing | Savings |
|-------|------------------------|-------------|---------|
| Growth | $6,750 | $3,375 | 50% |
| Full Scale | $67,500 | $33,750 | 50% |

**Combined Bedrock Optimization:**

| Scale | Current | Optimized (all three) | Savings |
|-------|---------|----------------------|---------|
| Growth | $8,313 | $3,500 | 58% |
| Full Scale | $83,123 | $35,000 | 58% |

### 6. Step Functions: Standard to Express

At Full Scale, replace Standard Workflows ($0.025/1K transitions) with Express Workflows ($0.00001667/GB-second) for the AI pipeline:

| Scale | Standard Cost | Express Cost | Savings |
|-------|-------------|-------------|---------|
| Full Scale | $18,750 | $300 | 98% |

### 7. ElastiCache Reserved Nodes

1-year reserved nodes with no upfront payment: 28% savings. 1-year all-upfront: 40% savings.

| Scale | On-Demand | Reserved (1yr, all upfront) | Savings |
|-------|-----------|---------------------------|---------|
| Growth | $756 | $454 | 40% |
| Full Scale | $2,308 | $1,385 | 40% |

### 8. Compute Savings Plans

3-year compute savings plans provide up to 52% discount on Lambda and Fargate:

| Scale | Current Compute | With Savings Plan (3yr) | Savings |
|-------|----------------|------------------------|---------|
| Full Scale (Lambda + Fargate) | $7,015 | $3,507 | 50% |

### Optimized Cost Summary (Full Scale)

| Service | Before Optimization | After Optimization | Savings |
|---------|-------------------|--------------------|---------|
| DynamoDB | $7,310 | $4,386 | -$2,924 |
| S3 | $5,088 | $3,088 | -$2,000 |
| SES | $45,499 | $31,849 | -$13,650 |
| Lambda + ECS | $7,015 | $3,507 | -$3,508 |
| API Gateway | $7,390 | $7,390 | $0 |
| ElastiCache | $2,308 | $1,385 | -$923 |
| OpenSearch | $3,528 | $3,528 | $0 |
| Kinesis | $469 | $469 | $0 |
| Bedrock | $83,123 | $35,000 | -$48,123 |
| Step Functions | $18,750 | $300 | -$18,450 |
| CloudWatch | $1,632 | $1,632 | $0 |
| Networking | $668 | $668 | $0 |
| Other | $1,007 | $1,007 | $0 |
| **Total** | **$183,787** | **$94,209** | **-$89,578 (49%)** |

**Optimized margins at Full Scale:**
- Monthly Revenue: $1,700,000
- Monthly Cost (optimized): $94,209
- Gross Margin: **94.5%** (up from 89.2%)

---

## Break-Even Analysis

### Assumptions for Break-Even

- Team cost: 4 engineers at $200K/year fully loaded = $800K/year = $66,667/month
- Office/tools/overhead: $5,000/month
- Total fixed cost: $71,667/month

### Break-Even Calculation

| Metric | Calculation |
|--------|-------------|
| Blended revenue per message | $0.00567 |
| Variable cost per message (startup scale) | $0.00103 |
| Contribution margin per message | $0.00464 |
| Fixed costs per month | $71,667 |
| **Break-even messages/month** | **71,667 / 0.00464 = 15,447,198** |
| **Break-even messages/day** | **~515,000** |
| **Break-even inboxes** (at 30 msgs/inbox/mo) | **~515,000** |
| **Break-even organizations** (at 10K inboxes avg) | **~52** |
| **Break-even MRR** | **$87,585** |

### Break-Even Timeline

| Month | Inboxes | Messages/Mo | MRR | AWS Cost | Fixed Cost | Profit/Loss |
|-------|---------|------------|-----|---------|-----------|-------------|
| 3 (end Phase 1) | 5,000 | 150,000 | $850 | $1,500 | $71,667 | -$72,317 |
| 6 (end Phase 2) | 25,000 | 750,000 | $4,250 | $1,800 | $71,667 | -$69,217 |
| 9 (end Phase 3) | 100,000 | 3,000,000 | $17,000 | $3,079 | $71,667 | -$57,746 |
| 12 (end Phase 4) | 300,000 | 9,000,000 | $51,000 | $7,500 | $71,667 | -$28,167 |
| 15 | 500,000 | 15,000,000 | $85,000 | $11,000 | $71,667 | +$2,333 |
| 18 | 800,000 | 24,000,000 | $136,000 | $16,000 | $71,667 | +$48,333 |
| 24 | 2,000,000 | 60,000,000 | $340,000 | $35,000 | $71,667 | +$233,333 |

**Break-even: Month 15** (approximately 500K inboxes, 15M messages/month, ~50 organizations).

### Cumulative Cash Required

Total cash burn before break-even (months 1-15): approximately **$750,000**.

This assumes:
- Self-funded or seed-stage capital
- 4-person engineering team
- No sales/marketing headcount (word-of-mouth, Marketplace listing)
- AWS credits from startup programs ($10K-$100K via AWS Activate) offset early costs

---

## AWS Enterprise Discount Program

### EDP Overview

At $100K+ annual AWS spend, AgentMail qualifies for the Enterprise Discount Program:

| Commitment Level | Discount | Annual Spend Required |
|-----------------|---------|----------------------|
| 1-year, $100K | 5-8% | $100,000 |
| 1-year, $250K | 8-12% | $250,000 |
| 3-year, $500K | 12-18% | $500,000 |
| 3-year, $1M+ | 15-22% | $1,000,000 |

### EDP Impact by Scale

| Scale | Annual Cost | EDP Discount (est.) | Annual Savings |
|-------|-----------|-------------------|---------------|
| Startup | $36,948 | Not eligible | $0 |
| Growth | $252,840 | 10% | $25,284 |
| Full Scale | $2,205,444 | 18% | $396,980 |

**Combined with service-level optimizations:**
- Full Scale optimized cost: $94,209/month = $1,130,508/year
- EDP 18% discount: $1,130,508 x 0.82 = $927,016/year
- **Total optimized + EDP annual cost: $927,016**
- **Revenue: $20,400,000**
- **Net margin: 95.5%**

### ISV Accelerate Program

As an AWS Marketplace ISV, AgentMail can apply for ISV Accelerate:
- AWS funds co-sell resources to help close enterprise deals
- Reduced Marketplace fee (3% instead of up to 5%)
- Access to AWS sales teams for joint customer engagement
- Requires: AWS Foundational Technical Review (FTR) passing score

---

## Marketplace Fee Impact

### Fee Structure

| Revenue Tier | Standard Fee | ISV Accelerate Fee |
|-------------|-------------|-------------------|
| First $1M | 5% | 3% |
| $1M - $10M | 4% | 3% |
| $10M+ | 3% | 3% |

### Fee Calculation by Scale

| Scale | Annual Revenue | Standard Fee | ISV Accelerate Fee |
|-------|---------------|-------------|-------------------|
| Startup | $204,000 | $10,200 (5%) | $6,120 (3%) |
| Growth | $2,040,000 | $89,600 (4.4% blended) | $61,200 (3%) |
| Full Scale | $20,400,000 | $672,000 (3.3% blended) | $612,000 (3%) |

### Net Revenue After Marketplace Fees

| Scale | Revenue | Fee (ISV Accel.) | Net Revenue | AWS Cost (optimized) | **Net Margin** |
|-------|---------|-----------------|-------------|---------------------|----------------|
| Startup | $204,000 | $6,120 | $197,880 | $36,948 | **78.9%** |
| Growth | $2,040,000 | $61,200 | $1,978,800 | $165,000 | **91.7%** |
| Full Scale | $20,400,000 | $612,000 | $19,788,000 | $927,016 | **95.3%** |

The Marketplace fee is a small percentage of revenue and is more than offset by the distribution benefits: access to enterprise procurement, EDP credit usage, and co-sell opportunities. The fee is the cost of the sales channel -- comparable to what a direct sales team would cost at much lower efficiency.
