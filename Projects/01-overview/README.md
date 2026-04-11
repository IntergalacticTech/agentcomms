# 01 - AgentMail Overview

## What Is AgentMail?

AgentMail is an API-first email platform purpose-built for AI agents. It provides a complete set of RESTful APIs that allow autonomous software systems to create email inboxes, send and receive messages, manage threads, process attachments, and perform AI-powered email analysis -- all without human intervention.

### The Problem

AI agents need email. They need to send onboarding sequences, receive customer replies, process invoices, handle support tickets, and communicate with external systems. But existing email infrastructure was built for humans:

- **Cost**: Traditional email providers (Google Workspace, Microsoft 365) charge $4-12 per inbox per month. An AI agent platform managing 100,000 agents would pay $400K-$1.2M/month just for email.
- **No Programmatic Creation**: Creating a mailbox on Google Workspace or Exchange requires admin console workflows, provisioning delays, and often manual approval. There is no "create inbox" API call that returns in milliseconds.
- **Automation-Hostile Rate Limits**: Gmail limits sending to 500 messages/day for consumer accounts and 2,000/day for Workspace. These limits exist to prevent spam from humans, but they cripple legitimate AI workflows.
- **OAuth Complexity**: Accessing email programmatically requires OAuth 2.0 flows designed for interactive human consent. AI agents cannot click "Allow" in a browser popup.
- **No AI-Native Features**: Traditional email has no built-in semantic search, no email categorization, no structured data extraction. AI agents must build these capabilities themselves.

### The Solution

AgentMail solves every one of these problems:

- **$0.10/inbox/month at scale** -- 40-120x cheaper than traditional providers
- **Instant programmatic inbox creation** -- one API call, sub-second response
- **10M messages/day capacity** -- no artificial rate limits for legitimate use
- **API key authentication** -- no OAuth flows, no browser popups, no consent screens
- **Built-in AI capabilities** -- semantic search, categorization, and data extraction powered by Amazon Bedrock

---

## Target Market

### Primary: AI Agent Platforms

Companies building platforms where AI agents operate autonomously and need email communication capabilities:

- **Autonomous AI agent frameworks** (AutoGPT, LangChain agents, CrewAI, etc.) that need agents to send/receive email as part of multi-step workflows
- **AI-powered customer service platforms** that deploy email-based support agents handling thousands of simultaneous conversations
- **AI email assistants** that manage inboxes on behalf of human users, triaging, drafting, and responding to messages
- **AI sales development platforms** that run personalized outbound email campaigns through individual agent inboxes
- **RPA/workflow automation platforms** that need email as a trigger or action in automated business processes

### Secondary: Developer Tools and SaaS

- **SaaS platforms** that provide per-customer email inboxes (e.g., helpdesk tools, CRM systems)
- **Testing and staging environments** that need disposable email inboxes for automated testing
- **Email-based API integrations** where legacy systems communicate via email and need programmatic processing

### Market Sizing

- AI agent market projected to reach $65B by 2028 (Gartner)
- Email infrastructure TAM: $8.5B (2025)
- Addressable segment (programmatic email for AI): estimated $500M-$2B by 2027
- Initial target: 100 customers at $1K-50K/month average = $1.2M-$60M ARR

---

## Competitive Landscape

### Direct Competitor: AgentMail.to

AgentMail.to is the product we are cloning and improving upon. It is the first mover in the "email for AI agents" space.

| Dimension | AgentMail.to | Our AgentMail (AWS) |
|-----------|-------------|---------------------|
| Infrastructure | Unknown (likely multi-cloud) | 100% AWS-native |
| Billing | Stripe direct | AWS Marketplace (enterprise procurement) |
| AI capabilities | Email categorization, extraction | Same + semantic search via OpenSearch |
| Scale ceiling | Unknown | Designed for 10M inboxes |
| Enterprise readiness | Limited | AWS Marketplace, IAM integration, SOC 2 path |
| Custom domains | Yes | Yes (Route 53 automated) |
| IMAP/SMTP | Yes | Yes (ECS Fargate) |

