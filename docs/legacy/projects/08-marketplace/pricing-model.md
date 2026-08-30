# Pricing Model

This document defines the **current pricing structure direction** for FreeMail.

Important: pricing details are intentionally not frozen yet. The goal of this document is to lock the **commercial shape**, not the final numbers.

---

## Commercial Model

FreeMail uses a two-channel model:

1. **Direct SaaS**
   - launch channel
   - supports `Free` and `Pro`
   - optimized for self-serve adoption

2. **AWS Marketplace**
   - upgrade path above Pro
   - optimized for higher mailbox/domain/throughput needs
   - optimized for procurement-led buying

---

## Direct SaaS Structure

### Free

Purpose:

- prove value quickly
- remove adoption friction
- differentiate on custom-domain support

Principles:

- more generous than current competitors
- includes custom domains
- excludes AI
- uses hard blocks instead of overage billing

### Pro

Purpose:

- provide the first self-serve paid upgrade
- unlock higher-value usage without building a large pricing matrix

Principles:

- more inboxes than Free
- more domains than Free
- higher throughput than Free
- AI becomes available only on paid plans

### Not in Scope Yet

Do not add additional self-serve SaaS tiers until usage justifies them.

The working commercial progression is:

`Free -> Pro -> AWS Marketplace`

---

## AWS Marketplace Structure

Marketplace begins where Pro stops.

### Marketplace Customer Profile

- more inboxes than Pro supports
- more custom domains than Pro supports
- more send/receive throughput than Pro supports
- heavier AI usage
- AWS procurement requirements

### Marketplace Tier Philosophy

Public tier names are still provisional, but the structure should be:

- **Growth**: first step above Pro
- **Scale**: materially above Growth
- **Enterprise**: negotiated private offers

### What Marketplace Adds

- higher mailbox/domain/throughput ceilings
- contract-backed AI usage
- AWS billing and procurement
- private offers
- future enterprise controls

---

## AI Commercial Rule

AI is not a free-tier feature.

This applies to:

- semantic search
- AI categorization
- structured extraction
- any future Bedrock-backed mail intelligence feature

Reason:

- Bedrock and OpenSearch are the first meaningful marginal-cost components
- AI should only be unlocked once billing, quotas, and cost visibility exist

---

## Proposed Canonical Marketplace Metering Dimensions

These dimensions are the current proposed source of truth for Marketplace planning.

Do not publish them until there is a final review, because Marketplace dimensions are difficult to change later.

| Dimension Key | Description | Unit |
|---------------|-------------|------|
| `messages_sent` | outbound messages accepted for delivery | per message |
| `messages_received` | inbound messages processed and stored | per message |
| `inboxes_active` | active inbox inventory | per inbox-hour |
| `domains_active` | verified active custom domains | per domain-hour |
| `api_calls` | authenticated API calls | per 1,000 calls |
| `storage_gb` | stored bodies and attachments | per GB-hour |
| `webhooks_delivered` | successful webhook deliveries | per 1,000 deliveries |
| `ai_ops` | paid AI operations across search/categorize/extract | per operation |

### Why This Shape

- it captures the main scale drivers above Pro
- it gives domains explicit commercial weight
- it keeps AI generic while pricing details are still fluid
- it avoids prematurely splitting AI into multiple dimensions before demand is clear

---

## Proposed Entitlement Model

Marketplace contracts should include allowances for:

- active inboxes
- active domains
- monthly send volume
- monthly receive volume
- API volume
- AI operations

Customers above included levels can then be metered on the dimensions above.

---

## Migration Path

### When to Move a Customer from Pro to Marketplace

Trigger a Marketplace conversation when one or more are true:

- they repeatedly exceed Pro mailbox limits
- they repeatedly exceed Pro domain limits
- they need materially higher throughput
- their AI usage is large enough to justify a contract
- their procurement team asks for AWS billing

### Migration Expectations

- same org
- same inboxes
- same domains
- same API keys if feasible
- billing channel changes from Stripe to Marketplace
- quota and entitlement source changes

---

## Marketplace Free Trial Guidance

If FreeMail offers a Marketplace free trial later, the planning assumptions should be:

- keep the trial optional, not launch-critical
- stay within AWS-supported duration limits
- do not model the trial as automatically converting to paid
- use the trial only as an evaluation path for procurement-led buyers

The free SaaS product is the main evaluation path for most users.

---

## Open Pricing Items

These are intentionally deferred:

- exact Free quota levels
- exact Pro monthly price
- exact Pro included AI allowance
- whether Pro includes AI credits or separate AI usage charges
- exact Marketplace public prices
- whether `domains_active` remains a metered dimension or becomes contract-only

Those decisions should be made after:

- public beta usage
- free-tier cost data
- first signs of Pro conversion
- clearer evidence of Marketplace demand
