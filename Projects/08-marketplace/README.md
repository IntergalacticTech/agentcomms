# AWS Marketplace Integration

AgentMail is distributed exclusively through the AWS Marketplace as a SaaS product using the **SaaS Contracts with Consumption** hybrid billing model. This approach combines committed contract revenue with pay-as-you-go consumption metering, enabling predictable base revenue while allowing customers to scale usage seamlessly. Selling through the Marketplace eliminates procurement friction for enterprise buyers -- customers purchase AgentMail using existing AWS accounts, consolidated billing, and committed spend (EDP) credits.

---

## Sub-Documents

| Document | Description |
|----------|-------------|
| [Listing Setup](./listing-setup.md) | Seller registration, product listing configuration, FTR requirements, ISV Accelerate program, and listing approval process |
| [Pricing Model](./pricing-model.md) | Metering dimensions, contract tiers, pay-as-you-go rates, free trial configuration, private offers, and CPPO |
| [Metering Pipeline](./metering-pipeline.md) | Usage event collection, hourly aggregation, BatchMeterUsage submission, error handling, DLQ, reconciliation, and complete Lambda code |
| [Customer Lifecycle](./customer-lifecycle.md) | Onboarding flow, ResolveCustomer integration, SNS notifications, entitlement checking, unsubscribe handling, and edge cases |

---

## Architecture Overview

```
Customer subscribes via AWS Marketplace
        |
        v
AWS Marketplace ──POST──> API Gateway (fulfillment URL)
        |                        |
        |                  Lambda: ResolveCustomer
        |                        |
        |                  Create Tenant + API Keys
        |                        |
        v                        v
SNS Topic ───> SQS Queue ───> Lambda: Lifecycle Handler
(subscribe, unsubscribe,        |
 entitlement changes)      Update tenant state
                                 |
                                 v
                           DynamoDB (tenant table)
                                 |
                                 v
API Gateway ──> Lambda ──> Usage Events ──> Kinesis
                                 |
                           EventBridge (hourly)
                                 |
                           Lambda: Aggregator
                                 |
                           DynamoDB (hourly aggregates)
                                 |
                           Lambda: MeterUsage
                                 |
                           BatchMeterUsage API
                                 |
                           AWS Marketplace Billing
```

---

## Key Integration Points

| AWS Service | Role | API/Action |
|-------------|------|------------|
| **AWS Marketplace Metering Service** | Report hourly usage per dimension per customer | `BatchMeterUsage`, `MeterUsage` |
| **AWS Marketplace Entitlement Service** | Check what a customer has paid for | `GetEntitlements` |
| **AWS Marketplace Catalog API** | Manage product listing programmatically | `StartChangeSet` |
| **Amazon SNS** | Receive customer lifecycle events | Subscribe to Marketplace SNS topic |
| **Amazon SQS** | Buffer SNS messages for durable processing | Queue subscribed to SNS topic |

---

## Key Design Decisions

1. **SaaS Contracts with Consumption over pure SaaS Subscriptions.** Pure subscriptions limit revenue to fixed tiers. The hybrid model captures base commitment revenue while metering overages, aligning cost with value delivered.

2. **Hourly batch metering over real-time per-request metering.** `BatchMeterUsage` accepts up to 25 records per call and requires UTC-hour-aligned timestamps. Batching reduces API calls and aligns with the Marketplace's hourly billing granularity.

3. **SQS queue for SNS lifecycle events, not direct Lambda invocation.** SNS-to-Lambda drops messages on Lambda errors. SNS-to-SQS-to-Lambda provides automatic retry, dead-letter queue support, and visibility timeout for exactly-once processing.

4. **Local ledger for metering reconciliation.** Every usage record submitted to `BatchMeterUsage` is also written to DynamoDB. This enables dispute resolution, audit trails, and detection of lost records (the 6-hour submission window means late records are permanently lost revenue).

5. **Entitlement caching with SNS-triggered refresh.** Calling `GetEntitlements` on every API request adds latency and risks throttling. A 15-minute cache with SNS-triggered immediate refresh balances freshness against performance.