### Transactional Email Providers

| Provider | Strengths | Why We Differentiate |
|----------|-----------|---------------------|
| **Mailgun** | Reliable sending, good APIs | No inbox management, no receiving, no AI features, sending-only |
| **SendGrid** | Scale, deliverability tools | Same as Mailgun -- sending-only platform, no inbox concept |
| **Postmark** | Delivery speed, transactional focus | Sending-only, no inbox creation, no receiving APIs |
| **Amazon SES** | Low cost, high volume | Raw transport only -- no inbox abstraction, no storage, no AI |

**Key differentiation**: None of these provide the *inbox* abstraction. They send email. AgentMail creates, manages, and operates complete email inboxes with bidirectional communication and AI processing.

### Traditional Email Providers

| Provider | Strengths | Why We Differentiate |
|----------|-----------|---------------------|
| **Google Workspace** | Reliability, ecosystem | $7.20/user/month minimum, no programmatic creation, OAuth required |
| **Microsoft 365** | Enterprise adoption | $6/user/month minimum, complex Graph API, Azure AD required |
| **Zoho Mail** | Lower cost | Still $1/user/month, limited API, manual provisioning |

**Key differentiation**: 40-120x cost advantage, instant programmatic provisioning, API-key auth, no per-seat licensing.

---

## Product Capabilities

### Core Email Operations

1. **Programmatic Inbox Creation and Management**
   - Create inboxes via single API call (POST /inboxes)
   - Assign to pods for multi-tenant grouping
   - Configure display name, default from address
   - Enable/disable inboxes without deletion
   - Bulk creation support (up to 1,000 per batch request)

2. **Send Email**
   - Full MIME support (HTML, plain text, multipart)
   - DKIM signing with per-domain or platform keys
   - SPF and DMARC alignment
   - Attachment support (up to 25MB per message via S3 presigned URLs)
   - Scheduled sending (send_at parameter)
   - CC, BCC, Reply-To headers

3. **Receive Email**
   - Inbound email processing via SES receipt rules
   - Automatic threading by Message-ID/References/In-Reply-To headers
   - Attachment extraction and S3 storage
   - Real-time delivery via webhooks and WebSockets

4. **Threading**
   - Automatic thread detection using email headers
   - Thread listing with message count and last activity timestamp
   - Thread-level operations (archive, label, mute)

5. **Attachments**
   - Upload via presigned S3 URLs
   - Download via presigned S3 URLs (time-limited)
   - Virus scanning via Lambda (ClamAV layer)
   - Size limits enforced per organization tier
   - Content-type detection and validation

6. **Drafts**
   - Create, update, delete draft messages
   - Auto-save support
   - Convert draft to sent message

### Domain Management

7. **Custom Domains**
   - Verify domain ownership via DNS TXT records
   - Automated DKIM key generation and DNS record creation
   - SPF record guidance
   - DMARC policy configuration
   - MX record setup for inbound email routing
   - Domain health monitoring dashboard
   - Support for subdomains (e.g., agents.company.com)

### Organization and Multi-Tenancy

8. **Pods (Multi-Tenant Grouping)**
   - Group inboxes into isolated pods
   - Per-pod configuration (webhooks, domains, quotas)
   - Pod-level metrics and billing
   - Useful for: one pod per customer, per department, per AI agent team

### Real-Time Communication

9. **Webhooks**
   - Configure per-inbox or per-pod webhook URLs
   - Events: message.received, message.sent, message.bounced, message.opened, inbox.created, etc.
   - HMAC-SHA256 signature verification
   - Automatic retry with exponential backoff (up to 72 hours)
   - Webhook delivery logs and health status

10. **WebSockets**
    - Persistent connections for real-time message delivery
    - Per-inbox or per-pod subscription
    - Automatic reconnection support
    - Heartbeat/ping-pong for connection health

