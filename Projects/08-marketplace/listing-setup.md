# Marketplace Listing Setup

This document covers every step required to list AgentMail on the AWS Marketplace, from seller registration through listing approval, ISV Accelerate enrollment, and the Foundational Technical Review.

---

## Seller Registration

### Step 1: Create an AWS Marketplace Seller Account

1. **Navigate** to the [AWS Marketplace Management Portal](https://aws.amazon.com/marketplace/management/) (AMMP).
2. **Sign in** with the AWS account that will own the listing. This should be the production AWS account (not a dev/sandbox account), because the seller account is permanently bound to this AWS account ID.
3. **Register as a seller** -- click "Register" and provide:
   - Legal entity name (must match tax documents exactly)
   - Business address
   - Primary contact (name, email, phone)
   - Technical contact for integration issues
   - Marketing contact for listing content

### Step 2: Bank and Tax Information

1. **Bank account for disbursements:**
   - US bank account required for US-based entities
   - International wire transfer details for non-US entities
   - AWS disburses revenue monthly, NET 30-60 days after the customer billing period closes
   - Minimum disbursement threshold: $100

2. **Tax information:**
   - **US entities**: Complete IRS Form W-9 (Request for Taxpayer Identification Number)
   - **Non-US entities**: Complete IRS Form W-8BEN or W-8BEN-E (Certificate of Foreign Status)
   - Tax interview completed through the AMMP portal (guided workflow)
   - AWS reports revenue to IRS via 1099-K for US sellers exceeding $20K/200 transactions

3. **Approval timeline**: 1-3 business days after submitting bank/tax info. AWS verifies bank account ownership and tax document validity.

### Step 3: Agree to Seller Terms

- Sign the AWS Marketplace Seller Terms and Conditions
- Accept the AWS Customer Agreement (if not already accepted)
- Review the Enhanced Data Sharing agreement (opt-in recommended -- provides customer contact info for direct support)

---

## Product Configuration

### Product Type: SaaS

AgentMail is listed as a **SaaS** product. The customer does not install anything in their AWS account. All infrastructure runs in our AWS account.

| Product Attribute | Value |
|-------------------|-------|
| Product type | SaaS |
| Deployment model | Vendor-hosted (our AWS account) |
| Billing model | SaaS Contracts with Consumption |
| Contract duration options | 1 month, 12 months, 24 months, 36 months |
| Auto-renewal | Enabled (customer can disable) |
| Refund policy | Prorated refund for annual contracts; no refund for monthly |

### Why SaaS Contracts with Consumption (Hybrid)

AWS Marketplace offers three SaaS billing models:

| Model | How It Works | Pros | Cons |
|-------|-------------|------|------|
| **SaaS Subscriptions** | Fixed monthly fee, no usage metering | Simple, predictable revenue | Cannot capture usage upside, customers overpay or underpay |
| **SaaS Contracts** | Customer commits to entitlements upfront (e.g., 1,000 inboxes) | Predictable revenue, supports annual/multi-year deals | No flexibility for bursty usage, customer must upgrade contract to use more |
| **SaaS Contracts with Consumption** | Base contract commitment + pay-as-you-go for usage above commitment | Predictable base + usage upside, aligns cost with value | More complex metering implementation |

**We chose SaaS Contracts with Consumption because:**

1. **Predictable base revenue** -- contract tiers (Starter, Growth, Scale) provide committed monthly revenue that supports financial planning.
2. **Usage upside capture** -- customers who exceed their tier's included usage pay per-unit overage rates. This aligns our revenue with the value we deliver.
3. **Enterprise flexibility** -- large customers can negotiate custom contracts (private offers) with specific entitlement levels and overage rates.
4. **EDP credit consumption** -- customers can apply their AWS Enterprise Discount Program credits to both the base contract and overage charges.
5. **Annual commitment incentives** -- annual contracts provide discounts (typically 10-20%) that reduce churn and improve revenue predictability.

---

## Listing Metadata

### Product Title
```
AgentMail - Programmatic Email Platform for AI Agents
```
Maximum 72 characters. Must not include "AWS" or "Amazon" unless part of an official program name.

### Short Description
```
API-first email infrastructure for AI agents. Create and manage millions of email 
inboxes programmatically. Built-in AI categorization, semantic search, and structured 
data extraction. 40-120x cheaper than traditional email providers.
```
Maximum 250 characters.

### Long Description

```
AgentMail is a cloud-native email platform designed for AI agents and automated 
systems that need programmatic email capabilities at scale.

WHAT IT DOES:
- Create email inboxes via API (sub-second provisioning, no human intervention)
- Send and receive email with full MIME support, DKIM signing, and threading
- AI-powered email categorization, semantic search, and structured data extraction
- Real-time delivery via webhooks and WebSockets
- Multi-tenant isolation with pods for grouping inboxes by customer/team/use-case
- IMAP/SMTP compatibility for legacy system integration

WHO IT'S FOR:
- AI agent platforms (AutoGPT, LangChain, CrewAI) needing email communication
- AI-powered customer service platforms deploying email-based support agents
- SaaS platforms providing per-customer email inboxes
- Email-based workflow automation and RPA systems

PRICING:
- Starter: $29/month (1,000 messages, 5 inboxes included)
- Growth: $99/month (10,000 messages, 25 inboxes included)
- Scale: $499/month (100,000 messages, 100 inboxes included)
- Enterprise: Custom pricing via private offer
- Pay-as-you-go overage for usage above tier commitments
- Marketplace trial optional; duration TBD within AWS Marketplace limits

TECHNICAL HIGHLIGHTS:
- 99.95% uptime SLA
- <200ms API response time (p99)
- <5 second email delivery
- 10M+ inbox capacity
- Full REST API with Python, Node.js, and Go SDKs
- SOC 2 Type II compliance (in progress)
```

### Product Highlights (up to 3 bullet points)

1. **Instant Programmatic Inbox Creation** -- Create and manage millions of email inboxes through a single API call with sub-second response times. No OAuth flows, no admin consoles, no per-seat licensing.

2. **Built-in AI Email Intelligence** -- Semantic search, automatic categorization, and structured data extraction powered by Amazon Bedrock. Your AI agents understand email content natively.

3. **40-120x Cheaper Than Traditional Email** -- Purpose-built for machine-scale operations at $0.10/inbox/month. Replaces Google Workspace ($7.20/user/month) and Microsoft 365 ($6/user/month) for automated use cases.

### Logo Requirements

- Format: PNG
- Dimensions: 120x120 pixels (minimum), 200x200 pixels (recommended)
- Background: transparent or white
- No AWS logos or trademarks in the product logo

### Support Information

| Field | Value |
|-------|-------|
| Support email | support@freemail.dev |
| Support URL | https://docs.freemail.dev/support |
| Documentation URL | https://docs.freemail.dev |
| Support tiers | Basic (email, <24h response), Premium (email + Slack, <4h response), Enterprise (dedicated TAM, <1h response) |

### EULA

- Use the **Standard Contract for AWS Marketplace (SCMP)** for standard listings
- SCMP is pre-approved by many enterprise procurement teams, reducing legal review cycles
- For private offers, attach custom EULA amendments (e.g., data processing addendums, SLA guarantees, custom indemnification)

---

## Revenue Share

| Revenue Band | AWS Fee |
|-------------|---------|
| All revenue (standard) | **3%** of billed amount |
| With ISV Accelerate (co-sell deals) | **3%** (reduced from legacy 5% tier) |
| First $1M (for qualifying startups) | 3% (no special reduction) |

AWS collects the fee before disbursement. If a customer pays $100/month, AWS disburses $97 to the seller.

**Important**: The 3% fee applies to the total billed amount, including both base contract charges and consumption overage charges.

---

## Listing Approval Process

### Step 1: Create the Listing in AMMP

1. Log in to the [AWS Marketplace Management Portal](https://aws.amazon.com/marketplace/management/)
2. Navigate to "Products" > "SaaS" > "Create product"
3. Fill in all metadata fields (title, description, highlights, logo, support)
4. Configure pricing dimensions (see [Pricing Model](./pricing-model.md))
5. Set up the fulfillment URL (HTTPS endpoint that receives POST with `x-amzn-marketplace-token`)
6. Configure the SNS topic for lifecycle events
7. Submit for review

### Step 2: Technical Validation

AWS verifies:
- Fulfillment URL is reachable and returns HTTP 200
- `ResolveCustomer` integration works correctly
- Metering records are being submitted (even if zero)
- SNS notifications are being processed
- Customer can complete the registration flow end-to-end

### Step 3: Content Review

AWS reviews:
- Product description accuracy (no misleading claims)
- Logo compliance (no AWS trademarks)
- Pricing clarity (all dimensions and rates clearly described)
- EULA completeness
- Support information validity

### Step 4: Approval Timeline

- **Standard review**: 3-7 business days
- **With FTR completion**: May be expedited to 2-3 business days
- **Common rejection reasons**: Broken fulfillment URL, missing metering, unclear pricing, AWS trademark in logo, claims about AWS partnership without formal agreement

### Limited Visibility Testing

Before making the listing public, request **limited visibility** (also called "limited listing"):
- Only accessible to specific AWS account IDs you whitelist
- Use for internal testing and beta customers
- Validates the entire purchase-to-usage flow without exposing the listing publicly
- Convert to public listing when ready by submitting a "go public" request (1-2 business days)

---

## ISV Accelerate Program

The [AWS ISV Accelerate Program](https://aws.amazon.com/partners/programs/isv-accelerate/) is a co-sell program that connects ISV partners with the AWS sales organization.

### Requirements

1. **Foundational Technical Review (FTR)** -- Pass the FTR (see below). This is the single most important prerequisite.
2. **Customer references** -- Provide at least 2 customer references (companies using AgentMail in production via AWS Marketplace).
3. **APN membership** -- Active membership in the AWS Partner Network at the Select tier or above.
4. **CRM integration** -- Integrate with AWS ACE (APN Customer Engagements) for opportunity sharing.

### Benefits

| Benefit | Description |
|---------|-------------|
| **AWS co-sell** | AWS sales reps actively sell AgentMail alongside AWS services. When a customer is evaluating AI agent infrastructure, AWS can recommend AgentMail. |
| **AWS Marketplace Featured** | Higher visibility in Marketplace search results and category pages |
| **Customer introductions** | AWS account teams introduce AgentMail to customers with relevant workloads |
| **Deal registration** | AWS field teams register joint opportunities in ACE, providing pipeline visibility |
| **Marketing support** | Co-branded case studies, webinar slots, re:Invent booth opportunities |
| **Technical support** | Access to ISV-specific Solution Architects for architecture reviews |

### Application Process

1. Complete FTR (see next section)
2. Submit ISV Accelerate application through APN portal
3. Provide 2 customer references with contact information
4. Describe go-to-market strategy and target customer profile
5. Review by AWS Partner team (2-4 weeks)
6. If approved, onboard to ACE CRM integration

---

## Foundational Technical Review (FTR)

The FTR is a technical validation conducted by AWS that verifies the product meets baseline architectural best practices. It is required for ISV Accelerate and recommended for any serious Marketplace listing.

### What AWS Evaluates

#### 1. IAM Best Practices

| Requirement | How AgentMail Meets It |
|-------------|----------------------|
| No long-term access keys | All compute uses IAM roles (Lambda execution roles, ECS task roles) |
| Least-privilege policies | Each Lambda function has a dedicated role with minimum required permissions |
| No wildcard (`*`) resource permissions | All IAM policies specify explicit resource ARNs |
| MFA on root account | Root account has hardware MFA enabled, root credentials locked in physical safe |
| Separate accounts for workloads | AWS Organizations with separate accounts for prod, staging, dev, billing |
| No IAM users for applications | All application authentication uses IAM roles assumed via STS |

#### 2. Logging and Monitoring

| Requirement | How AgentMail Meets It |
|-------------|----------------------|
| CloudTrail enabled in all regions | Organization-level CloudTrail with S3 log delivery and log file validation |
| CloudWatch Logs for all compute | Lambda, ECS, and API Gateway all log to CloudWatch Logs with 30-day retention |
| CloudWatch Alarms for critical metrics | Alarms for error rates > 1%, latency p99 > 500ms, DynamoDB throttling, SES bounce rate |
| Centralized logging | All logs shipped to a dedicated logging account via CloudWatch cross-account |
| X-Ray tracing | Active tracing enabled on API Gateway, Lambda, and AWS SDK calls |

#### 3. Encryption

| Requirement | How AgentMail Meets It |
|-------------|----------------------|
| Encryption at rest for all data stores | DynamoDB (AWS-owned keys), S3 (SSE-S3), Redis (at-rest encryption), OpenSearch (encryption enabled) |
| Encryption in transit | TLS 1.2+ enforced on all endpoints, HTTPS-only API, SMTPS/IMAPS |
| KMS for sensitive data | Webhook secrets encrypted with KMS, option for customer-managed keys on Enterprise tier |
| No plaintext secrets in code | All secrets in AWS Secrets Manager, referenced via environment variables pointing to Secrets Manager ARNs |

#### 4. Incident Response

| Requirement | How AgentMail Meets It |
|-------------|----------------------|
| Documented incident response plan | Runbook in operations wiki covering detection, triage, mitigation, communication, and post-mortem |
| Contact information current | PagerDuty on-call rotation with escalation to engineering leadership |
| Ability to isolate affected resources | CDK stacks are per-service; individual Lambda functions, DynamoDB tables, or SES configurations can be isolated |
| Post-incident review process | Blameless post-mortem template with mandatory "5 whys" analysis |

#### 5. Business Continuity

| Requirement | How AgentMail Meets It |
|-------------|----------------------|
| Automated backups | DynamoDB point-in-time recovery (PITR) enabled, S3 versioning enabled on all buckets |
| Multi-AZ deployment | Lambda (inherently multi-AZ), DynamoDB (inherently multi-AZ), Redis (multi-AZ replication), OpenSearch (multi-AZ) |
| RTO/RPO targets documented | RTO: 1 hour, RPO: 5 minutes (PITR granularity) |
| Disaster recovery plan | Cross-region S3 replication for email bodies; DynamoDB global tables for metadata (activated on Enterprise tier) |
| Infrastructure as Code | All infrastructure defined in AWS CDK (TypeScript), version-controlled in Git, deployed via CI/CD pipeline |

### FTR Process

1. **Self-assessment** -- Complete the AWS Well-Architected FTR checklist (available in APN portal)
2. **Submit evidence** -- Upload architecture diagrams, IAM policy samples, CloudTrail screenshots, backup configuration evidence
3. **Schedule review** -- AWS assigns a Partner Solutions Architect who conducts a 2-hour review call
4. **Remediation** -- Address any findings (typically 1-3 items). Most common: overly permissive IAM policies, missing CloudTrail in non-primary regions, no documented incident response plan
5. **Approval** -- PSA signs off. FTR is valid for 12 months, then requires renewal.

**Timeline**: 2-4 weeks from submission to approval (assumes no major remediations).

---

## APN Membership Considerations

The AWS Partner Network (APN) has multiple tiers:

| Tier | Annual Fee | Requirements | Benefits |
|------|-----------|--------------|----------|
| **Registered** | Free | Create APN account | Access to training, basic partner badge |
| **Select** | $2,500/year | 2 accredited individuals, 2 technical validated individuals, 2 customer references | Listed in partner directory, co-sell eligibility |
| **Advanced** | $2,500/year | FTR, 4 accredited, 4 validated, 6 references, $100K in Marketplace revenue | AWS Competency eligibility, more co-sell support |
| **Premier** | Invitation only | Significant revenue and customer base | Dedicated partner development manager, re:Invent keynote potential |

**Recommendation**: Start at **Select** tier ($2,500/year) to enable ISV Accelerate enrollment. Upgrade to **Advanced** after achieving $100K in Marketplace revenue and completing FTR, which unlocks AWS Competency badges (e.g., "Machine Learning Competency") that significantly improve listing visibility.
