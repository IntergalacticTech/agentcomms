# Billing & Plans

FreeMail has four tiers (Free, Starter, Pro, Enterprise) plus a BYOC ("bring your own cloud") tier sold via AWS Marketplace. Billing for the hosted tiers is handled through Stripe. BYOC billing is handled through AWS Marketplace.

New signups get a **14-day Pro trial** automatically, no credit card required. After 14 days, accounts that have not upgraded downgrade to the Free tier.

## Plans

### Free

The Free tier is available to all accounts immediately after signup and exists to let you try the platform end-to-end.

| Resource | Limit |
|----------|-------|
| Inboxes | 1 |
| Messages per day | 50 |
| Custom domains | 0 (use platform domains instead) |
| API keys | 1 |
| Pods | 1 |
| Webhooks | 1 |
| Storage | 100 MB |
| Retention | 7 days |
| AI features | Disabled |

Free-tier inboxes must be created on a **platform domain** from the pool below; bringing your own domain requires a paid plan.

### Starter — $5/month

The cheapest real agent-email plan on the market. Designed for building real applications on your own domain.

| Resource | Limit |
|----------|-------|
| Inboxes | 5 |
| Messages per day | 500 |
| Custom domains | 1 |
| API keys | 5 |
| Pods | 2 |
| Webhooks | 3 |
| Storage | 1 GB |
| Retention | 30 days |
| AI calls/month | 100 included |
| Support | Email (best effort) |

### Pro — $25/month

Production agent fleets.

| Resource | Limit |
|----------|-------|
| Inboxes | 100 |
| Messages per day | 5,000 |
| Custom domains | 10 |
| API keys | 25 |
| Pods | 10 |
| Webhooks | 25 |
| Storage | 25 GB |
| Retention | 1 year |
| AI calls/month | 2,000 included, $0.01/call overage |
| Support | Email with 24h SLA |

A soft cap of 100,000 messages per month applies; additional messages are billed at $0.30 per 1,000.

### Enterprise — Custom

For scale, compliance, and procurement motion. Contact `sales@victorymail.dev` or find us on AWS Marketplace Private Offers.

- Unlimited everything
- SSO / SAML authentication
- SOC 2 report (on request)
- Dedicated IPs
- EU region availability
- Named customer success manager
- Contract-based SLA credits

### BYOC — from $99/month

Run the entire FreeMail stack inside **your own AWS account** for compliance, data residency, or sovereign-cloud use cases. Deployed via AWS Marketplace. Source code is not visible to the purchaser — you pull SHA-pinned Lambda container images from our public ECR and our CDK package wires them into your infrastructure.

| Tier | Price | Scope |
|---|---|---|
| BYOC Trial | Free, 30 days | Full Starter features via CloudFormation Quick Launch |
| BYOC Starter | $99/mo | 1M msgs/mo, unlimited inboxes, 1 domain, email support (48h) |
| BYOC Pro | $499/mo | Unlimited msgs, unlimited domains, priority support (24h) |
| BYOC Enterprise | From $2,500/mo | Dedicated Slack, quarterly reviews, named CSM, custom regions, EU sovereign |

You continue to pay AWS directly for the infrastructure you provision. See [BYOC Deployment Guide](./byoc.md).

## Platform Domains (Free Tier)

Free-tier users can pick from these platform domains when creating an inbox:

| Domain | Description |
|---|---|
| `victorymail.dev` | Default |
| `karmascale.net` | Alternate |
| `karmascale.org` | Alternate |

Email addresses are unique **per domain**, so `agent@victorymail.dev` and `agent@karmascale.net` are separate inboxes that may belong to different accounts.

Pass the `domain` parameter when creating an inbox:

```json
POST /v1/inboxes
{"display_name": "signup bot", "domain": "karmascale.net"}
```

## How to Upgrade

### Via API

Create a Stripe Checkout session for the tier you want:

```bash
curl -X POST https://api.victorymail.dev/v1/billing/checkout \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tier": "starter"}'
```

The response includes a `checkout_url`:

```json
{"checkout_url": "https://checkout.stripe.com/c/pay/..."}
```

After successful payment, your organization is upgraded immediately and quotas are raised.

### Via Console

Navigate to the Billing page at `https://console.victorymail.dev/billing` and pick a plan.

## Checking Your Current Plan

```bash
curl https://api.victorymail.dev/v1/billing/status \
  -H "x-api-key: am_live_YOUR_KEY"
```

Response:

```json
{
  "org_id": "01HXYZ...",
  "tier": "starter",
  "billing_status": "active",
  "stripe_customer_id": "cus_..."
}
```

### Via Organization Endpoint

```bash
curl https://api.victorymail.dev/v1/organizations/me \
  -H "x-api-key: am_live_YOUR_KEY"
```

```json
{
  "tier": "pro",
  "quotas": {
    "max_inboxes": 100,
    "max_messages_per_day": 5000,
    "max_api_keys": 25,
    "max_pods": 10,
    "max_domains": 10,
    "max_webhooks": 25
  },
  "usage": {
    "inboxes": 42,
    "api_keys": 3,
    "pods": 2,
    "domains": 1
  }
}
```

## Managing Your Subscription

Access the Stripe Billing Portal to update payment, view invoices, or cancel:

```bash
curl -X POST https://api.victorymail.dev/v1/billing/portal \
  -H "x-api-key: am_live_YOUR_KEY"
```

When a subscription is canceled:

- Your account downgrades at the end of the current billing period.
- Quotas are reduced to the new tier's limits.
- Existing resources above the new limits remain but you cannot create new ones until you are within limits.

## Quota Enforcement

When you attempt to create a resource that would exceed your quota, the API returns **HTTP 403** with error code `QUOTA_EXCEEDED`:

```json
{
  "error": {
    "code": "QUOTA_EXCEEDED",
    "message": "Inbox quota exceeded. Current: 1, max: 1. Upgrade to Starter for higher limits."
  }
}
```

### What Counts Toward Quotas

- **Inboxes** — active inboxes only (deleted inboxes do not count).
- **API keys** — active keys only (revoked keys do not count).
- **Pods** — all pods.
- **Custom domains** — all registered domains you brought (platform domains don't count).
- **Webhooks** — all webhooks (active and paused).
- **Messages per day** — enforced by the outbound worker and inbound rate limiter.

## Billing Status Values

| Status | Description |
|--------|-------------|
| `none` | No billing account (Free tier) |
| `trialing` | Pro trial, no card on file |
| `active` | Active subscription, payments current |
| `past_due` | Payment failed, subscription at risk |
| `canceled` | Subscription canceled, downgraded |

## Webhook Notifications

If you have a webhook subscribed to `subscription.updated`, you receive events when your billing status changes:

```json
{
  "event": "subscription.updated",
  "data": {
    "org_id": "01HXYZ...",
    "tier": "starter",
    "billing_status": "active"
  },
  "timestamp": "2026-04-13T15:30:00Z"
}
```
