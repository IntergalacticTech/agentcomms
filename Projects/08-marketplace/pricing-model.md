# Pricing Model

This document defines the complete pricing architecture for AgentMail on the AWS Marketplace, including metering dimensions, contract tiers, pay-as-you-go rates, free trials, private offers, and critical constraints.

---

## Dual-Channel Pricing Strategy

AgentMail is available through two billing channels, each serving a different segment of the market. Both channels share the same infrastructure, API, and tenant isolation model.

### Direct SaaS (Stripe Billing)

Self-service sign-up at agentmail.dev. Users create an account, get an API key, and start building immediately.

| Tier | Price | Inboxes | Emails/Month | AI Features | Custom Domains |
|------|-------|---------|-------------|-------------|----------------|
| **Free** | $0 | 5 | 1,000 | None | 1 |
| **Pro** | $29/mo | 25 | 10,000 | Basic (categorization) | 3 |
| **Business** | $99/mo | 100 | 50,000 | Full (categorization + extraction + search) | 10 |
| **Scale** | $299/mo | 500 | 200,000 | Full + priority | 25 |

Free tier includes: MCP, REST API, webhooks, 30-day email retention. No AI features.

### AWS Marketplace (Marketplace Billing)

Enterprise procurement through AWS Marketplace. SaaS Contracts with Consumption model.

| Tier | Price | Inboxes | Emails/Month | AI Features | Custom Domains |
|------|-------|---------|-------------|-------------|----------------|
| **Starter** | $29/mo | 5 | 1,000 | Included | 1 |
| **Growth** | $99/mo | 25 | 10,000 | Included | 5 |
| **Scale** | $499/mo | 100 | 100,000 | Included | 20 |
| **Enterprise** | Custom | Negotiated | Negotiated | Full + dedicated | Unlimited |

Marketplace has a 14-day free trial (see Free Trial Configuration below) but no permanent free tier.

### Tier Alignment

The SaaS and Marketplace tiers are intentionally aligned to enable seamless migration:

- **Pro ($29) maps to Starter ($29)**: Same price point, similar base limits. Marketplace Starter includes AI features that Pro gets at a basic level.
- **Business ($99) maps to Growth ($99)**: Same price point. Growth includes slightly different allocations optimized for Marketplace consumption metering.
- **Scale ($299 SaaS / $499 Marketplace)**: Marketplace Scale is priced higher because it includes higher overage allowances, full AI access, and enterprise-grade SLA.

### Migration Path: SaaS to Marketplace

When a direct SaaS customer upgrades to AWS Marketplace:

1. Customer subscribes to a Marketplace tier via AWS
2. Our fulfillment flow detects the existing org (by email match or explicit link)
3. The org's `billing_channel` switches from `"stripe"` to `"marketplace"`
4. Stripe subscription is cancelled (prorated refund for remaining period)
5. All data, inboxes, pods, and API keys remain intact -- zero downtime migration
6. Entitlements and quotas update to reflect the Marketplace tier
7. Usage metering switches from Stripe Usage Records to `BatchMeterUsage`

### AI Feature Gating

AI features (semantic search, email categorization, data extraction) are gated by channel and tier:

| Channel / Tier | Categorization | Data Extraction | Semantic Search |
|----------------|---------------|-----------------|-----------------|
| SaaS Free | No | No | No |
| SaaS Pro | Yes (2,000/mo) | Yes (500/mo) | Yes (500/mo) |
| SaaS Business | Yes (20,000/mo) | Yes (5,000/mo) | Yes (5,000/mo) |
| SaaS Scale | Yes (200,000/mo) | Yes (50,000/mo) | Yes (50,000/mo) |
| Marketplace (all tiers) | Yes (per tier) | Yes (per tier) | Yes (per tier) |

---

## Metering Dimensions

AWS Marketplace supports up to **24 metering dimensions** per product. AWS recommends keeping dimensions to **8 or fewer** for clarity in billing. AgentMail uses exactly 8 dimensions:

