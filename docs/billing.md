# Billing & Plans

FreeMail offers a free tier for getting started and a Pro tier for production workloads. Billing is managed through Stripe.

## Plans

### Free Tier

The free tier is available to all accounts immediately after signup. No credit card required.

| Resource | Limit |
|----------|-------|
| Inboxes | 5 |
| Messages per day | 1,000 |
| API keys | 5 |
| Pods | 3 |
| Custom domains | 1 |
| Webhooks | 5 |

The free tier uses shared SES sending infrastructure.

### Pro Tier

The Pro tier is designed for production AI agent workloads.

| Resource | Limit |
|----------|-------|
| Inboxes | 1,000 |
| Messages per day | 50,000 |
| API keys | 50 |
| Pods | 50 |
| Custom domains | 10 |
| Webhooks | 50 |

## How to Upgrade

### Via API

Create a Stripe Checkout session:

```bash
curl -X POST https://api.victorymail.dev/v1/billing/checkout \
  -H "x-api-key: am_live_YOUR_KEY"
```

The response includes a `checkout_url`. Open this URL in a browser to complete payment:

```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/..."
}
```

After successful payment, your organization is immediately upgraded to Pro and quotas are increased.

### Via Console

Navigate to the Billing page in the developer console at `https://console.victorymail.dev/billing` and click "Upgrade to Pro".

## Checking Your Current Plan

### Via API

```bash
curl https://api.victorymail.dev/v1/billing/status \
  -H "x-api-key: am_live_YOUR_KEY"
```

Response:

```json
{
  "org_id": "01HXYZ...",
  "tier": "free",
  "billing_status": "none",
  "stripe_customer_id": null
}
```

### Via Organization Endpoint

The organization endpoint also shows your current tier and quotas:

```bash
curl https://api.victorymail.dev/v1/organizations/me \
  -H "x-api-key: am_live_YOUR_KEY"
```

Response includes:

```json
{
  "tier": "pro",
  "quotas": {
    "max_inboxes": 1000,
    "max_messages_per_day": 50000,
    "max_api_keys": 50,
    "max_pods": 50,
    "max_domains": 10,
    "max_webhooks": 50
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

### Billing Portal

Access the Stripe Billing Portal to update payment methods, view invoices, or cancel your subscription:

```bash
curl -X POST https://api.victorymail.dev/v1/billing/portal \
  -H "x-api-key: am_live_YOUR_KEY"
```

Response:

```json
{
  "portal_url": "https://billing.stripe.com/p/session/..."
}
```

Open the `portal_url` in a browser to manage your subscription.

### Cancellation

Cancel your subscription through the Stripe Billing Portal. When a subscription is canceled:

- Your account is downgraded to the free tier at the end of the current billing period.
- Quotas are reduced to free tier limits.
- Existing resources above the free tier limits remain but you cannot create new ones until you are within limits.

## Quota Enforcement

When you attempt to create a resource that would exceed your quota, the API returns a 400 error:

```json
{
  "error": {
    "code": "QUOTA_EXCEEDED",
    "message": "Inbox quota exceeded. Current: 5, max: 5. Upgrade to Pro for higher limits."
  }
}
```

### What Counts Toward Quotas

- **Inboxes** -- active inboxes only (deleted inboxes do not count)
- **Messages per day** -- rolling 24-hour window, both inbound and outbound
- **API keys** -- active keys only (revoked keys do not count)
- **Pods** -- all pods
- **Custom domains** -- all registered domains
- **Webhooks** -- all webhooks (active and paused)

## Billing Status Values

| Status | Description |
|--------|-------------|
| `none` | No billing account (free tier) |
| `active` | Active subscription, payments current |
| `past_due` | Payment failed, subscription at risk |
| `canceled` | Subscription canceled, downgraded to free |

## Webhook Notifications

If you have a webhook subscribed to `subscription.updated`, you will receive notifications when your billing status changes:

```json
{
  "event": "subscription.updated",
  "data": {
    "org_id": "01HXYZ...",
    "tier": "pro",
    "billing_status": "active"
  },
  "timestamp": "2025-01-15T10:30:00Z"
}
```