### AI-Powered Features

11. **Semantic Search**
    - Full-text search across all emails in an inbox or pod
    - Vector-based semantic search (find emails by meaning, not just keywords)
    - Powered by Amazon OpenSearch Serverless with vector engine
    - Embeddings generated by Amazon Bedrock (Titan Embeddings v2)
    - Filters: date range, sender, has_attachment, thread_id, labels

12. **AI Email Categorization**
    - Classify incoming emails into categories using LLM
    - Default categories: inquiry, notification, marketing, transactional, spam, urgent
    - Custom category definitions via prompt configuration
    - Per-inbox or per-pod category prompts
    - Powered by Amazon Bedrock (Claude 3.5 Haiku for cost-efficiency)

13. **Structured Data Extraction**
    - Extract structured JSON from email bodies
    - Define extraction schema per inbox or pod
    - Examples: extract invoice amounts, shipping tracking numbers, meeting times, contact information
    - Powered by Amazon Bedrock (Claude 3.5 Sonnet for accuracy)
    - Results stored alongside message metadata

### Access Control

14. **Allow/Block Lists**
    - Per-inbox sender allow lists (only accept email from these addresses/domains)
    - Per-inbox sender block lists (reject email from these addresses/domains)
    - Wildcard domain support (e.g., *.company.com)
    - Pod-level and organization-level lists that cascade

### Observability

15. **Usage Metrics**
    - Messages sent/received per hour, day, month
    - Inbox count over time
    - API call volume by endpoint
    - Bounce rate, complaint rate
    - AI feature usage (categorizations, extractions, searches)
    - Export via API or CloudWatch metrics

### Protocol Compatibility

16. **IMAP/SMTP Support**
    - IMAP server for reading email via traditional email clients
    - SMTP server for sending email via traditional email clients
    - Runs on ECS Fargate behind NLB
    - Protocol translation layer converts IMAP/SMTP to internal API calls
    - Enables backward compatibility with existing email tooling

---

## API Resource Model

```
Organization (top-level account)
  |
  +-- API Keys (authentication tokens)
  |
  +-- Domains (verified custom domains)
  |
  +-- Pods (multi-tenant grouping)
  |     |
  |     +-- Inboxes (email addresses)
  |     |     |
  |     |     +-- Messages (sent/received emails)
  |     |     +-- Threads (conversation threads)
  |     |     +-- Drafts (unsent messages)
  |     |     +-- Attachments (files)
  |     |     +-- Allow/Block Lists (access control)
  |     |
  |     +-- Webhooks (event delivery endpoints)
  |     +-- Metrics (usage data)
  |
  +-- Webhooks (org-level event delivery)
  +-- Metrics (org-level usage data)
  +-- Lists (org-level allow/block)
```

### Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/organizations` | Create organization |
| POST | `/api-keys` | Generate API key |
| POST | `/domains` | Add and verify custom domain |
| GET | `/domains/{id}/verify` | Check domain DNS verification status |
| POST | `/pods` | Create pod |
| POST | `/inboxes` | Create inbox |
| GET | `/inboxes` | List inboxes (filterable by pod) |
| POST | `/inboxes/{id}/messages` | Send message from inbox |
| GET | `/inboxes/{id}/messages` | List messages in inbox |
| GET | `/inboxes/{id}/threads` | List threads in inbox |
| GET | `/inboxes/{id}/threads/{thread_id}` | Get thread with messages |
| POST | `/inboxes/{id}/drafts` | Create draft |
| PUT | `/inboxes/{id}/drafts/{draft_id}` | Update draft |
| POST | `/inboxes/{id}/drafts/{draft_id}/send` | Send draft |
| GET | `/inboxes/{id}/attachments/{att_id}` | Get attachment download URL |
| POST | `/inboxes/{id}/search` | Semantic search within inbox |
| PUT | `/inboxes/{id}/categorization` | Configure AI categorization |
| PUT | `/inboxes/{id}/extraction` | Configure data extraction schema |
| POST | `/webhooks` | Register webhook |
| GET | `/metrics` | Get usage metrics |
| PUT | `/inboxes/{id}/lists/allow` | Update allow list |
| PUT | `/inboxes/{id}/lists/block` | Update block list |