| # | Dimension Key | Display Name | Unit | Description |
|---|--------------|-------------|------|-------------|
| 1 | `messages_sent` | Messages Sent | Per message | Outbound emails successfully accepted by SES |
| 2 | `messages_received` | Messages Received | Per message | Inbound emails processed and stored |
| 3 | `inboxes_active` | Active Inboxes | Per inbox-hour | Inboxes in `active` state, metered hourly |
| 4 | `api_calls` | API Calls | Per 1,000 calls | All authenticated API requests (batch of 1K) |
| 5 | `storage_gb` | Storage | Per GB-hour | S3 storage for email bodies + attachments, metered hourly |
| 6 | `webhooks_delivered` | Webhooks Delivered | Per 1,000 deliveries | Successful webhook delivery attempts (batch of 1K) |
| 7 | `ai_searches` | AI Searches | Per search | Semantic search queries via OpenSearch + Bedrock embeddings |
| 8 | `ai_categorizations` | AI Categorizations | Per categorization | Email categorization or data extraction via Bedrock |

### Dimension Key Rules

- Keys must be lowercase alphanumeric with underscores only
- Keys must be unique within the product
- Maximum 24 characters per key
- Keys are **immutable after publishing** -- see critical gotcha below

### CRITICAL GOTCHA: Immutable Dimensions After Publishing

> **Once a product is published to AWS Marketplace, you cannot add, remove, rename, or modify metering dimensions.** Changing dimensions requires creating an entirely new product listing, migrating all existing customers to the new listing, and deprecating the old one.

**Implications:**
- Design dimensions carefully before first publish
- Use generic names where possible (e.g., `ai_searches` rather than `opensearch_queries` -- the underlying technology may change)
- Err on the side of more dimensions rather than fewer (you can meter 0 for unused dimensions, but you cannot add new ones)
- Consider future features: if you might add video processing, reserve a dimension now or use a generic name like `ai_operations`

**Our mitigation strategy:**
- 8 dimensions covers all current features with room for AI expansion
- `ai_searches` and `ai_categorizations` are generic enough to cover future AI capabilities
- `api_calls` is a catch-all that can absorb new endpoint types
- If a genuinely new dimension is needed, we create a new product listing and migrate customers via private offers

---

## Contract Tiers

Customers subscribe to a contract tier that provides a base commitment with included usage. Usage above the commitment is billed at pay-as-you-go rates.

### Tier: Starter -- $29/month

| Dimension | Included | Overage Rate |
|-----------|----------|-------------|
| Messages Sent | 500/month | $0.002/message |
| Messages Received | 500/month | $0.001/message |
| Active Inboxes | 5 | $0.50/inbox/month |
| API Calls | 10,000/month | $0.50/1K calls |
| Storage | 1 GB | $0.25/GB/month |
| Webhooks Delivered | 5,000/month | $0.30/1K deliveries |
| AI Searches | 100/month | $0.01/search |
| AI Categorizations | 500/month | $0.005/categorization |

**Target customer**: Individual developer, early-stage startup, proof of concept.

### Tier: Growth -- $99/month

| Dimension | Included | Overage Rate |
|-----------|----------|-------------|
| Messages Sent | 5,000/month | $0.0015/message |
| Messages Received | 5,000/month | $0.0008/message |
| Active Inboxes | 25 | $0.40/inbox/month |
| API Calls | 50,000/month | $0.40/1K calls |
| Storage | 10 GB | $0.20/GB/month |
| Webhooks Delivered | 25,000/month | $0.25/1K deliveries |
| AI Searches | 1,000/month | $0.008/search |
| AI Categorizations | 5,000/month | $0.004/categorization |

**Target customer**: Growing startup with moderate agent fleet, mid-market SaaS integrating email.

### Tier: Scale -- $499/month

| Dimension | Included | Overage Rate |
|-----------|----------|-------------|
| Messages Sent | 50,000/month | $0.001/message |
| Messages Received | 50,000/month | $0.0005/message |
| Active Inboxes | 100 | $0.30/inbox/month |
| API Calls | 500,000/month | $0.30/1K calls |
| Storage | 100 GB | $0.15/GB/month |
| Webhooks Delivered | 100,000/month | $0.20/1K deliveries |
| AI Searches | 10,000/month | $0.006/search |
| AI Categorizations | 50,000/month | $0.003/categorization |

