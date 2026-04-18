# Stripe Setup (Ops)

This doc is **for operators**, not customers. It walks through creating Stripe products/prices and wiring them into the CDK deploy so `/billing/checkout` can issue real checkout sessions.

## Step 1: Create Stripe products and prices

In the Stripe Dashboard, create two products with recurring monthly prices:

| Product name | Price | Nickname | Notes |
|---|---|---|---|
| FreeMail Starter | $5.00 USD / month | `starter` | Used for `POST /billing/checkout {"tier":"starter"}` |
| FreeMail Pro | $25.00 USD / month | `pro` | Used for `POST /billing/checkout {"tier":"pro"}` |

Copy the **Price ID** (starts with `price_`) from each — you'll need it below.

## Step 2: Create a webhook endpoint

In Stripe Dashboard → Developers → Webhooks → Add endpoint:

- **Endpoint URL**: `https://api.victorymail.dev/v1/billing/webhook`
- **Events to send**:
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_failed`

After creating the endpoint, copy its **Signing Secret** (starts with `whsec_`). This verifies webhook authenticity.

## Step 3: Deploy with CDK context

The CDK `ApiStack` reads Stripe config from context values. Deploy with all four set:

```bash
cd cdk
npx cdk deploy VictoryMail-Api-dev \
  -c stripeSecretKey=sk_live_... \
  -c stripeWebhookSecret=whsec_... \
  -c stripePriceIdStarter=price_... \
  -c stripePriceIdPro=price_... \
  --require-approval never
```

Or persist them in `cdk/cdk.json` under the `context` key (don't commit secrets — use environment substitution or AWS Secrets Manager for production).

## Step 4: Verify end-to-end

With a real API key:

```bash
# Should return a live checkout URL (not NOT_CONFIGURED)
curl -X POST https://api.victorymail.dev/v1/billing/checkout \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tier": "starter"}'
```

Expected response:

```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/cs_live_...",
  "tier": "starter"
}
```

Paying a $5 Stripe test transaction and watching the webhook fire is the full loop.

## Future: move secrets to AWS Secrets Manager

CDK context is fine for dev deploys but should not hold production Stripe secrets long-term. When we ship, swap the `tryGetContext` calls in `cdk/lib/stacks/api-stack.ts` for `secretsmanager.Secret.fromSecretNameV2(...)` references and grant the billing Lambda `secretsmanager:GetSecretValue`. Rotate secrets with `stripe.CLI --rotate`.