---

## SDK Strategy

All SDKs are auto-generated from a single OpenAPI 3.1 specification to ensure consistency and reduce maintenance burden.

### Python SDK

- **Package**: `agentmail-python` (PyPI)
- **Generator**: OpenAPI Generator with Python template
- **Features**: Async support (asyncio), type hints, Pydantic models, automatic retries
- **Priority**: First SDK (Python dominates AI/ML ecosystem)

### Node.js SDK

- **Package**: `@agentmail/sdk` (npm)
- **Generator**: OpenAPI Generator with TypeScript template
- **Features**: TypeScript-first, ESM and CJS support, automatic retries, WebSocket client
- **Priority**: Second SDK (Node.js dominates web backend ecosystem)

### Go SDK

- **Package**: `github.com/agentmail/agentmail-go`
- **Generator**: OpenAPI Generator with Go template
- **Features**: Context-based cancellation, structured errors, connection pooling
- **Priority**: Third SDK (Go used in infrastructure and DevOps tooling)

### OpenAPI Spec

- Hosted at `api.agentmail.com/openapi.json`
- Versioned (v1, v2, etc.) with backward compatibility guarantees
- Includes request/response examples for every endpoint
- Used to generate SDKs, API documentation, and Postman collections

---

## Business Model

### Pricing Structure: Consumption-Based via AWS Marketplace

AgentMail is sold as a SaaS product through the AWS Marketplace using the **SaaS Contracts with Consumption** model. Customers commit to a base contract and pay for usage above that commitment.

### Pricing Dimensions

| Dimension | Unit | Estimated Price |
|-----------|------|----------------|
| Inboxes | Per inbox per month | $0.10 - $0.50 (volume-tiered) |
| Messages Sent | Per message | $0.0005 - $0.002 |
| Messages Received | Per message | $0.0003 - $0.001 |
| AI Categorizations | Per categorization | $0.001 - $0.005 |
| AI Extractions | Per extraction | $0.005 - $0.02 |
| Semantic Searches | Per search | $0.002 - $0.01 |
| Storage | Per GB/month | $0.10 - $0.50 |
| Custom Domains | Per domain/month | $1.00 - $5.00 |
| IMAP/SMTP Connections | Per connection-hour | $0.001 - $0.005 |

### Contract Tiers

| Tier | Monthly Commitment | Included | Overage Rate |
|------|-------------------|----------|-------------|
| **Starter** | $29/month | 5 inboxes, 1,000 emails | Standard rates |
| **Growth** | $99/month | 25 inboxes, 10,000 emails | 20% discount |
| **Scale** | $499/month | 100 inboxes, 100,000 emails | 40% discount |
| **Enterprise** | Custom | Custom | Negotiated |

### AWS Marketplace Integration

- **SaaS Contract**: Customer subscribes through AWS Marketplace, payment handled by AWS
- **Consumption Metering**: Usage reported hourly via AWS Marketplace Metering API
- **Entitlement Checks**: API validates customer entitlements before processing requests
- **Revenue Share**: AWS takes 3-5% of revenue (varies by program participation)
- **Enterprise Benefits**: Customers can use AWS committed spend (EDP) credits

### Target Unit Economics (at Full Scale)

| Metric | Target |
|--------|--------|
| Blended COGS per inbox/month | < $0.03 |
| Blended COGS per message | < $0.0002 |
| Gross margin (Starter tier) | 70% |
| Gross margin (Scale tier) | 75% |
| Gross margin (Enterprise tier) | 80% |
| AWS Marketplace fee | 3-5% |
| Net margin after Marketplace fee | 65-77% |
