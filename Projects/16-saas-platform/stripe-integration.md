# Stripe Billing Integration

This document provides the complete Stripe integration design for AgentMail's direct SaaS billing channel. Stripe handles all payment processing, subscription management, invoicing, and PCI compliance for customers who sign up directly through the AgentMail website (as opposed to AWS Marketplace customers, whose billing flows through Marketplace Metering).

**Stripe is used for direct SaaS customers only.** AWS Marketplace customers have their own billing pipeline documented in [Section 08: Marketplace](../08-marketplace/README.md). The two billing channels share the same DynamoDB org records, same API, same infrastructure -- only the `billing_channel` field differs.

---

## Table of Contents

- [1. Stripe Account Setup](#1-stripe-account-setup)
- [2. Products and Prices](#2-products-and-prices)
- [3. Checkout Flow](#3-checkout-flow)
- [4. Customer Portal](#4-customer-portal)
- [5. Webhook Integration](#5-webhook-integration)
- [6. Metered Billing (Overage)](#6-metered-billing-overage)
- [7. Proration on Tier Changes](#7-proration-on-tier-changes)
- [8. Dunning and Failed Payments](#8-dunning-and-failed-payments)
- [9. Free-to-Paid Conversion Flow](#9-free-to-paid-conversion-flow)
- [10. Marketplace Migration](#10-marketplace-migration)
- [11. Revenue Reconciliation](#11-revenue-reconciliation)
- [12. PCI Compliance](#12-pci-compliance)

---

## 1. Stripe Account Setup

### Account Configuration

```
Stripe Account: AgentMail Inc.
Mode: Live (production)
Country: United States
Currency: USD (primary), EUR, GBP (enabled for future international)
Statement Descriptor: AGENTMAIL
Shortened Descriptor: AGNTMAIL

Settings:
- Automatic tax collection: Enabled (Stripe Tax)
- Tax ID collection: Enabled
- Promotion codes: Enabled
- Customer emails: Stripe sends receipts and invoices
- Branding: AgentMail logo, brand color #2563EB
```

### API Keys (Stored in AWS Secrets Manager)

```
Secret: agentmail/stripe/live
{
  "secret_key": "sk_live_...",
  "publishable_key": "pk_live_...",
  "webhook_signing_secret": "whsec_...",
  "restricted_key_metering": "rk_live_...",  // Only usage record creation permission
  "restricted_key_readonly": "rk_live_..."   // Only read permission for dashboards
}
```

**Why restricted keys:** The main secret key has full access. Lambda functions that only report usage records get a restricted key with only `write` permission on `subscription_items.usage_records`. This limits blast radius if a key is compromised.

### Stripe SDK Configuration

```python
# shared/stripe_config.py

import stripe
import boto3
import json

def get_stripe_client():
    """Initialize Stripe with credentials from Secrets Manager."""
    secrets = boto3.client('secretsmanager')
    response = secrets.get_secret_value(SecretId='agentmail/stripe/live')
    config = json.loads(response['SecretString'])
    
    stripe.api_key = config['secret_key']
    stripe.max_network_retries = 2
    stripe.api_version = '2025-12-18.acacia'  # Pin API version
    
    return stripe

# Always pin the Stripe API version to avoid breaking changes
# Update the version explicitly when we want to adopt new features
```

---

## 2. Products and Prices

### Product Catalog

Three Stripe Products (one per paid tier), plus metered price objects for overage:

```python
# scripts/setup_stripe_products.py
# Run once to create the product catalog in Stripe

import stripe

stripe.api_key = "sk_live_..."

# ─── Pro Tier ────────────────────────────────────────────

pro_product = stripe.Product.create(
    name="AgentMail Pro",
    description="25 inboxes, 10,000 emails/month, AI features, 3 custom domains",
    metadata={
        "agentmail_tier": "pro",
        "inboxes": "25",
        "emails_per_month": "10000"
    },
    default_price_data={
        "unit_amount": 2900,
        "currency": "usd",
        "recurring": {"interval": "month"}
    },
    images=["https://agentmail.to/assets/pro-badge.png"],
    tax_code="txcd_10103001"  # SaaS - business use
)

pro_monthly_price = stripe.Price.create(
    product=pro_product.id,
    nickname="Pro Monthly",
    unit_amount=2900,
    currency="usd",
    recurring={"interval": "month"},
    metadata={"agentmail_tier": "pro", "billing_interval": "monthly"},
    tax_behavior="exclusive"  # Tax added on top
)

pro_annual_price = stripe.Price.create(
    product=pro_product.id,
    nickname="Pro Annual",
    unit_amount=2320,  # $23.20/mo = $278.40/year (20% discount)
    currency="usd",
    recurring={"interval": "month", "interval_count": 12},
    metadata={"agentmail_tier": "pro", "billing_interval": "annual"},
    tax_behavior="exclusive"
)

# ─── Business Tier ───────────────────────────────────────

business_product = stripe.Product.create(
    name="AgentMail Business",
    description="100 inboxes, 50,000 emails/month, IMAP/SMTP, full AI, 10 domains",
    metadata={
        "agentmail_tier": "business",
        "inboxes": "100",
        "emails_per_month": "50000"
    },
    tax_code="txcd_10103001"
)

business_monthly_price = stripe.Price.create(
    product=business_product.id,
    nickname="Business Monthly",
    unit_amount=9900,
    currency="usd",
    recurring={"interval": "month"},
    metadata={"agentmail_tier": "business", "billing_interval": "monthly"},
    tax_behavior="exclusive"
)

business_annual_price = stripe.Price.create(
    product=business_product.id,
    nickname="Business Annual",
    unit_amount=7920,  # $79.20/mo = $950.40/year (20% discount)
    currency="usd",
    recurring={"interval": "month", "interval_count": 12},
    metadata={"agentmail_tier": "business", "billing_interval": "annual"},
    tax_behavior="exclusive"
)

# ─── Scale Tier ──────────────────────────────────────────

scale_product = stripe.Product.create(
    name="AgentMail Scale",
    description="500 inboxes, 200,000 emails/month, unlimited pods, priority support",
    metadata={
        "agentmail_tier": "scale",
        "inboxes": "500",
        "emails_per_month": "200000"
    },
    tax_code="txcd_10103001"
)

scale_monthly_price = stripe.Price.create(
    product=scale_product.id,
    nickname="Scale Monthly",
    unit_amount=29900,
    currency="usd",
    recurring={"interval": "month"},
    metadata={"agentmail_tier": "scale", "billing_interval": "monthly"},
    tax_behavior="exclusive"
)

scale_annual_price = stripe.Price.create(
    product=scale_product.id,
    nickname="Scale Annual",
    unit_amount=23920,  # $239.20/mo = $2,870.40/year (20% discount)
    currency="usd",
    recurring={"interval": "month", "interval_count": 12},
    metadata={"agentmail_tier": "scale", "billing_interval": "annual"},
    tax_behavior="exclusive"
)

# ─── Overage Metered Prices ─────────────────────────────
# These are attached to subscriptions as additional line items
# Usage is reported via Stripe Usage Records

email_overage_price = stripe.Price.create(
    product=pro_product.id,  # Can be linked to any product
    nickname="Email Overage (per email)",
    currency="usd",
    recurring={
        "interval": "month",
        "usage_type": "metered",
        "aggregate_usage": "sum"
    },
    unit_amount=5,  # $0.05 per email over quota
    metadata={"agentmail_dimension": "email_overage"},
    tax_behavior="exclusive"
)

search_overage_price = stripe.Price.create(
    product=pro_product.id,
    nickname="Semantic Search Overage (per query)",
    currency="usd",
    recurring={
        "interval": "month",
        "usage_type": "metered",
        "aggregate_usage": "sum"
    },
    unit_amount=2,  # $0.02 per search over quota
    metadata={"agentmail_dimension": "search_overage"},
    tax_behavior="exclusive"
)

categorization_overage_price = stripe.Price.create(
    product=pro_product.id,
    nickname="AI Categorization Overage (per categorization)",
    currency="usd",
    recurring={
        "interval": "month",
        "usage_type": "metered",
        "aggregate_usage": "sum"
    },
    unit_amount=1,  # $0.01 per categorization over quota
    metadata={"agentmail_dimension": "categorization_overage"},
    tax_behavior="exclusive"
)

extraction_overage_price = stripe.Price.create(
    product=pro_product.id,
    nickname="AI Extraction Overage (per extraction)",
    currency="usd",
    recurring={
        "interval": "month",
        "usage_type": "metered",
        "aggregate_usage": "sum"
    },
    unit_amount=3,  # $0.03 per extraction over quota
    metadata={"agentmail_dimension": "extraction_overage"},
    tax_behavior="exclusive"
)

# ─── Dedicated IP Add-on ────────────────────────────────

dedicated_ip_price = stripe.Price.create(
    product=scale_product.id,
    nickname="Dedicated IP (per IP/month)",
    unit_amount=2500,  # $25.00/month per dedicated IP
    currency="usd",
    recurring={"interval": "month"},
    metadata={"agentmail_addon": "dedicated_ip"},
    tax_behavior="exclusive"
)

# ─── Store all price IDs for reference ───────────────────
print(f"""
Price ID Reference:
  Pro Monthly:       {pro_monthly_price.id}
  Pro Annual:        {pro_annual_price.id}
  Business Monthly:  {business_monthly_price.id}
  Business Annual:   {business_annual_price.id}
  Scale Monthly:     {scale_monthly_price.id}
  Scale Annual:      {scale_annual_price.id}
  Email Overage:     {email_overage_price.id}
  Search Overage:    {search_overage_price.id}
  Categorize Overage:{categorization_overage_price.id}
  Extract Overage:   {extraction_overage_price.id}
  Dedicated IP:      {dedicated_ip_price.id}
""")
```

### Price ID Configuration

Store price IDs as environment variables or in SSM Parameter Store:

```json
{
  "/agentmail/stripe/prices": {
    "pro": {
      "monthly": "price_1N...",
      "annual": "price_1N..."
    },
    "business": {
      "monthly": "price_1N...",
      "annual": "price_1N..."
    },
    "scale": {
      "monthly": "price_1N...",
      "annual": "price_1N..."
    },
    "overage": {
      "email": "price_1N...",
      "search": "price_1N...",
      "categorization": "price_1N...",
      "extraction": "price_1N..."
    },
    "addons": {
      "dedicated_ip": "price_1N..."
    }
  }
}
```

---

## 3. Checkout Flow

### Architecture

```
Console (React SPA)
    │
    │ POST /v1/billing/checkout
    │ { tier: "pro", interval: "monthly" }
    │
    ▼
API Gateway → Lambda: create-checkout-session
    │
    │ 1. Get/create Stripe Customer
    │ 2. Create Checkout Session with line items
    │ 3. Return session URL
    │
    ▼
Console redirects to Stripe Checkout (hosted page)
    │
    │ Customer enters payment details
    │ (card number, billing address, tax ID)
    │
    ▼
Stripe processes payment
    │
    ├── Success → redirect to console success URL
    │              Stripe fires checkout.session.completed webhook
    │              Lambda upgrades org tier
    │
    └── Failure → Stripe shows error, customer retries
                   No webhook fired until successful
```

### Lambda: create-checkout-session

```python
# Lambda: create-checkout-session
# API: POST /v1/billing/checkout
# Auth: JWT (Cognito) -- must be logged into console

import json
import stripe
from shared.stripe_config import get_stripe_client
from shared.auth import get_org_from_jwt
from shared.prices import PRICE_MAP, OVERAGE_PRICES

stripe = get_stripe_client()

def handler(event, context):
    # Extract org from JWT
    org = get_org_from_jwt(event)
    org_id = org['org_id']
    
    body = json.loads(event['body'])
    tier = body['tier']           # "pro", "business", "scale"
    interval = body.get('interval', 'monthly')  # "monthly", "annual"
    
    # ── Validation ────────────────────────────────────
    
    if tier not in ('pro', 'business', 'scale'):
        return response(400, {"error": "Invalid tier. Must be pro, business, or scale."})
    
    if interval not in ('monthly', 'annual'):
        return response(400, {"error": "Invalid interval. Must be monthly or annual."})
    
    if org.get('billing_channel') == 'marketplace':
        return response(400, {
            "error": "This organization is billed through AWS Marketplace. "
                     "Contact support to change your plan."
        })
    
    if org.get('tier') == tier:
        return response(400, {
            "error": f"You are already on the {tier} tier. "
                     "Use the billing portal to manage your subscription."
        })
    
    # ── Get or create Stripe Customer ────────────────
    
    customer_id = org.get('stripe_customer_id')
    
    if not customer_id:
        customer = stripe.Customer.create(
            email=org['owner_email'],
            name=org.get('name', org['owner_email']),
            metadata={
                'agentmail_org_id': org_id
            }
        )
        customer_id = customer.id
        
        # Persist customer ID immediately
        update_org(org_id, stripe_customer_id=customer_id)
    
    # ── Build line items ─────────────────────────────
    
    base_price_id = PRICE_MAP[tier][interval]
    
    line_items = [
        {
            "price": base_price_id,
            "quantity": 1
        }
    ]
    
    # ── Create Checkout Session ──────────────────────
    
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode='subscription',
        
        line_items=line_items,
        
        # After success, add metered overage items to the subscription
        # (Stripe Checkout does not support metered items directly,
        #  so we add them in the checkout.session.completed webhook)
        
        success_url=(
            'https://console.agentmail.to/settings/billing'
            '?checkout=success'
            '&session_id={CHECKOUT_SESSION_ID}'
        ),
        cancel_url=(
            'https://console.agentmail.to/settings/billing'
            '?checkout=cancelled'
        ),
        
        # Subscription metadata
        subscription_data={
            'metadata': {
                'agentmail_org_id': org_id,
                'agentmail_tier': tier
            },
            'description': f'AgentMail {tier.title()} - {interval.title()}'
        },
        
        # Tax
        automatic_tax={'enabled': True},
        tax_id_collection={'enabled': True},
        
        # Promo codes
        allow_promotion_codes=True,
        
        # Billing address (needed for tax calculation)
        billing_address_collection='required',
        
        # Customer can update email
        customer_update={
            'address': 'auto',
            'name': 'auto'
        },
        
        # Metadata for webhook processing
        metadata={
            'agentmail_org_id': org_id,
            'agentmail_tier': tier,
            'agentmail_interval': interval
        },
        
        # Consent collection
        consent_collection={
            'terms_of_service': 'required'
        },
        
        # Expiration: 30 minutes
        expires_at=int(time.time()) + 1800
    )
    
    return response(200, {
        'checkout_url': session.url,
        'session_id': session.id,
        'expires_at': session.expires_at
    })
```

### After Checkout: Adding Metered Items

Stripe Checkout does not support metered line items directly. After checkout completes, we add the metered overage prices to the subscription:

```python
def add_metered_items_to_subscription(subscription_id, tier):
    """
    Add metered overage price items to a new subscription.
    Called from checkout.session.completed webhook handler.
    """
    if tier == 'free':
        return  # Free tier has no overage
    
    subscription = stripe.Subscription.retrieve(subscription_id)
    
    # Add each overage metered price as a subscription item
    for dimension, price_id in OVERAGE_PRICES.items():
        stripe.SubscriptionItem.create(
            subscription=subscription_id,
            price=price_id,
            metadata={
                'agentmail_dimension': dimension,
                'agentmail_type': 'overage'
            }
        )
    
    # Store the subscription item IDs for later usage reporting
    updated_sub = stripe.Subscription.retrieve(subscription_id, expand=['items'])
    
    metered_items = {}
    for item in updated_sub['items']['data']:
        if item['price']['recurring'].get('usage_type') == 'metered':
            dimension = item['price']['metadata'].get('agentmail_dimension')
            if dimension:
                metered_items[dimension] = item['id']
    
    # Cache metered item IDs on the org record for fast lookup
    org_id = subscription['metadata']['agentmail_org_id']
    update_org(org_id, stripe_metered_items=metered_items)
```

---

## 4. Customer Portal

### Portal Configuration

```python
# scripts/setup_stripe_portal.py
# Run once to create the Customer Portal configuration

portal_config = stripe.billing_portal.Configuration.create(
    business_profile={
        "headline": "Manage your AgentMail subscription",
        "privacy_policy_url": "https://agentmail.to/privacy",
        "terms_of_service_url": "https://agentmail.to/terms"
    },
    features={
        # Allow updating billing email and tax ID
        "customer_update": {
            "enabled": True,
            "allowed_updates": ["email", "tax_id", "address"]
        },
        
        # Show invoice history with download links
        "invoice_history": {
            "enabled": True
        },
        
        # Allow updating/adding payment methods
        "payment_method_update": {
            "enabled": True
        },
        
        # Allow subscription cancellation
        "subscription_cancel": {
            "enabled": True,
            "mode": "at_period_end",  # Cancel at end of billing period
            "cancellation_reason": {
                "enabled": True,
                "options": [
                    "too_expensive",
                    "missing_features",
                    "switched_service",
                    "unused",
                    "customer_service",
                    "too_complex",
                    "low_quality",
                    "other"
                ]
            },
            "proration_behavior": "none"
        },
        
        # Allow tier upgrades/downgrades
        "subscription_update": {
            "enabled": True,
            "default_allowed_updates": ["price", "promotion_code"],
            "proration_behavior": "always_invoice",  # Immediate charge for upgrades
            "products": [
                {
                    "product": "prod_pro_...",
                    "prices": ["price_pro_monthly_...", "price_pro_annual_..."]
                },
                {
                    "product": "prod_business_...",
                    "prices": ["price_business_monthly_...", "price_business_annual_..."]
                },
                {
                    "product": "prod_scale_...",
                    "prices": ["price_scale_monthly_...", "price_scale_annual_..."]
                }
            ]
        }
    },
    default_return_url="https://console.agentmail.to/settings/billing"
)

print(f"Portal Configuration ID: {portal_config.id}")
# Store this as STRIPE_PORTAL_CONFIG_ID
```

### Lambda: create-portal-session

```python
# Lambda: create-portal-session
# API: POST /v1/billing/portal
# Auth: JWT (Cognito)

def handler(event, context):
    org = get_org_from_jwt(event)
    
    if not org.get('stripe_customer_id'):
        return response(400, {
            "error": "No billing account found. Upgrade to a paid plan first.",
            "upgrade_url": "https://console.agentmail.to/settings/billing"
        })
    
    session = stripe.billing_portal.Session.create(
        customer=org['stripe_customer_id'],
        configuration=STRIPE_PORTAL_CONFIG_ID,
        return_url='https://console.agentmail.to/settings/billing',
        flow_data=None  # Use default portal flow
    )
    
    return response(200, {
        'portal_url': session.url
    })
```

### What Customers Can Do in the Portal

1. **View and download invoices** -- PDF invoices for every payment
2. **Update payment method** -- Add/remove credit cards
3. **Change plan** -- Upgrade or downgrade between Pro/Business/Scale
4. **Cancel subscription** -- With reason collection (feeds into churn analysis)
5. **Update billing email** -- Change where receipts are sent
6. **Add tax ID** -- For VAT/GST exemption

### What We Handle Server-Side (Not in Portal)

1. **Free-to-paid upgrade** -- Uses Checkout Session (portal requires existing subscription)
2. **Marketplace migration** -- Custom flow, not a Stripe operation
3. **Tier limit changes** -- Automatic via webhook handlers
4. **Overage billing** -- Automatic via metered usage records

---

## 5. Webhook Integration

### Webhook Endpoint Setup

```
Endpoint URL: https://api.agentmail.to/webhooks/stripe
Events to listen for:
  - checkout.session.completed
  - customer.subscription.created
  - customer.subscription.updated
  - customer.subscription.deleted
  - customer.subscription.paused
  - customer.subscription.resumed
  - invoice.paid
  - invoice.payment_failed
  - invoice.finalized
  - invoice.upcoming
  - customer.updated
  - payment_method.attached
  - payment_method.detached
```

### Webhook Security

```python
# The webhook endpoint is public (no API key or JWT required).
# Security is provided by Stripe's webhook signature verification.

# API Gateway configuration for the webhook endpoint:
{
    "path": "/webhooks/stripe",
    "method": "POST",
    "authorization": "NONE",           # No auth -- Stripe signs the payload
    "integration": "Lambda",
    "lambda": "agentmail-stripe-webhook-handler"
}

# The Lambda function verifies the Stripe-Signature header
# using the webhook signing secret before processing any event.
```

### Complete Webhook Handler

```python
# Lambda: stripe-webhook-handler
# Endpoint: POST /webhooks/stripe
# Auth: None (verified by Stripe signature)

import json
import time
import stripe
from shared.stripe_config import get_stripe_client
from shared.dynamodb import update_org, get_org, get_org_by_stripe_customer
from shared.cognito import update_cognito_user_tier
from shared.cache import invalidate_org_cache
from shared.email import send_template_email
from shared.events import emit_event
from shared.tiers import TIER_LIMITS, TIER_FEATURES, TIER_RETENTION

stripe = get_stripe_client()
WEBHOOK_SECRET = get_secret('agentmail/stripe/webhook-secret')


def handler(event, context):
    """Main webhook entry point."""
    payload = event['body']
    sig_header = event['headers'].get('Stripe-Signature', '')
    
    # ── Signature verification ───────────────────────
    try:
        stripe_event = stripe.Webhook.construct_event(
            payload, sig_header, WEBHOOK_SECRET
        )
    except ValueError:
        print("ERROR: Invalid payload")
        return {'statusCode': 400, 'body': 'Invalid payload'}
    except stripe.error.SignatureVerificationError:
        print("ERROR: Invalid signature")
        return {'statusCode': 400, 'body': 'Invalid signature'}
    
    event_type = stripe_event['type']
    event_data = stripe_event['data']['object']
    event_id = stripe_event['id']
    
    # ── Idempotency check ────────────────────────────
    # Stripe may retry webhook delivery. Deduplicate by event ID.
    if is_event_already_processed(event_id):
        print(f"Event {event_id} already processed, skipping")
        return {'statusCode': 200, 'body': 'Already processed'}
    
    # ── Route to handler ─────────────────────────────
    try:
        HANDLERS = {
            'checkout.session.completed': handle_checkout_completed,
            'customer.subscription.created': handle_subscription_created,
            'customer.subscription.updated': handle_subscription_updated,
            'customer.subscription.deleted': handle_subscription_deleted,
            'invoice.paid': handle_invoice_paid,
            'invoice.payment_failed': handle_invoice_payment_failed,
            'invoice.finalized': handle_invoice_finalized,
            'invoice.upcoming': handle_invoice_upcoming,
            'customer.updated': handle_customer_updated,
        }
        
        handler_fn = HANDLERS.get(event_type)
        if handler_fn:
            handler_fn(event_data, stripe_event)
        else:
            print(f"Unhandled event type: {event_type}")
        
        # Mark event as processed
        mark_event_processed(event_id)
        
    except Exception as e:
        print(f"ERROR processing {event_type}: {str(e)}")
        # Return 500 so Stripe retries
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}
    
    return {'statusCode': 200, 'body': 'OK'}


# ─── Handler Functions ────────────────────────────────────


def handle_checkout_completed(session, stripe_event):
    """
    Fired when a customer completes Stripe Checkout.
    This is the primary upgrade trigger for free-to-paid conversions.
    """
    org_id = session['metadata'].get('agentmail_org_id')
    tier = session['metadata'].get('agentmail_tier')
    subscription_id = session.get('subscription')
    customer_id = session.get('customer')
    
    if not org_id or not tier:
        print(f"WARNING: Checkout session missing metadata: {session['id']}")
        return
    
    org = get_org(org_id)
    previous_tier = org.get('tier', 'free')
    
    # 1. Update org record with new tier and billing info
    update_org(org_id,
        tier=tier,
        billing_channel='stripe',
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        stripe_subscription_status='active',
        limits=TIER_LIMITS[tier],
        features=TIER_FEATURES[tier],
        retention_days=TIER_RETENTION[tier],
        overage_policy='grace_then_block',
        overage_grace_percent=10,
        upgraded_at=now_iso8601()
    )
    
    # 2. Add metered overage items to the subscription
    add_metered_items_to_subscription(subscription_id, tier)
    
    # 3. Update Cognito user attributes
    update_cognito_user_tier(org_id, tier)
    
    # 4. Invalidate all caches
    invalidate_org_cache(org_id)
    
    # 5. Send upgrade confirmation email
    send_template_email(
        to=org['owner_email'],
        template='upgrade-confirmation',
        data={
            'tier': tier,
            'previous_tier': previous_tier,
            'features': TIER_FEATURES[tier],
            'new_limits': TIER_LIMITS[tier]
        }
    )
    
    # 6. Emit analytics event
    emit_event('billing.checkout_completed', {
        'org_id': org_id,
        'from_tier': previous_tier,
        'to_tier': tier,
        'subscription_id': subscription_id,
        'session_id': session['id']
    })
    
    print(f"Org {org_id} upgraded from {previous_tier} to {tier}")


def handle_subscription_created(subscription, stripe_event):
    """
    Fired when a new subscription is created.
    Usually this fires alongside checkout.session.completed,
    so we do minimal work here to avoid double-processing.
    """
    org_id = subscription['metadata'].get('agentmail_org_id')
    if not org_id:
        return
    
    # Ensure org has the subscription ID stored
    update_org(org_id,
        stripe_subscription_id=subscription['id'],
        stripe_subscription_status=subscription['status'],
        stripe_current_period_start=subscription['current_period_start'],
        stripe_current_period_end=subscription['current_period_end']
    )


def handle_subscription_updated(subscription, stripe_event):
    """
    Fired when a subscription is modified.
    Triggers include: tier change via portal, renewal, payment method update,
    cancellation scheduled, trial ending, etc.
    """
    org_id = subscription['metadata'].get('agentmail_org_id')
    if not org_id:
        return
    
    new_tier = subscription['metadata'].get('agentmail_tier')
    status = subscription['status']
    cancel_at_period_end = subscription.get('cancel_at_period_end', False)
    
    org = get_org(org_id)
    previous_tier = org.get('tier')
    
    # Update subscription status
    update_fields = {
        'stripe_subscription_status': status,
        'stripe_current_period_start': subscription['current_period_start'],
        'stripe_current_period_end': subscription['current_period_end']
    }
    
    if status == 'active' and new_tier and new_tier != previous_tier:
        # Tier change (upgrade or downgrade via portal)
        update_fields.update({
            'tier': new_tier,
            'limits': TIER_LIMITS[new_tier],
            'features': TIER_FEATURES[new_tier],
            'retention_days': TIER_RETENTION[new_tier]
        })
        
        update_cognito_user_tier(org_id, new_tier)
        
        emit_event('billing.tier_changed', {
            'org_id': org_id,
            'from_tier': previous_tier,
            'to_tier': new_tier,
            'source': 'stripe_portal'
        })
        
        print(f"Org {org_id} changed tier: {previous_tier} -> {new_tier}")
    
    if cancel_at_period_end:
        update_fields['cancel_at_period_end'] = True
        update_fields['cancel_effective_date'] = subscription['current_period_end']
        
        send_template_email(
            to=org['owner_email'],
            template='subscription-cancellation-scheduled',
            data={
                'effective_date': format_timestamp(subscription['current_period_end']),
                'tier': org.get('tier'),
                'reactivate_url': 'https://console.agentmail.to/settings/billing'
            }
        )
    
    if status == 'past_due':
        update_fields['billing_alert'] = 'payment_past_due'
        # Do NOT downgrade yet -- Stripe is retrying payment
    
    if status in ('canceled', 'unpaid'):
        # Subscription terminated
        downgrade_to_free(org_id, reason='subscription_ended')
    
    update_org(org_id, **update_fields)
    invalidate_org_cache(org_id)


def handle_subscription_deleted(subscription, stripe_event):
    """
    Fired when a subscription is fully cancelled (not just scheduled).
    This is the definitive downgrade trigger.
    """
    org_id = subscription['metadata'].get('agentmail_org_id')
    if not org_id:
        return
    
    cancellation_reason = subscription.get('cancellation_details', {}).get('reason', 'unknown')
    
    downgrade_to_free(org_id, reason=f'subscription_deleted:{cancellation_reason}')
    
    emit_event('billing.subscription_deleted', {
        'org_id': org_id,
        'subscription_id': subscription['id'],
        'reason': cancellation_reason
    })


def handle_invoice_paid(invoice, stripe_event):
    """
    Fired when an invoice is successfully paid.
    This is the monthly renewal success event.
    """
    customer_id = invoice['customer']
    org_id = resolve_org_from_customer(customer_id)
    if not org_id:
        return
    
    # Reset monthly usage counters on successful renewal
    if invoice.get('billing_reason') in ('subscription_cycle', 'subscription_create'):
        reset_monthly_usage(org_id)
    
    # Store invoice record
    store_invoice_record(org_id, {
        'invoice_id': invoice['id'],
        'invoice_number': invoice.get('number'),
        'amount_paid': invoice['amount_paid'],
        'amount_due': invoice['amount_due'],
        'currency': invoice['currency'],
        'status': 'paid',
        'billing_reason': invoice.get('billing_reason'),
        'period_start': invoice.get('period_start'),
        'period_end': invoice.get('period_end'),
        'pdf_url': invoice.get('invoice_pdf'),
        'hosted_invoice_url': invoice.get('hosted_invoice_url'),
        'paid_at': now_iso8601(),
        'line_items': extract_line_items(invoice)
    })
    
    # Clear any billing alerts
    update_org(org_id, billing_alert=None)
    invalidate_org_cache(org_id)
    
    print(f"Invoice {invoice['id']} paid for org {org_id}: "
          f"${invoice['amount_paid']/100:.2f}")


def handle_invoice_payment_failed(invoice, stripe_event):
    """
    Fired when a payment attempt fails.
    Stripe will retry based on its Smart Retries algorithm.
    """
    customer_id = invoice['customer']
    org_id = resolve_org_from_customer(customer_id)
    if not org_id:
        return
    
    org = get_org(org_id)
    attempt_count = invoice.get('attempt_count', 1)
    next_attempt = invoice.get('next_payment_attempt')
    
    # Template selection based on attempt count
    if attempt_count == 1:
        template = 'payment-failed-first'
        urgency = 'info'
        banner_color = 'yellow'
    elif attempt_count == 2:
        template = 'payment-failed-second'
        urgency = 'warning'
        banner_color = 'orange'
    else:
        template = 'payment-failed-final'
        urgency = 'critical'
        banner_color = 'red'
    
    send_template_email(
        to=org['owner_email'],
        template=template,
        data={
            'amount': invoice['amount_due'] / 100,
            'currency': invoice['currency'].upper(),
            'attempt_count': attempt_count,
            'next_attempt': format_timestamp(next_attempt) if next_attempt else 'none (final attempt)',
            'update_payment_url': 'https://console.agentmail.to/settings/billing',
            'invoice_url': invoice.get('hosted_invoice_url')
        }
    )
    
    update_org(org_id,
        billing_alert=f'payment_failed_attempt_{attempt_count}',
        billing_alert_color=banner_color
    )
    
    emit_event('billing.payment_failed', {
        'org_id': org_id,
        'attempt_count': attempt_count,
        'amount': invoice['amount_due'],
        'has_next_attempt': next_attempt is not None
    })


def handle_invoice_finalized(invoice, stripe_event):
    """
    Fired when an invoice is finalized (ready for payment).
    Good for record-keeping and pre-payment notifications.
    """
    customer_id = invoice['customer']
    org_id = resolve_org_from_customer(customer_id)
    if not org_id:
        return
    
    store_invoice_record(org_id, {
        'invoice_id': invoice['id'],
        'invoice_number': invoice.get('number'),
        'amount_due': invoice['amount_due'],
        'currency': invoice['currency'],
        'status': 'finalized',
        'billing_reason': invoice.get('billing_reason'),
        'pdf_url': invoice.get('invoice_pdf'),
        'hosted_invoice_url': invoice.get('hosted_invoice_url'),
        'finalized_at': now_iso8601(),
        'line_items': extract_line_items(invoice)
    })


def handle_invoice_upcoming(invoice, stripe_event):
    """
    Fired ~3 days before the next invoice is due.
    Use for pre-billing notifications and usage summaries.
    """
    customer_id = invoice['customer']
    org_id = resolve_org_from_customer(customer_id)
    if not org_id:
        return
    
    org = get_org(org_id)
    usage = get_current_usage(org_id)
    
    # Send usage summary email before next billing
    send_template_email(
        to=org['owner_email'],
        template='upcoming-invoice',
        data={
            'amount': invoice['amount_due'] / 100,
            'billing_date': format_timestamp(invoice.get('next_payment_attempt')),
            'tier': org['tier'],
            'usage_summary': {
                'emails': usage.get('emails_sent', 0) + usage.get('emails_received', 0),
                'email_limit': org['limits']['emails_per_month'],
                'inboxes': usage.get('inboxes_active', 0),
                'inbox_limit': org['limits']['inboxes'],
                'storage_mb': round(usage.get('storage_bytes', 0) / 1024 / 1024, 1),
                'storage_limit_mb': round(org['limits']['storage_bytes'] / 1024 / 1024, 1)
            }
        }
    )


def handle_customer_updated(customer, stripe_event):
    """
    Fired when customer info is updated (email, name, address).
    Sync changes back to our org record if relevant.
    """
    org_id = customer['metadata'].get('agentmail_org_id')
    if not org_id:
        return
    
    # Update billing email if changed
    if customer.get('email'):
        update_org(org_id, billing_email=customer['email'])


# ─── Helper Functions ────────────────────────────────────


def resolve_org_from_customer(stripe_customer_id):
    """Resolve a Stripe customer ID to an AgentMail org_id."""
    # Query GSI3 (Stripe Customer Index)
    result = dynamodb.query(
        TableName='agentmail-main',
        IndexName='GSI3-StripeCustomer',
        KeyConditionExpression='GSI3PK = :pk',
        ExpressionAttributeValues={
            ':pk': {'S': f'STRIPE#{stripe_customer_id}'}
        }
    )
    
    if result['Items']:
        return result['Items'][0]['org_id']['S']
    
    # Fallback: scan by stripe_customer_id (slower, for migration period)
    return None


def downgrade_to_free(org_id, reason='unknown'):
    """
    Downgrade an org to free tier.
    Called when subscription is cancelled or payment fails permanently.
    """
    org = get_org(org_id)
    previous_tier = org.get('tier', 'unknown')
    
    update_org(org_id,
        tier='free',
        billing_channel='none',
        limits=TIER_LIMITS['free'],
        features=TIER_FEATURES['free'],
        retention_days=30,
        overage_policy='hard_block',
        downgraded_at=now_iso8601(),
        downgrade_reason=reason,
        previous_tier=previous_tier,
        billing_alert=None,
        cancel_at_period_end=False
    )
    
    update_cognito_user_tier(org_id, 'free')
    invalidate_org_cache(org_id)
    
    # Schedule excess resource cleanup if org exceeds free limits
    inbox_count = count_inboxes(org_id)
    if inbox_count > 5:
        schedule_cleanup(org_id, excess_inboxes=inbox_count - 5, days=30)
    
    send_template_email(
        to=org['owner_email'],
        template='downgraded-to-free',
        data={
            'previous_tier': previous_tier,
            'reason': reason,
            'excess_inboxes': max(0, inbox_count - 5),
            'cleanup_date': (now() + timedelta(days=30)).isoformat(),
            'reactivate_url': 'https://console.agentmail.to/settings/billing'
        }
    )
    
    emit_event('billing.downgraded', {
        'org_id': org_id,
        'from_tier': previous_tier,
        'to_tier': 'free',
        'reason': reason
    })
    
    print(f"Org {org_id} downgraded to free (was {previous_tier}, reason: {reason})")


def is_event_already_processed(event_id):
    """Check if this Stripe event has been processed (idempotency)."""
    try:
        result = dynamodb.get_item(
            TableName='agentmail-main',
            Key={
                'PK': {'S': 'STRIPE_EVENT'},
                'SK': {'S': event_id}
            }
        )
        return 'Item' in result
    except Exception:
        return False


def mark_event_processed(event_id):
    """Mark a Stripe event as processed."""
    dynamodb.put_item(
        TableName='agentmail-main',
        Item={
            'PK': {'S': 'STRIPE_EVENT'},
            'SK': {'S': event_id},
            'processed_at': {'S': now_iso8601()},
            'ttl': {'N': str(int(time.time()) + 86400 * 30)}  # 30-day TTL
        }
    )
```

### Webhook Reliability

**Retry behavior:** Stripe retries failed webhook deliveries (non-2xx response) with exponential backoff for up to 3 days.

**Idempotency:** Every event is deduplicated by event ID in DynamoDB. The TTL ensures old event records are cleaned up after 30 days.

**Ordering:** Stripe does not guarantee webhook ordering. The handler must be idempotent -- processing the same event twice should produce the same result.

**Dead letter queue:** If the webhook Lambda fails persistently, the API Gateway integration has a DLQ (SQS) configured. An alarm fires if the DLQ depth exceeds 10 messages.

---

## 6. Metered Billing (Overage)

### How Overage Works

Paid tiers get a 10% grace window above their included quota. Usage within the grace window is billed as overage at per-unit rates. Beyond the grace window, the API returns 429.

```
Included quota: 10,000 emails (Pro)
Grace window:   10% = 1,000 additional emails
Total allowed:  11,000 emails before hard block

Usage:    0 ──────── 10,000 ────── 11,000
          |  included quota  | overage | BLOCKED
          |    (free)        | (billed)|
```

### Reporting Overage to Stripe

```python
# Lambda: report-stripe-overage
# Called from the feature gate when usage enters the grace window

import stripe
from shared.stripe_config import get_stripe_client
from shared.dynamodb import get_org

stripe = get_stripe_client()

OVERAGE_DIMENSIONS = {
    'emails_per_month': 'email_overage',
    'semantic_searches_per_month': 'search_overage',
    'ai_categorizations_per_month': 'categorization_overage',
    'ai_extractions_per_month': 'extraction_overage'
}


def report_overage(org_id, dimension, quantity=1):
    """
    Report overage usage to Stripe for metered billing.
    Called each time a request falls in the overage window.
    
    Args:
        org_id: Organization ID
        dimension: The quota dimension (e.g., 'emails_per_month')
        quantity: Number of units to report (usually 1)
    """
    org = get_org(org_id)
    
    # Only report for Stripe-billed orgs
    if org.get('billing_channel') != 'stripe':
        return
    
    # Only report for paid tiers
    if org.get('tier') == 'free':
        return
    
    # Get the Stripe subscription item ID for this dimension
    metered_items = org.get('stripe_metered_items', {})
    overage_key = OVERAGE_DIMENSIONS.get(dimension)
    
    if not overage_key:
        return
    
    subscription_item_id = metered_items.get(overage_key)
    if not subscription_item_id:
        print(f"WARNING: No metered item for {overage_key} on org {org_id}")
        return
    
    # Report usage to Stripe
    try:
        stripe.SubscriptionItem.create_usage_record(
            subscription_item_id,
            quantity=quantity,
            timestamp=int(time.time()),
            action='increment'
        )
    except stripe.error.InvalidRequestError as e:
        print(f"ERROR reporting overage for org {org_id}: {str(e)}")
        # If the subscription item doesn't exist (subscription cancelled),
        # this will fail. That's expected.
    
    # Also record in our local ledger for reconciliation
    record_local_overage(org_id, dimension, quantity)
```

### Overage Pricing Summary

| Dimension | Overage Rate | Example |
|-----------|-------------|---------|
| Emails (sent + received) | $0.05/email | Pro user sends 10,500 emails: 500 overage x $0.05 = $25.00 |
| Semantic search queries | $0.02/query | Business user runs 5,200 searches: 200 overage x $0.02 = $4.00 |
| AI categorizations | $0.01/categorization | Business user categorizes 20,500: 500 overage x $0.01 = $5.00 |
| AI extractions | $0.03/extraction | Pro user runs 520 extractions: 20 overage x $0.03 = $0.60 |

### Overage on the Invoice

The customer's monthly invoice shows:
```
AgentMail Pro (Monthly)                     $29.00
Email Overage (500 emails x $0.05)          $25.00
AI Extraction Overage (20 x $0.03)           $0.60
─────────────────────────────────────────────────────
Subtotal                                    $54.60
Tax (if applicable)                          $X.XX
Total                                       $XX.XX
```

---

## 7. Proration on Tier Changes

### Upgrade (Pro to Business)

When a customer upgrades mid-cycle, Stripe calculates proration automatically:

```
Scenario:
- Current plan: Pro ($29/month)
- Billing cycle: April 1 - April 30
- Upgrade date: April 15 (halfway through cycle)
- New plan: Business ($99/month)

Stripe calculation:
- Unused Pro time: 15 days x ($29/30) = $14.50 credit
- Remaining Business time: 15 days x ($99/30) = $49.50 charge
- Net charge: $49.50 - $14.50 = $35.00 (charged immediately)
- Next full month: $99.00 on May 1
```

**Implementation:** The Stripe Customer Portal and our `change-subscription-tier` Lambda both use `proration_behavior: 'always_invoice'`, which creates an immediate invoice for the proration difference.

### Downgrade (Business to Pro)

Downgrades take effect at the end of the current billing period:

```
Scenario:
- Current plan: Business ($99/month)
- Billing cycle: April 1 - April 30
- Downgrade requested: April 15
- New plan: Pro ($29/month)

What happens:
- Customer retains Business features until April 30
- No refund for current period (already paid)
- On May 1, subscription renews at Pro ($29/month)
- Tier limits and features change to Pro on May 1
```

**Implementation:** The `customer.subscription.updated` webhook detects the pending tier change and schedules the tier downgrade for the period end.

---

## 8. Dunning and Failed Payments

### Stripe Dunning Configuration

```
Smart Retries: Enabled (Stripe ML picks optimal retry times)
Retry schedule: 3 retries over 7 days
  - Retry 1: ~3 days after failure
  - Retry 2: ~3 days after retry 1
  - Retry 3: ~1 day after retry 2
After all retries fail: Mark subscription as unpaid
  → Triggers customer.subscription.updated (status: unpaid)
  → Then customer.subscription.deleted
  → Our webhook downgrades to free tier
```

### Customer Communication Timeline

| Day | Event | Email Template | Console Banner |
|-----|-------|---------------|----------------|
| 0 | Payment fails | `payment-failed-first`: "We couldn't process your payment. Please update your payment method." | Yellow: "Payment issue" |
| 3 | Retry 1 fails | `payment-failed-second`: "Second attempt failed. Your service may be interrupted." | Orange: "Payment failing" |
| 6 | Retry 2 fails | `payment-failed-final`: "Final attempt. Account will be downgraded in 24 hours." | Red: "Action required" |
| 7 | Retry 3 fails | `downgraded-to-free`: "Your account has been downgraded. Reactivate anytime." | Red: "Downgraded to Free" |
| 37 | Cleanup | `data-deletion-notice`: "Excess data has been deleted per free tier limits." | None |

### Reactivation Flow

A previously-paid customer who was downgraded can reactivate:

1. Customer logs into console, sees "Reactivate" button
2. Button creates a new Checkout Session for their previous tier
3. Customer enters updated payment method
4. On successful payment: org is immediately upgraded back to their tier
5. Usage counters reset for the new billing period
6. If within the 30-day cleanup window: all data is preserved
7. If after the 30-day cleanup: excess data is gone, but remaining data is intact

---

## 9. Free-to-Paid Conversion Flow

This is the most important revenue conversion in the platform. The flow must be frictionless.

### Trigger Points

The console prompts for upgrade in several places:

1. **Dashboard quota warning**: When any resource is at 80%+ of free tier limit
2. **Feature gate block**: When user tries to use an AI feature (403 response)
3. **Inbox creation limit**: When trying to create inbox #6
4. **Domain limit**: When trying to add domain #2
5. **API response headers**: `X-Quota-Warning` and `X-Upgrade-URL` headers in API responses

### Conversion Flow

```
User hits a limit or wants an AI feature
    │
    ▼
Console shows upgrade modal:
    ┌────────────────────────────────────────────────┐
    │     Upgrade to unlock more                      │
    │                                                  │
    │  You're on the Free tier.                       │
    │  Upgrade to Pro for:                             │
    │  ✓ 25 inboxes (you have 5)                      │
    │  ✓ 10,000 emails/month (you used 1,000)        │
    │  ✓ Semantic search                               │
    │  ✓ AI categorization                             │
    │  ✓ AI extraction                                 │
    │  ✓ 3 custom domains                              │
    │                                                  │
    │  [Upgrade to Pro - $29/month]                    │
    │  [Compare all plans]                             │
    │                                                  │
    │  Annual billing saves 20% ($23.20/month)        │
    └────────────────────────────────────────────────┘
    │
    ▼
User clicks "Upgrade to Pro"
    │
    ▼
POST /v1/billing/checkout { tier: "pro", interval: "monthly" }
    │
    ▼
Redirect to Stripe Checkout
    │
    ▼
User enters credit card
    │
    ▼
Payment succeeds → redirect to console
    │
    ▼
Webhook fires → org upgraded → features unlocked
    │
    ▼
Console shows success toast:
    "Welcome to Pro! Your new features are active."
```

### Conversion Tracking

```python
# Track conversion funnel in analytics

CONVERSION_EVENTS = [
    'upgrade_prompt_shown',       # User saw an upgrade prompt
    'upgrade_prompt_clicked',     # User clicked an upgrade CTA
    'checkout_session_created',   # Checkout page opened
    'checkout_completed',         # Payment successful
    'checkout_abandoned',         # Checkout page opened but not completed
]

def track_conversion_event(org_id, event_name, metadata=None):
    emit_event(f'conversion.{event_name}', {
        'org_id': org_id,
        'tier': get_org(org_id)['tier'],
        'timestamp': now_iso8601(),
        'trigger': metadata.get('trigger') if metadata else None,
        **(metadata or {})
    })
```

---

## 10. Marketplace Migration

### Cancelling Stripe on Migration

When an org migrates from Stripe billing to AWS Marketplace:

```python
def cancel_stripe_on_marketplace_migration(org_id, marketplace_customer_id):
    """
    Cancel the Stripe subscription when migrating to Marketplace.
    Called from the Marketplace migration handler.
    """
    org = get_org(org_id)
    
    if not org.get('stripe_subscription_id'):
        print(f"Org {org_id} has no Stripe subscription to cancel")
        return
    
    subscription_id = org['stripe_subscription_id']
    
    # Cancel at period end (customer has already paid for current period)
    stripe.Subscription.modify(
        subscription_id,
        cancel_at_period_end=True,
        metadata={
            'agentmail_cancellation_reason': 'marketplace_migration',
            'agentmail_marketplace_customer_id': marketplace_customer_id,
            'agentmail_migration_date': now_iso8601()
        }
    )
    
    # Update org: billing channel is now marketplace
    # But keep stripe_customer_id for reference (invoices, etc.)
    update_org(org_id,
        billing_channel='marketplace',
        marketplace_customer_id=marketplace_customer_id,
        stripe_subscription_status='cancelling_for_migration',
        stripe_migration_note=f'Migrated to Marketplace on {now_iso8601()}'
    )
    
    # Send confirmation
    send_template_email(
        to=org['owner_email'],
        template='marketplace-migration-billing',
        data={
            'stripe_end_date': format_timestamp(
                stripe.Subscription.retrieve(subscription_id)['current_period_end']
            ),
            'marketplace_customer_id': marketplace_customer_id
        }
    )
```

### Handling the Overlap Period

There may be a brief overlap where both Stripe and Marketplace billing are active:

```
Timeline:
Day 0: Marketplace offer accepted, migration initiated
Day 0: Stripe subscription set to cancel_at_period_end
Day 0: billing_channel changed to "marketplace"
Day 0-N: Marketplace metering begins
Day N: Stripe current period ends, subscription cancelled
Day N: customer.subscription.deleted webhook fires
       → Handler sees "marketplace_migration" reason
       → Does NOT downgrade to free (migration, not cancellation)
```

```python
def handle_subscription_deleted(subscription, stripe_event):
    """Modified handler that checks for marketplace migration."""
    org_id = subscription['metadata'].get('agentmail_org_id')
    cancellation_reason = subscription['metadata'].get('agentmail_cancellation_reason')
    
    if cancellation_reason == 'marketplace_migration':
        # This is expected -- Stripe subscription ending because org migrated
        # Do NOT downgrade to free
        update_org(org_id,
            stripe_subscription_id=None,
            stripe_subscription_status='cancelled_for_migration'
        )
        print(f"Org {org_id} Stripe subscription ended (marketplace migration)")
        return
    
    # Normal cancellation -- downgrade to free
    downgrade_to_free(org_id, reason='subscription_cancelled')
```

---

## 11. Revenue Reconciliation

### Monthly Reconciliation Process

```python
# Lambda: monthly-revenue-reconciliation
# EventBridge: runs on the 2nd of each month at 06:00 UTC

def handler(event, context):
    """
    Reconcile Stripe billing data against our internal records.
    Ensures every paid org has an active subscription and
    every subscription maps to a valid org.
    """
    reconciliation_report = {
        'period': previous_month(),
        'checked_at': now_iso8601(),
        'issues': []
    }
    
    # 1. Check all paid orgs have active Stripe subscriptions
    paid_orgs = query_orgs_by_billing_channel('stripe')
    for org in paid_orgs:
        if not org.get('stripe_subscription_id'):
            reconciliation_report['issues'].append({
                'type': 'missing_subscription',
                'org_id': org['org_id'],
                'tier': org['tier'],
                'severity': 'critical'
            })
            continue
        
        try:
            sub = stripe.Subscription.retrieve(org['stripe_subscription_id'])
            if sub['status'] not in ('active', 'trialing'):
                reconciliation_report['issues'].append({
                    'type': 'inactive_subscription',
                    'org_id': org['org_id'],
                    'subscription_id': org['stripe_subscription_id'],
                    'subscription_status': sub['status'],
                    'org_tier': org['tier'],
                    'severity': 'high'
                })
        except stripe.error.InvalidRequestError:
            reconciliation_report['issues'].append({
                'type': 'subscription_not_found',
                'org_id': org['org_id'],
                'subscription_id': org['stripe_subscription_id'],
                'severity': 'critical'
            })
    
    # 2. Check all active Stripe subscriptions map to valid orgs
    active_subs = stripe.Subscription.list(status='active', limit=100)
    for sub in active_subs.auto_paging_iter():
        org_id = sub['metadata'].get('agentmail_org_id')
        if not org_id:
            reconciliation_report['issues'].append({
                'type': 'orphaned_subscription',
                'subscription_id': sub['id'],
                'customer_id': sub['customer'],
                'severity': 'medium'
            })
            continue
        
        org = get_org(org_id)
        if not org:
            reconciliation_report['issues'].append({
                'type': 'subscription_org_not_found',
                'subscription_id': sub['id'],
                'org_id': org_id,
                'severity': 'critical'
            })
    
    # 3. Calculate revenue metrics
    revenue = calculate_monthly_revenue(previous_month())
    reconciliation_report['revenue'] = revenue
    
    # 4. Store report
    store_reconciliation_report(reconciliation_report)
    
    # 5. Alert on issues
    if reconciliation_report['issues']:
        critical_count = len([i for i in reconciliation_report['issues'] if i['severity'] == 'critical'])
        if critical_count > 0:
            send_alert('ops-critical', f'Revenue reconciliation: {critical_count} critical issues')
        else:
            send_alert('ops-warning', f'Revenue reconciliation: {len(reconciliation_report["issues"])} issues')
    
    return reconciliation_report


def calculate_monthly_revenue(month):
    """Calculate MRR and related metrics from Stripe."""
    invoices = stripe.Invoice.list(
        created={
            'gte': first_of_month_timestamp(month),
            'lt': first_of_month_timestamp(next_month(month))
        },
        status='paid',
        limit=100
    )
    
    total_revenue = 0
    base_revenue = 0
    overage_revenue = 0
    
    for invoice in invoices.auto_paging_iter():
        total_revenue += invoice['amount_paid']
        
        for line in invoice['lines']['data']:
            if line['price']['recurring'].get('usage_type') == 'metered':
                overage_revenue += line['amount']
            else:
                base_revenue += line['amount']
    
    return {
        'month': month,
        'total_revenue_cents': total_revenue,
        'base_revenue_cents': base_revenue,
        'overage_revenue_cents': overage_revenue,
        'total_revenue_usd': total_revenue / 100,
        'base_revenue_usd': base_revenue / 100,
        'overage_revenue_usd': overage_revenue / 100
    }
```

### Revenue Dashboard Metrics

```
Custom CloudWatch metrics emitted daily:

AgentMail/Revenue:
  - MRR (Monthly Recurring Revenue)
  - NewMRR (from new subscriptions this month)
  - ChurnedMRR (from cancelled subscriptions this month)
  - ExpansionMRR (from tier upgrades this month)
  - ContractionMRR (from tier downgrades this month)
  - OverageRevenue (from metered overage this month)
  - ARPU (Average Revenue Per User)
  - SubscriberCount (by tier)
  - ConversionRate (free to paid, trailing 30 days)
  - ChurnRate (trailing 30 days)
```

---

## 12. PCI Compliance

### Our PCI Posture

**AgentMail never handles, stores, or transmits raw credit card data.** All payment processing happens entirely within Stripe's PCI-compliant infrastructure.

```
Customer's browser
    │
    │ Card number entered into Stripe.js (iframe)
    │ or Stripe Checkout (hosted page)
    │
    ▼
Stripe's servers (PCI DSS Level 1)
    │
    │ Card tokenized, payment processed
    │ Only a token/customer ID returned to us
    │
    ▼
Our servers receive only:
    - Stripe Customer ID (cus_...)
    - Stripe Subscription ID (sub_...)
    - Payment status (succeeded/failed)
    - Invoice ID and amount
    - NEVER: card number, CVV, expiry date
```

### Compliance Checklist

| Requirement | How We Meet It |
|-------------|---------------|
| Card data never touches our servers | Stripe Checkout (hosted) or Stripe.js (client-side tokenization) |
| No card data in logs | We only log Stripe IDs (cus_, sub_, pi_), never card details |
| No card data in database | DynamoDB stores `stripe_customer_id`, never card numbers |
| TLS encryption | API Gateway enforces TLS 1.2+, Stripe requires HTTPS |
| Webhook signature verification | Every Stripe webhook is verified with HMAC-SHA256 |
| API key security | Stripe keys stored in AWS Secrets Manager, not in code or env vars |
| Restricted API keys | Lambda functions use minimum-privilege restricted keys |
| PCI SAQ-A eligible | Because we use Stripe Checkout (hosted page), we qualify for the simplest SAQ (Self-Assessment Questionnaire A) |

### What This Means

We do not need to undergo a PCI audit. By using Stripe Checkout (hosted page) for all payment collection, we qualify for **PCI SAQ-A**, which is a simple self-assessment that confirms we do not handle card data. Stripe's own PCI DSS Level 1 certification covers the actual payment processing.

If we later add inline card collection (Stripe Elements embedded in our page), we would need to upgrade to **PCI SAQ-A-EP**, which has more requirements around our page's security (CSP headers, script integrity, etc.). For now, using Stripe Checkout's hosted page keeps us at the simplest compliance level.
