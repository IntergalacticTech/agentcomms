# Legacy Project Planning Archive

This directory is historical. It preserves the original FreeMail and AgentMail planning corpus so old architecture, migration, cost, and go-to-market decisions remain auditable. It is not the current AgentComms implementation guide, and it intentionally contains old product names, old domains, old placeholder account IDs, and superseded assumptions.

Use the current AgentComms docs in [`docs/`](../..) for implementation work.

---

# FreeMail - Complete Project Documentation

## Executive Summary

FreeMail is a cloud-native API platform built on AWS that gives AI agents fully programmatic email capabilities. The product launches as a **free SaaS offering first**, with a generous developer experience and custom-domain support as the main wedge. The immediate goal is not to maximize feature breadth; it is to get real users sending and receiving mail quickly, then monetize the cost-heavy parts later.

The current plan is:

- **FreeMail** is the product name.
- `victorymail.dev` is the temporary deployment and testing domain.
- the initial go-to-market motion is **direct SaaS**, not Marketplace-first.
- the paid self-serve tier is **Pro**.
- **AI features are paid-only** because Bedrock and OpenSearch are the first major marginal-cost drivers.
- customers who outgrow Pro should move to **AWS Marketplace** for higher mailbox/domain/throughput needs and procurement-led buying.

The documentation in this repo covers architecture, implementation, cost analysis, security, and go-to-market planning. Some lower-level documents still use the legacy `AgentMail` name; the canonical product identity is now **FreeMail**.

---

## Documentation Directory

| # | Section | File | Description |
|---|---------|------|-------------|
| 01 | [Overview](./01-overview/README.md) | `01-overview/README.md` | Product vision, market analysis, competitive landscape, and complete feature inventory |
| 01a | [System Architecture](./01-overview/system-architecture.md) | `01-overview/system-architecture.md` | End-to-end architecture diagrams, data flows, and layer-by-layer system design |
| 01c | [Competitive Analysis](./01-overview/competitive-analysis.md) | `01-overview/competitive-analysis.md` | Full competitive landscape: AgentMail.to, Lumbox, adjacent competitors, feature matrix, pricing comparison |
| 01b | [AWS Services Inventory](./01-overview/aws-services-inventory.md) | `01-overview/aws-services-inventory.md` | Complete inventory of every AWS service used, with costs, config, and alternatives |
| 02 | [Email Transport](./02-email-transport/README.md) | `02-email-transport/` | SES configuration, DKIM/SPF/DMARC, inbound/outbound email processing, domain coexistence with Google Workspace/Microsoft 365 |
| 03 | [API Platform](./03-api-platform/README.md) | `03-api-platform/` | API Gateway configuration, Lambda functions, OpenAPI spec, rate limiting, error handling, pagination, idempotency |
| 04 | [Database](./04-database/README.md) | `04-database/` | DynamoDB table design, access patterns, GSI strategy, S3 storage |
| 05 | [Real-Time Events](./05-real-time-events/README.md) | `05-real-time-events/` | Kinesis streams, WebSocket API, webhook delivery, EventBridge scheduled tasks and operational events |
| 06 | [AI/ML](./06-ai-ml/README.md) | `06-ai-ml/` | Bedrock integration, OpenSearch Serverless, email categorization, semantic search |
| 07 | [IMAP/SMTP](./07-imap-smtp/README.md) | `07-imap-smtp/` | Legacy protocol support via ECS Fargate, NLB, protocol translation |
| 08 | [Marketplace](./08-marketplace/README.md) | `08-marketplace/` | AWS Marketplace listing, metering, entitlements, billing integration |
| 09 | [Multi-Tenancy](./09-multi-tenancy/README.md) | `09-multi-tenancy/` | Organization isolation, pod architecture, resource quotas, tenant provisioning/deprovisioning, GDPR data export |
| 10 | [Observability](./10-observability/README.md) | `10-observability/` | CloudWatch metrics, X-Ray tracing, alerting, dashboards, load testing, capacity planning |
| 11 | [CI/CD](./11-cicd/README.md) | `11-cicd/` | Deployment pipeline, infrastructure as code, canary deployments |
| 12 | [Cost Analysis](./12-cost-analysis/README.md) | `12-cost-analysis/` | Detailed cost modeling at every scale tier, margin analysis, optimization strategies |
| 13 | [Implementation Roadmap](./13-implementation-roadmap/README.md) | `13-implementation-roadmap/` | Phased delivery plan, milestones, team structure, timeline |
| 14 | [Security](./14-security/README.md) | `14-security/` | IAM policies, encryption, network security, compliance, threat model, disaster recovery, business continuity |
| 15 | [Lumbox-Inspired Features](./15-lumbox-features/README.md) | `15-lumbox-features/` | Competitive features: OTP extraction, long-poll, MCP server (43 tools, full design), prompt injection defense, bulk send |
| 16 | [SaaS Platform](./16-saas-platform/README.md) | `16-saas-platform/` | Direct SaaS product: user auth, free/paid tiers, Stripe billing, feature gating, domain onboarding, developer console, Marketplace migration |

