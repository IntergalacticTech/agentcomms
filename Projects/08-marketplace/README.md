# AWS Marketplace Integration

AWS Marketplace is a **post-Pro growth channel** for FreeMail. It is not the initial launch motion.

The product should launch as a free and Pro SaaS offering first, then use Marketplace for customers who:

- outgrow Pro mailbox counts
- outgrow Pro custom-domain counts
- need more throughput
- want heavier AI usage under contract
- require AWS-native procurement

---

## Current Role of Marketplace

Marketplace exists to solve three problems:

1. **Procurement**
   Enterprise buyers want to buy through AWS.

2. **Scaling beyond Pro**
   Once a customer has clearly grown past self-serve economics, Marketplace becomes the natural commercial upgrade path.

3. **Contract-backed higher-cost usage**
   AI and higher-volume traffic are easier to support under committed or negotiated Marketplace terms.

---

## Launch Order

The current build order is:

1. Free SaaS MVP
2. Public beta hardening
3. Pro billing and paid AI
4. Marketplace migration path
5. Public Marketplace listing

This order is deliberate. Marketplace should not block product launch.

---

## Sub-Documents

| Document | Description |
|----------|-------------|
| [Pricing Model](./pricing-model.md) | Current commercial structure, proposed metering dimensions, and trial strategy |
| [Metering Pipeline](./metering-pipeline.md) | Hourly metering architecture and current AWS identifier rules |
| [Customer Lifecycle](./customer-lifecycle.md) | Fulfillment, entitlement refresh, and SaaS-to-Marketplace migration planning |
| [Listing Setup](./listing-setup.md) | Listing mechanics, seller workflow, FTR, and private offers |

---

## Current Integration Decisions

### 1. Marketplace is not exclusive

FreeMail uses a dual-channel model:

- direct SaaS for free and Pro
- Marketplace for growth beyond Pro

### 2. Marketplace identifiers must follow current AWS guidance

For a new SaaS product, planning should treat these as first-class fields:

- `CustomerAWSAccountId`
- `LicenseArn`
- `ProductCode`

Retain `CustomerIdentifier` only as a compatibility/reference field where AWS still returns it.

### 3. Metering dimensions must be frozen only once

Do not publish a listing until the metering dimensions are finalized. They are effectively a contract boundary.

### 4. Free trials are optional and must not be modeled as auto-converting

If FreeMail offers a Marketplace free trial, it should be designed as a bounded evaluation path inside AWS limits, with explicit follow-up conversion to a paid offer.

### 5. Private offers should come before public scale assumptions

The first usable Marketplace motion is likely:

- private offers
- migration of specific Pro customers
- limited-visibility listing
- public listing later

---

## Architecture Overview

```
Existing FreeMail SaaS customer exceeds Pro limits
        |
        v
Team offers AWS Marketplace contract or private offer
        |
        v
Customer subscribes on AWS Marketplace
        |
        v
Fulfillment endpoint calls ResolveCustomer
        |
        v
Existing org is linked to Marketplace account and license
        |
        v
Usage metering begins hourly via BatchMeterUsage
        |
        v
Entitlements and quotas now come from Marketplace
```

---

## Success Criteria

Marketplace work is complete when:

- an existing Pro customer can migrate without losing data
- entitlements can be refreshed safely
- metering is auditable and retry-safe
- private offers can be fulfilled without custom operator workflows