**Target customer**: Established AI platform, enterprise with large agent deployment, high-volume SaaS.

### Tier: Enterprise -- Custom Pricing

- Negotiated via **private offers** (see below)
- Typically $2,000-$50,000/month base commitment
- Volume discounts of 40-70% off standard overage rates
- Custom SLA guarantees (99.99% uptime, <100ms p99 latency)
- Dedicated support with named TAM
- Custom EULA amendments (DPA, BAA for HIPAA, custom indemnification)
- Multi-year contracts (2-3 years) with additional discounts

### Annual Contract Discounts

| Duration | Discount |
|----------|----------|
| Monthly | 0% (standard pricing) |
| 12 months | 10% off base commitment |
| 24 months | 15% off base commitment |
| 36 months | 20% off base commitment |

Annual contracts are paid upfront or in monthly installments (configured per offer). Overage charges are always billed monthly regardless of contract duration.

---

## Pay-As-You-Go Dimension Pricing

For customers who exceed their tier's included usage, overage is billed per dimension at the rates shown in each tier above. The following table shows the pricing range across tiers:

| Dimension | Unit | Starter Rate | Growth Rate | Scale Rate | Enterprise (typical) |
|-----------|------|-------------|-------------|------------|---------------------|
| Messages Sent | Per message | $0.002 | $0.0015 | $0.001 | $0.0005 |
| Messages Received | Per message | $0.001 | $0.0008 | $0.0005 | $0.0003 |
| Active Inboxes | Per inbox/month | $0.50 | $0.40 | $0.30 | $0.10-$0.20 |
| API Calls | Per 1K calls | $0.50 | $0.40 | $0.30 | $0.15-$0.25 |
| Storage | Per GB/month | $0.25 | $0.20 | $0.15 | $0.10 |
| Webhooks Delivered | Per 1K deliveries | $0.30 | $0.25 | $0.20 | $0.10-$0.15 |
| AI Searches | Per search | $0.01 | $0.008 | $0.006 | $0.003-$0.005 |
| AI Categorizations | Per categorization | $0.005 | $0.004 | $0.003 | $0.001-$0.002 |

### Overage Billing Mechanics

1. Usage is metered hourly via `BatchMeterUsage` (see [Metering Pipeline](./metering-pipeline.md))
2. AWS aggregates hourly metering records into monthly usage per dimension
3. At the end of each billing period, AWS subtracts the tier's included amount from total usage
4. Overage = max(0, total_usage - included_amount) for each dimension
5. Overage charge = overage_units * overage_rate_per_unit
6. Total bill = base_contract + sum(overage_charges_per_dimension)

---

## Free Trial Configuration

AWS Marketplace supports free trials for SaaS Contract products with the following constraints:

| Parameter | Value |
|-----------|-------|
| Maximum trial duration | **14 days** |
| Contract amount during trial | **$0** |
| Trial entitlements | Limited subset of paid tier |
| Conversion | Automatic conversion to paid tier unless customer cancels |
| Customer payment method | Required at signup (AWS billing) |

### AgentMail Free Trial Configuration

```json
{
  "trial_duration_days": 14,
  "trial_contract_amount": 0,
  "trial_entitlements": {
    "messages_sent": 100,
    "messages_received": 100,
    "inboxes_active": 2,
    "api_calls": 5000,
    "storage_gb": 0.5,
    "webhooks_delivered": 1000,
    "ai_searches": 50,
    "ai_categorizations": 100
  },
  "conversion_tier": "Starter",
  "conversion_notification_days_before": [7, 3, 1]
}
```

### Trial Flow

1. Customer clicks "Free Trial" on Marketplace listing
2. AWS creates a $0 contract with trial entitlements
3. Customer is redirected to fulfillment URL (same as paid flow)
4. AgentMail provisions tenant with trial-tier quotas
5. Usage is metered normally (but billed at $0 because within entitlements)
6. 7 days before trial end: email notification via SES
7. 3 days before: second notification
8. 1 day before: final notification with conversion details
9. Trial ends: AWS converts to Starter tier ($29/month) unless customer cancels
10. If customer cancels: `unsubscribe-pending` SNS notification triggers data retention flow

