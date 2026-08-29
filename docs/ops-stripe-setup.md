# Stripe Setup (Hosted Ops)

This doc is for operators of a hosted AgentComms service. Self-hosted Apache-2.0 deployments do not need Stripe billing.

## Products

Create products and recurring prices in Stripe for your hosted tiers. Example hosted tiers:

| Product name | Nickname |
|---|---|
| AgentComms Developer | `developer` |
| AgentComms Team | `team` |
| AgentComms Business | `business` |

Store Stripe price IDs in your hosted deployment's secret/config system.

## Webhook Endpoint

Register a Stripe webhook endpoint for your hosted API:

```text
https://api.agentcomms.dev/v1/billing/webhook
```

Events:

- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_failed`

Store the webhook signing secret securely and pass it only to the hosted billing handler.

## Deploy

Billing is not part of the core self-host contract. If your hosted deployment includes billing routes, wire the Stripe secret key, webhook secret, and price IDs through Secrets Manager or another secret store rather than committed CDK context.

## Verify

With a hosted org API key:

```bash
curl -sS -X POST https://api.agentcomms.dev/v1/billing/checkout \
  -H "Authorization: Bearer ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tier": "developer"}'
```

Expected: a Stripe Checkout URL for the hosted service.

## License

Hosted billing does not limit OSS rights. The repository remains Apache-2.0 for self-hosted, commercial, and hosted use.