---

## Quick Reference: Key AWS Services

| AWS Service | Role in AgentMail | Why This Service |
|-------------|-------------------|------------------|
| **Amazon SES** | Email send/receive transport | Purpose-built for high-volume email; handles DKIM signing, bounce processing, reputation management |
| **API Gateway (REST + WebSocket)** | API entry point and WebSocket connections | Managed API layer with throttling, auth, and WebSocket support; no servers to manage |
| **AWS Lambda** | Core compute for all API and event processing | Pay-per-invocation pricing perfect for bursty email workloads; scales to zero |
| **Amazon DynamoDB** | Primary database for all metadata | Single-digit ms latency at any scale; pay-per-request pricing aligns with consumption model |
| **Amazon S3** | Email body and attachment storage | Unlimited storage at $0.023/GB; lifecycle policies for cost optimization |
| **Amazon ElastiCache (Redis)** | Caching, rate limiting, WebSocket state | Sub-ms latency for hot data; pub/sub for real-time fan-out |
| **Amazon Kinesis Data Streams** | Event streaming backbone | Ordered event delivery with replay; connects inbound email to processing pipeline |
| **Amazon Bedrock** | AI categorization and data extraction | Managed LLM access; no model hosting overhead; pay-per-token |
| **Amazon OpenSearch Serverless** | Semantic email search | Vector search + full-text search in one service; serverless scaling |
| **Amazon Route 53** | DNS management for custom domains | Programmatic DNS; health checks; integrates with SES domain verification |
| **AWS Marketplace** | Billing and distribution | Direct enterprise sales channel; handles procurement, billing, and metering |
| **Amazon CloudWatch + X-Ray** | Monitoring and tracing | Native integration with all AWS services; distributed tracing across Lambda chains |

---

## Key Numbers

| Metric | Target |
|--------|--------|
| **Max Inboxes** | 10,000,000 |
| **Max Messages/Day** | 10,000,000 |
| **API Latency (p99)** | < 200ms |
| **Email Delivery Time** | < 5 seconds (outbound), < 3 seconds (inbound processing) |
| **Availability Target** | 99.95% |
| **Cost per Inbox/Month** (at scale) | < $0.10 |
| **Cost per Message** (at scale) | < $0.001 |
| **Gross Margin Target** | 70-80% |
| **Time to First Inbox** (API call) | < 500ms |
| **Free Tier Cost Ceiling** | $0.22/user/month |
| **Target Free-to-Paid Conversion** | 5% within 3 months |
| **Startup Tier AWS Spend** | ~$2,000/month (up to 100K inboxes) |
| **Growth Tier AWS Spend** | ~$15,000/month (up to 1M inboxes) |
| **Full Scale AWS Spend** | ~$80,000/month (10M inboxes, 10M msgs/day) |