### Trial Abuse Prevention

- One free trial per AWS account (enforced by Marketplace)
- Rate limits reduced during trial (50% of Starter tier API throttle)
- No custom domain support during trial
- No IMAP/SMTP access during trial
- Trial usage does not generate overage charges (hard cap at entitlement limits)

---

## Private Offers

Private offers enable custom pricing for specific customers, bypassing the public listing's standard tiers.

### When to Use Private Offers

- Enterprise customers requiring custom terms ($2K+/month)
- Customers needing EULA amendments (DPA, BAA, custom SLAs)
- Customers with AWS EDP credits they want to apply
- Strategic early customers who need promotional pricing
- Customers migrating from a competing solution (competitive displacement deals)

### Creating a Private Offer

```
AMMP > Private Offers > Create Private Offer

Offer Details:
  Customer AWS Account ID: 123456789012
  Product: AgentMail
  Offer Name: "Acme Corp Enterprise - 12 Month"
  Offer Expiration: 30 days from creation

Pricing:
  Contract Duration: 12 months
  Payment Schedule: Monthly installments
  Base Commitment: $5,000/month ($60,000/year)

Entitlements:
  messages_sent: 500,000/month
  messages_received: 500,000/month
  inboxes_active: 1,000
  api_calls: 5,000,000/month
  storage_gb: 500
  webhooks_delivered: 500,000/month
  ai_searches: 50,000/month
  ai_categorizations: 250,000/month

Overage Rates (custom):
  messages_sent: $0.0005/message
  messages_received: $0.0003/message
  inboxes_active: $0.15/inbox/month
  api_calls: $0.20/1K calls
  storage_gb: $0.10/GB/month
  webhooks_delivered: $0.12/1K deliveries
  ai_searches: $0.004/search
  ai_categorizations: $0.002/categorization

EULA:
  [x] Standard Contract for AWS Marketplace
  [x] Custom Amendment: Data Processing Addendum v2.1
  [x] Custom Amendment: SLA Guarantee (99.99% uptime)

Flexible Payment Schedule:
  Month 1-3: $3,000/month (ramp-up period)
  Month 4-12: $5,667/month (back-loaded to hit $60K annual)
```

### Private Offer Approval

- Private offers do **not** require separate AWS approval
- They go live immediately after creation
- Customer receives an email with a link to accept the offer
- Offer expires after the configured expiration date (typically 30 days)
- Once accepted, the customer is billed according to the private offer terms

---

## Channel Partner Private Offers (CPPO)

CPPO enables AWS Marketplace Channel Partners (resellers, MSPs, consulting partners) to resell AgentMail to their end customers.

### How CPPO Works

1. **Channel Partner registers** as an AWS Marketplace Channel Partner
2. **We authorize** the Channel Partner to resell AgentMail (via AMMP)
3. **Channel Partner creates CPPO** with their markup added to our wholesale price
4. **End customer accepts** the CPPO and subscribes through the Channel Partner
5. **Billing flows**: End customer pays AWS, AWS pays Channel Partner (minus AWS fee), Channel Partner pays us (minus their margin)

### CPPO Pricing Structure

```
Our wholesale price to Channel Partner:  $99/month (Growth tier)
Channel Partner markup:                  +$31/month (30% margin)
End customer price:                      $130/month

AWS Marketplace fee (3%):                -$3.90 (from end customer price)
Channel Partner receives:                $126.10
Channel Partner pays us:                 $99.00
Channel Partner profit:                  $27.10/month
```

### CPPO Considerations

- Channel Partners can set their own end-customer pricing (above our wholesale minimum)
- We maintain control over the wholesale floor price
- Channel Partners handle L1 support; we provide L2/L3
- CPPOs support the same custom terms as direct private offers
- Revenue attribution: CPPO revenue counts toward our Marketplace revenue thresholds for APN tier advancement
