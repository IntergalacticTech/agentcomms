# Tenant Provisioning

This document covers the complete tenant lifecycle -- from initial sign-up through tier changes, account deletion, data export, and recovery. It includes the full provisioning flow for both SaaS (Stripe) and AWS Marketplace channels.

---

## Provisioning: SaaS Sign-Up (billing_channel = "stripe")

### Flow Overview

```
User signs up at agentmail.dev
    |
    v
Cognito CreateUser (email + password)
    |
    v
Email verification
    |
    v
First login triggers Post-Confirmation Lambda
    |
    v
Post-Confirmation Lambda:
    1. Generate org_id (ULID)
    2. Create Organization record in DynamoDB
    3. Create default pod ("Default")
    4. Generate initial API key (org-scoped)
    5. Create SES configuration set
    6. Initialize usage counters
    7. Publish "org.created" event
    |
    v
Return org_id + API key to frontend
    |
    v
User sees dashboard with API key (shown once)
```

### Post-Confirmation Lambda

```python
import json
import hashlib
import secrets
from datetime import datetime, timezone

import boto3
import ulid

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("agentmail-main")
ses = boto3.client("sesv2")
kinesis = boto3.client("kinesis")
redis_client = None  # Initialized from VPC Lambda environment


# --- Tier defaults ---

TIER_DEFAULTS = {
    "free": {
        "max_pods": 1,
        "max_inboxes_total": 5,
        "max_inboxes_per_pod": 5,
        "max_emails_per_month": 500,
        "max_emails_per_day": 50,
        "max_email_size_mb": 10,
        "max_attachment_size_mb": 10,
        "max_attachments_per_email": 10,
        "max_webhooks": 2,
        "max_websocket_connections": 1,
        "max_api_keys": 1,
        "max_custom_domains": 0,
        "max_api_rate_per_second": 10,
        "max_storage_mb": 100,
        "retention_days": 30,
        "ai_search_queries_per_month": 0,
        "ai_categorizations_per_month": 0,
        "ai_extractions_per_month": 0,
        "features": {
            "semantic_search": False,
            "categorization": False,
            "extraction": False,
            "imap_smtp": False,
            "pods": False,
            "custom_domains": False,
            "bulk_send": False,
            "long_poll": True,
            "otp_extraction": True,
            "mcp_server": False,
        },
    },
    # Pro, Business, Scale, Enterprise defined similarly...
}


def handler(event, context):
    """
    Cognito Post-Confirmation Lambda trigger.
    Called once after the user verifies their email and confirms their account.
    """
    # Only run on ConfirmSignUp trigger (not on admin-created users)
    if event.get("triggerSource") != "PostConfirmation_ConfirmSignUp":
        return event

    cognito_user_id = event["request"]["userAttributes"]["sub"]
    email = event["request"]["userAttributes"]["email"]
    name = event["request"]["userAttributes"].get("name", email.split("@")[0])

    try:
        result = provision_saas_tenant(
            cognito_user_id=cognito_user_id,
            email=email,
            name=name,
        )

        # Store org_id in Cognito custom attribute for future lookups
        cognito = boto3.client("cognito-idp")
        cognito.admin_update_user_attributes(
            UserPoolId=event["userPoolId"],
            Username=event["userName"],
            UserAttributes=[
                {"Name": "custom:org_id", "Value": result["org_id"]},
            ],
        )

    except Exception as e:
        # Log but don't fail the Cognito flow -- user can still log in
        # and we'll retry provisioning on first API call
        print(f"Provisioning failed for {email}: {e}")
        # Publish failure event for alerting
        publish_event("org.provisioning_failed", {
            "cognito_user_id": cognito_user_id,
            "email": email,
            "error": str(e),
        })

    return event


def provision_saas_tenant(cognito_user_id: str, email: str, name: str) -> dict:
    """
    Complete SaaS tenant provisioning.
    Returns org_id and the raw API key (shown to user once, never stored in plaintext).
    """
    now = datetime.now(timezone.utc).isoformat()
    org_id = f"org_{ulid.new().str}"
    tier = "free"

    # --- Step 1: Create Organization record ---

    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": "METADATA",
            "entity_type": "Organization",
            "org_id": org_id,
            "name": name,
            "email": email,
            "cognito_user_id": cognito_user_id,
            "billing_channel": "stripe",
            "stripe_customer_id": None,  # Created when user upgrades to paid tier
            "marketplace_customer_id": None,
            "tier": tier,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        ConditionExpression="attribute_not_exists(PK)",  # Idempotency guard
    )

    # --- Step 2: Create quota record with free tier defaults ---

    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": "QUOTAS",
            "entity_type": "Quotas",
            "org_id": org_id,
            "tier": tier,
            "quotas": TIER_DEFAULTS[tier],
            "overrides": {},
            "created_at": now,
        },
    )

    # --- Step 3: Create default pod ---

    default_pod_id = f"pod_{ulid.new().str}"

    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": f"POD#{default_pod_id}",
            "entity_type": "Pod",
            "pod_id": default_pod_id,
            "org_id": org_id,
            "name": "Default",
            "status": "active",
            "config": {},
            "quotas": {},
            "inbox_count": 0,
            "is_default": True,
            "created_at": now,
            "updated_at": now,
            "GSI1PK": f"ORG#{org_id}#PODS",
            "GSI1SK": now,
        },
    )

    # --- Step 4: Generate initial API key ---

    raw_key = f"am_{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": f"APIKEY#{key_hash}",
            "entity_type": "ApiKey",
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "org_id": org_id,
            "pod_id": None,  # Org-scoped
            "name": "Default API Key",
            "scopes": ["*"],
            "status": "active",
            "created_at": now,
            "last_used_at": None,
        },
    )

    # --- Step 5: Create SES configuration set ---

    config_set_name = f"agentmail-{org_id}"

    ses.create_configuration_set(
        ConfigurationSetName=config_set_name,
        TrackingOptions={"CustomRedirectDomain": "track.agentmail.aws"},
        DeliveryOptions={"TlsPolicy": "REQUIRE", "SendingPoolName": "default"},
        ReputationOptions={
            "ReputationMetricsEnabled": True,
            "LastFreshStart": datetime.now(timezone.utc),
        },
        SendingOptions={"SendingEnabled": True},
        Tags=[
            {"Key": "org_id", "Value": org_id},
            {"Key": "service", "Value": "agentmail"},
            {"Key": "tier", "Value": tier},
        ],
    )

    ses.create_configuration_set_event_destination(
        ConfigurationSetName=config_set_name,
        EventDestinationName=f"{config_set_name}-events",
        EventDestination={
            "Enabled": True,
            "MatchingEventTypes": [
                "BOUNCE", "COMPLAINT", "DELIVERY", "SEND", "REJECT",
            ],
            "SnsDestination": {
                "TopicArn": "arn:aws:sns:us-east-1:ACCOUNT_ID:agentmail-ses-events",
            },
        },
    )

    # --- Step 6: Initialize usage counters ---

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": f"USAGE#MONTHLY#{month}",
            "entity_type": "MonthlyUsage",
            "org_id": org_id,
            "emails_sent": 0,
            "emails_received": 0,
            "ai_search_queries": 0,
            "ai_categorizations": 0,
            "ai_extractions": 0,
            "api_calls": 0,
            "created_at": now,
        },
    )

    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": "USAGE#STORAGE",
            "entity_type": "StorageUsage",
            "org_id": org_id,
            "storage_bytes": 0,
            "created_at": now,
        },
    )

    # --- Step 7: Initialize Redis cache ---

    init_redis_cache(org_id, tier, raw_key, key_hash)

    # --- Step 8: Publish org.created event ---

    publish_event("org.created", {
        "org_id": org_id,
        "email": email,
        "tier": tier,
        "billing_channel": "stripe",
        "default_pod_id": default_pod_id,
    })

    return {
        "org_id": org_id,
        "api_key": raw_key,  # Shown once, never stored in plaintext
        "api_key_prefix": key_prefix,
        "default_pod_id": default_pod_id,
        "tier": tier,
    }


def init_redis_cache(org_id: str, tier: str, raw_key: str, key_hash: str):
    """Pre-populate Redis caches so the first API call is fast."""
    import redis as redis_lib

    r = redis_lib.Redis(
        host="agentmail-redis.xxxxx.use1.cache.amazonaws.com",
        port=6379,
        ssl=True,
    )

    # Cache API key -> org mapping (1 hour TTL)
    r.setex(
        f"auth:{key_hash}",
        3600,
        json.dumps({
            "org_id": org_id,
            "pod_id": None,
            "scopes": ["*"],
            "status": "active",
        }),
    )

    # Cache quotas (5 min TTL)
    r.setex(
        f"{org_id}:quotas",
        300,
        json.dumps({
            "tier": tier,
            "quotas": TIER_DEFAULTS[tier],
            "overrides": {},
        }),
    )

    # Cache entitlements (5 min TTL)
    r.setex(
        f"{org_id}:entitlement",
        300,
        json.dumps({
            "tier": tier,
            "features": TIER_DEFAULTS[tier]["features"],
        }),
    )


def publish_event(event_type: str, data: dict):
    """Publish a lifecycle event to Kinesis for downstream consumers."""
    kinesis.put_record(
        StreamName="agentmail-lifecycle-events",
        PartitionKey=data.get("org_id", "system"),
        Data=json.dumps({
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }).encode(),
    )
```

---

## Provisioning: AWS Marketplace

### Flow Overview

```
Customer subscribes on AWS Marketplace listing
    |
    v
AWS redirects to fulfillment URL with registration token
    |
    v
POST https://agentmail.dev/api/marketplace/fulfill
    |
    v
Lambda: MarketplaceFulfillment
    1. ResolveCustomer(token) → CustomerIdentifier, ProductCode
    2. GetEntitlements → determine tier from entitlements
    3. Same provisioning flow as SaaS, but with:
       - billing_channel = "marketplace"
       - tier from entitlements (not "free")
       - marketplace_customer_id = CustomerIdentifier
    4. Create Cognito user (if new) or link to existing
    5. Return org_id + API key
    |
    v
User redirected to AgentMail dashboard
```

### Marketplace Fulfillment Lambda

```python
import json
from datetime import datetime, timezone

import boto3
import ulid

marketplace = boto3.client("marketplace-metering")
entitlements = boto3.client("marketplace-entitlement")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("agentmail-main")


# Marketplace entitlement → AgentMail tier mapping
ENTITLEMENT_TO_TIER = {
    "StarterPlan": "starter",
    "GrowthPlan": "growth",
    "ScalePlan": "scale",
    "EnterprisePlan": "enterprise",
}


def handler(event, context):
    """
    POST /marketplace/fulfill
    Called when a customer completes Marketplace subscription.
    The request body contains a registration token from AWS.
    """
    body = json.loads(event["body"])
    registration_token = body["x-amzn-marketplace-token"]

    # --- Step 1: Resolve the customer ---

    resolve_response = marketplace.resolve_customer(
        RegistrationToken=registration_token,
    )

    customer_id = resolve_response["CustomerIdentifier"]
    product_code = resolve_response["ProductCode"]
    customer_aws_account = resolve_response.get("CustomerAWSAccountId")

    # --- Step 2: Check if this customer already exists ---

    existing_org = find_org_by_marketplace_customer(customer_id)
    if existing_org:
        # Customer already provisioned -- update entitlements and redirect
        update_entitlements(existing_org["org_id"], customer_id, product_code)
        return {
            "statusCode": 302,
            "headers": {
                "Location": f"https://agentmail.dev/dashboard?org_id={existing_org['org_id']}",
            },
        }

    # --- Step 3: Fetch entitlements to determine tier ---

    entitlement_response = entitlements.get_entitlements(
        ProductCode=product_code,
        Filter={"CUSTOMER_IDENTIFIER": [customer_id]},
    )

    tier = "starter"  # Default
    for ent in entitlement_response.get("Entitlements", []):
        dimension = ent.get("Dimension")
        if dimension in ENTITLEMENT_TO_TIER:
            tier = ENTITLEMENT_TO_TIER[dimension]

    # --- Step 4: Provision the tenant ---

    result = provision_marketplace_tenant(
        customer_id=customer_id,
        product_code=product_code,
        customer_aws_account=customer_aws_account,
        tier=tier,
        email=body.get("email"),
    )

    # --- Step 5: Return redirect to dashboard ---

    return {
        "statusCode": 302,
        "headers": {
            "Location": (
                f"https://agentmail.dev/onboarding"
                f"?org_id={result['org_id']}"
                f"&api_key={result['api_key']}"
                f"&tier={tier}"
            ),
        },
    }


def provision_marketplace_tenant(
    customer_id: str,
    product_code: str,
    customer_aws_account: str,
    tier: str,
    email: str = None,
) -> dict:
    """
    Provision a tenant from AWS Marketplace. Same as SaaS provisioning
    but with billing_channel='marketplace' and tier from entitlements.
    """
    now = datetime.now(timezone.utc).isoformat()
    org_id = f"org_{ulid.new().str}"

    # Create Organization record (marketplace-specific fields)
    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": "METADATA",
            "entity_type": "Organization",
            "org_id": org_id,
            "name": email.split("@")[0] if email else f"Marketplace Customer {customer_id[:8]}",
            "email": email,
            "cognito_user_id": None,  # Linked after Cognito account creation
            "billing_channel": "marketplace",
            "stripe_customer_id": None,
            "marketplace_customer_id": customer_id,
            "marketplace_product_code": product_code,
            "marketplace_aws_account": customer_aws_account,
            "tier": tier,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            # GSI for looking up org by marketplace customer ID
            "GSI2PK": f"MKTPLACE#{customer_id}",
            "GSI2SK": "METADATA",
        },
        ConditionExpression="attribute_not_exists(PK)",
    )

    # Same steps as SaaS provisioning: quotas, default pod, API key, SES config, counters
    # (Using marketplace tier defaults instead of free defaults)
    marketplace_tier_defaults = get_marketplace_tier_defaults(tier)

    table.put_item(Item={
        "PK": f"ORG#{org_id}", "SK": "QUOTAS",
        "entity_type": "Quotas", "org_id": org_id,
        "tier": tier, "quotas": marketplace_tier_defaults, "overrides": {},
        "created_at": now,
    })

    default_pod_id = create_default_pod(org_id, now)
    api_key_result = create_initial_api_key(org_id, now)
    create_ses_configuration_set(org_id, tier)
    initialize_usage_counters(org_id, now)

    publish_event("org.created", {
        "org_id": org_id,
        "tier": tier,
        "billing_channel": "marketplace",
        "marketplace_customer_id": customer_id,
        "default_pod_id": default_pod_id,
    })

    return {
        "org_id": org_id,
        "api_key": api_key_result["raw_key"],
        "default_pod_id": default_pod_id,
        "tier": tier,
    }


def find_org_by_marketplace_customer(customer_id: str) -> dict | None:
    """Look up an existing org by marketplace customer ID using GSI2."""
    response = table.query(
        IndexName="GSI2",
        KeyConditionExpression="GSI2PK = :pk AND GSI2SK = :sk",
        ExpressionAttributeValues={
            ":pk": f"MKTPLACE#{customer_id}",
            ":sk": "METADATA",
        },
    )
    items = response.get("Items", [])
    return items[0] if items else None
```

---

## Tier Upgrades

### SaaS Upgrade via Stripe Checkout

```
User clicks "Upgrade" in dashboard
    |
    v
Frontend creates Stripe Checkout session
    |
    v
User completes payment on Stripe
    |
    v
Stripe webhook: checkout.session.completed
    |
    v
Lambda: StripeWebhookHandler
    1. Extract customer_id, subscription_id, price_id
    2. Map price_id → tier
    3. Update org record: tier, stripe_customer_id, stripe_subscription_id
    4. Update quota record with new tier defaults
    5. Invalidate Redis cache
    6. Publish "org.tier_changed" event
    |
    v
New limits take effect on next API call
```

### Stripe Webhook Handler

```python
import json
import stripe

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("agentmail-main")

# Stripe Price ID → AgentMail tier mapping
PRICE_TO_TIER = {
    "price_pro_monthly": "pro",
    "price_pro_annual": "pro",
    "price_business_monthly": "business",
    "price_business_annual": "business",
    "price_scale_monthly": "scale",
    "price_scale_annual": "scale",
}


def handle_stripe_webhook(event, context):
    """Handle Stripe webhook events for tier changes."""
    body = event["body"]
    sig_header = event["headers"].get("stripe-signature")

    # Verify webhook signature
    stripe_event = stripe.Webhook.construct_event(
        body, sig_header, STRIPE_WEBHOOK_SECRET,
    )

    event_type = stripe_event["type"]

    if event_type == "checkout.session.completed":
        handle_checkout_completed(stripe_event["data"]["object"])

    elif event_type == "customer.subscription.updated":
        handle_subscription_updated(stripe_event["data"]["object"])

    elif event_type == "customer.subscription.deleted":
        handle_subscription_cancelled(stripe_event["data"]["object"])

    return {"statusCode": 200}


def handle_checkout_completed(session: dict):
    """New subscription created via Stripe Checkout."""
    stripe_customer_id = session["customer"]
    subscription_id = session["subscription"]

    # Fetch subscription to get the price/tier
    subscription = stripe.Subscription.retrieve(subscription_id)
    price_id = subscription["items"]["data"][0]["price"]["id"]
    new_tier = PRICE_TO_TIER.get(price_id, "pro")

    # Find org by Stripe customer ID (set during Checkout session creation)
    org_id = session["metadata"]["org_id"]

    apply_tier_change(org_id, new_tier, stripe_customer_id, subscription_id)


def handle_subscription_updated(subscription: dict):
    """Subscription plan changed (upgrade or downgrade)."""
    stripe_customer_id = subscription["customer"]
    price_id = subscription["items"]["data"][0]["price"]["id"]
    new_tier = PRICE_TO_TIER.get(price_id)

    if not new_tier:
        return  # Unknown price, skip

    org = find_org_by_stripe_customer(stripe_customer_id)
    if not org:
        print(f"No org found for Stripe customer {stripe_customer_id}")
        return

    apply_tier_change(org["org_id"], new_tier, stripe_customer_id, subscription["id"])


def apply_tier_change(org_id: str, new_tier: str, stripe_customer_id: str = None, subscription_id: str = None):
    """Apply a tier change to an organization."""
    now = datetime.now(timezone.utc).isoformat()

    # Get current tier for the event
    org = table.get_item(Key={"PK": f"ORG#{org_id}", "SK": "METADATA"}).get("Item", {})
    old_tier = org.get("tier", "free")

    if old_tier == new_tier:
        return  # No change

    # Update org record
    update_expr = "SET tier = :tier, updated_at = :now"
    expr_values = {":tier": new_tier, ":now": now}

    if stripe_customer_id:
        update_expr += ", stripe_customer_id = :sc"
        expr_values[":sc"] = stripe_customer_id
    if subscription_id:
        update_expr += ", stripe_subscription_id = :ss"
        expr_values[":ss"] = subscription_id

    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )

    # Update quota record
    new_defaults = get_tier_defaults(new_tier)
    overrides = table.get_item(
        Key={"PK": f"ORG#{org_id}", "SK": "QUOTAS"}
    ).get("Item", {}).get("overrides", {})

    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "QUOTAS"},
        UpdateExpression="SET quotas = :quotas, tier = :tier, updated_at = :now",
        ExpressionAttributeValues={
            ":quotas": new_defaults,
            ":tier": new_tier,
            ":now": now,
        },
    )

    # Invalidate Redis caches
    invalidate_caches(org_id)

    # Publish event
    publish_event("org.tier_changed", {
        "org_id": org_id,
        "old_tier": old_tier,
        "new_tier": new_tier,
        "billing_channel": "stripe",
    })

    print(f"Tier changed for {org_id}: {old_tier} -> {new_tier}")


def invalidate_caches(org_id: str):
    """Invalidate all Redis caches for an org so new quotas take effect immediately."""
    import redis as redis_lib

    r = redis_lib.Redis(
        host="agentmail-redis.xxxxx.use1.cache.amazonaws.com",
        port=6379,
        ssl=True,
    )
    r.delete(f"{org_id}:quotas")
    r.delete(f"{org_id}:entitlement")
    # Don't delete auth cache -- API keys are still valid
```

### Marketplace Tier Upgrade

Marketplace tier changes are handled via SNS notifications from the Marketplace Entitlement Service:

```python
def handle_marketplace_entitlement_change(event, context):
    """
    Triggered by SNS notification from AWS Marketplace Entitlement Service.
    Fires when a customer changes their Marketplace contract.
    """
    for record in event["Records"]:
        message = json.loads(record["Sns"]["Message"])
        customer_id = message["CustomerIdentifier"]
        product_code = message["ProductCode"]

        # Fetch new entitlements
        entitlement_response = entitlements.get_entitlements(
            ProductCode=product_code,
            Filter={"CUSTOMER_IDENTIFIER": [customer_id]},
        )

        new_tier = "starter"
        for ent in entitlement_response.get("Entitlements", []):
            dimension = ent.get("Dimension")
            if dimension in ENTITLEMENT_TO_TIER:
                new_tier = ENTITLEMENT_TO_TIER[dimension]

        # Find org and apply change
        org = find_org_by_marketplace_customer(customer_id)
        if org:
            apply_tier_change(org["org_id"], new_tier)
```

---

## Deprovisioning: Account Deletion

Account deletion follows a three-phase process designed to prevent accidental data loss while ensuring complete cleanup.

### Phase 1: Disable (Immediate)

Triggered when the user requests account deletion, Stripe subscription is cancelled, or Marketplace sends `unsubscribe-success`.

```python
from datetime import datetime, timezone, timedelta

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("agentmail-main")
ses = boto3.client("sesv2")


def disable_tenant(org_id: str, reason: str = "user_requested"):
    """
    Phase 1: Immediately disable all tenant access.
    Reversible within 30 days.
    """
    now = datetime.now(timezone.utc).isoformat()
    disable_deadline = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    delete_deadline = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()

    # 1. Update org status
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
        UpdateExpression=(
            "SET #status = :status, disabled_at = :now, "
            "disable_reason = :reason, "
            "archive_deadline = :archive, "
            "delete_deadline = :delete, "
            "updated_at = :now"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "disabled",
            ":now": now,
            ":reason": reason,
            ":archive": disable_deadline,
            ":delete": delete_deadline,
        },
    )

    # 2. Disable all API keys
    api_keys = query_items(org_id, sk_prefix="APIKEY#")
    for key in api_keys:
        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": key["SK"]},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "disabled"},
        )

    # 3. Disable all webhooks
    webhooks = query_items(org_id, sk_prefix="WEBHOOK#")
    for wh in webhooks:
        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": wh["SK"]},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "disabled"},
        )

    # 4. Disable SES sending (stop outbound email)
    try:
        ses.put_configuration_set_sending_options(
            ConfigurationSetName=f"agentmail-{org_id}",
            SendingOptions={"SendingEnabled": False},
        )
    except ses.exceptions.NotFoundException:
        pass

    # 5. Flush all Redis caches
    flush_org_redis_keys(org_id)

    # 6. Stop metering (no further usage charges)
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
        UpdateExpression="SET metering_enabled = :false",
        ExpressionAttributeValues={":false": False},
    )

    # 7. Cancel billing
    org = table.get_item(Key={"PK": f"ORG#{org_id}", "SK": "METADATA"}).get("Item", {})
    billing_channel = org.get("billing_channel")

    if billing_channel == "stripe" and org.get("stripe_subscription_id"):
        stripe.Subscription.delete(org["stripe_subscription_id"])

    # Marketplace: unsubscribe is handled by the Marketplace SNS flow,
    # not initiated by us

    # 8. Publish event
    publish_event("org.disabled", {
        "org_id": org_id,
        "reason": reason,
        "archive_deadline": disable_deadline,
        "delete_deadline": delete_deadline,
    })

    # 9. Send confirmation email
    send_disable_confirmation_email(org_id, disable_deadline, delete_deadline)


def flush_org_redis_keys(org_id: str):
    """Delete all Redis keys for an organization."""
    import redis as redis_lib

    r = redis_lib.Redis(
        host="agentmail-redis.xxxxx.use1.cache.amazonaws.com",
        port=6379,
        ssl=True,
    )

    # Scan for all keys with org prefix
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=f"{org_id}:*", count=100)
        if keys:
            r.delete(*keys)
        if cursor == 0:
            break

    # Also delete auth keys for this org's API keys
    api_keys = query_items(org_id, sk_prefix="APIKEY#")
    for key in api_keys:
        r.delete(f"auth:{key['key_hash']}")
```

### Phase 2: Archive (After 30 Days)

A scheduled Lambda runs daily and processes orgs that have been disabled for 30+ days.

```python
def archive_disabled_tenants():
    """
    Scheduled Lambda (daily). Archives orgs that passed the 30-day disable window.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Query for disabled orgs past their archive deadline
    # Using GSI on status + archive_deadline
    orgs_to_archive = table.query(
        IndexName="GSI-Status",
        KeyConditionExpression="entity_type = :et AND #status = :status",
        FilterExpression="archive_deadline <= :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":et": "Organization",
            ":status": "disabled",
            ":now": now,
        },
    )

    for org in orgs_to_archive.get("Items", []):
        org_id = org["org_id"]

        try:
            archive_tenant(org_id)
        except Exception as e:
            print(f"Failed to archive org {org_id}: {e}")
            publish_event("org.archive_failed", {
                "org_id": org_id,
                "error": str(e),
            })


def archive_tenant(org_id: str):
    """
    Phase 2: Archive tenant data.
    - Export data to S3 archive bucket (if customer requested)
    - Delete SES receive routing (stop inbound email)
    - Delete custom domains
    - Set DynamoDB TTL on all org records (90 days from original disable)
    """
    now = datetime.now(timezone.utc)
    org = table.get_item(Key={"PK": f"ORG#{org_id}", "SK": "METADATA"}).get("Item", {})

    # Calculate TTL (90 days from original disable date)
    disabled_at = datetime.fromisoformat(org["disabled_at"])
    ttl_timestamp = int((disabled_at + timedelta(days=90)).timestamp())

    # 1. Delete all inboxes (SES receive routing stops)
    inboxes = query_all_inboxes(org_id)
    for inbox in inboxes:
        # Remove SES receipt rule for this inbox
        remove_ses_receipt_rule(inbox["email_address"])

    # 2. Delete custom domains (SES identity removed)
    domains = query_items(org_id, sk_prefix="DOMAIN#")
    for domain in domains:
        try:
            ses.delete_email_identity(EmailIdentity=domain["domain_name"])
        except Exception:
            pass

    # 3. Delete SES configuration set
    try:
        ses.delete_configuration_set(
            ConfigurationSetName=f"agentmail-{org_id}",
        )
    except ses.exceptions.NotFoundException:
        pass

    # 4. Set TTL on all DynamoDB records for this org
    all_items = query_all_org_items(org_id)
    with table.batch_writer() as batch:
        for item in all_items:
            table.update_item(
                Key={"PK": item["PK"], "SK": item["SK"]},
                UpdateExpression="SET #ttl = :ttl",
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={":ttl": ttl_timestamp},
            )

    # 5. Update org status
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
        UpdateExpression="SET #status = :status, archived_at = :now, #ttl = :ttl",
        ExpressionAttributeNames={"#status": "status", "#ttl": "ttl"},
        ExpressionAttributeValues={
            ":status": "archived",
            ":now": now.isoformat(),
            ":ttl": ttl_timestamp,
        },
    )

    publish_event("org.archived", {
        "org_id": org_id,
        "delete_at": datetime.fromtimestamp(ttl_timestamp, tz=timezone.utc).isoformat(),
    })
```

### Phase 3: Delete (After 90 Days)

DynamoDB TTL handles most deletion automatically. A daily cleanup Lambda handles the rest:

```python
def cleanup_expired_tenants():
    """
    Scheduled Lambda (daily). Cleans up non-DynamoDB resources for
    tenants past the 90-day retention period.

    DynamoDB items are auto-deleted by TTL, but we need to clean up:
    - S3 objects (email bodies, attachments, exports)
    - OpenSearch documents
    - Any remaining Redis keys
    """
    # Query for archived orgs past their delete deadline
    expired_orgs = table.query(
        IndexName="GSI-Status",
        KeyConditionExpression="entity_type = :et AND #status = :status",
        FilterExpression="delete_deadline <= :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":et": "Organization",
            ":status": "archived",
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )

    for org in expired_orgs.get("Items", []):
        org_id = org["org_id"]

        try:
            hard_delete_tenant(org_id)
        except Exception as e:
            print(f"Failed to delete org {org_id}: {e}")


def hard_delete_tenant(org_id: str):
    """Phase 3: Permanently delete all tenant data."""
    s3 = boto3.client("s3")

    # 1. Delete S3 objects
    for bucket in ["agentmail-email-bodies", "agentmail-attachments", "agentmail-exports"]:
        delete_all_s3_objects(s3, bucket, prefix=f"{org_id}/")

    # 2. Delete OpenSearch documents
    opensearch_client.delete_by_query(
        index="agentmail-emails",
        body={
            "query": {"term": {"org_id.keyword": org_id}},
        },
    )

    # 3. Flush any remaining Redis keys
    flush_org_redis_keys(org_id)

    # 4. DynamoDB records should be auto-deleted by TTL by now,
    #    but clean up any stragglers
    remaining_items = query_all_org_items(org_id)
    with table.batch_writer() as batch:
        for item in remaining_items:
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    # 5. Publish final event
    publish_event("org.deleted", {
        "org_id": org_id,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    })

    print(f"Permanently deleted all data for org {org_id}")


def delete_all_s3_objects(s3_client, bucket: str, prefix: str):
    """Delete all objects under a prefix in an S3 bucket."""
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = page.get("Contents", [])
        if not objects:
            continue

        delete_keys = [{"Key": obj["Key"]} for obj in objects]

        s3_client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": delete_keys},
        )
```

---

## Account Recovery

### Within 30-Day Disable Window

The user can reactivate their account by logging in and resubscribing:

```python
def reactivate_tenant(org_id: str):
    """
    Reactivate a disabled org within the 30-day window.
    Called when user logs in and confirms reactivation.
    """
    org = table.get_item(Key={"PK": f"ORG#{org_id}", "SK": "METADATA"}).get("Item", {})

    if org.get("status") != "disabled":
        raise ValueError(f"Org is not in disabled state (current: {org.get('status')})")

    archive_deadline = datetime.fromisoformat(org["archive_deadline"])
    if datetime.now(timezone.utc) > archive_deadline:
        raise ValueError("30-day recovery window has expired. Contact support.")

    now = datetime.now(timezone.utc).isoformat()

    # 1. Reactivate org
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
        UpdateExpression=(
            "SET #status = :status, reactivated_at = :now, "
            "metering_enabled = :true, updated_at = :now "
            "REMOVE disabled_at, disable_reason, archive_deadline, delete_deadline"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "active",
            ":now": now,
            ":true": True,
        },
    )

    # 2. Re-enable API keys
    api_keys = query_items(org_id, sk_prefix="APIKEY#")
    for key in api_keys:
        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": key["SK"]},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "active"},
        )

    # 3. Re-enable webhooks
    webhooks = query_items(org_id, sk_prefix="WEBHOOK#")
    for wh in webhooks:
        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": wh["SK"]},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "active"},
        )

    # 4. Re-enable SES sending
    try:
        ses.put_configuration_set_sending_options(
            ConfigurationSetName=f"agentmail-{org_id}",
            SendingOptions={"SendingEnabled": True},
        )
    except ses.exceptions.NotFoundException:
        # Config set was deleted -- recreate
        create_ses_configuration_set(org_id, org.get("tier", "free"))

    # 5. Rebuild Redis caches
    init_redis_cache(org_id, org.get("tier", "free"), None, None)

    publish_event("org.reactivated", {"org_id": org_id})
```

### After 30 Days (Archived)

Data may be partially archived. The SES configuration and routing rules have been deleted. Recovery requires a support ticket and manual intervention:

1. Support engineer verifies account ownership
2. If DynamoDB TTL has not yet expired, records can be restored by removing the `ttl` attribute
3. SES configuration set must be recreated
4. SES receipt rules must be re-created for each inbox
5. Custom domains must be re-verified

### After 90 Days

Data is permanently deleted. No recovery is possible. The org_id is not reused.

---

## Data Export (GDPR Compliance)

### API Endpoint

```http
POST /organizations/me/export
Authorization: Bearer am_abc123...
```

### Response

```json
{
  "export_id": "export_01HXYZ...",
  "status": "processing",
  "created_at": "2026-04-10T14:30:00.000Z",
  "estimated_completion": "2026-04-10T14:45:00.000Z"
}
```

### Export Lambda

```python
import io
import zipfile
from email.mime.text import MIMEText

import boto3

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("agentmail-main")
ses = boto3.client("sesv2")


def handle_export_request(event, context):
    """
    POST /organizations/me/export
    Triggers an async data export job.
    Rate limited: 1 export per 24 hours per org.
    """
    org_id = event["requestContext"]["authorizer"]["org_id"]

    # Rate limit: 1 export per 24 hours
    last_export = get_last_export_time(org_id)
    if last_export:
        hours_since = (datetime.now(timezone.utc) - last_export).total_seconds() / 3600
        if hours_since < 24:
            return {
                "statusCode": 429,
                "body": json.dumps({
                    "error": "export_rate_limited",
                    "retry_after_hours": round(24 - hours_since, 1),
                }),
            }

    export_id = f"export_{ulid.new().str}"

    # Record the export request
    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": f"EXPORT#{export_id}",
            "entity_type": "Export",
            "export_id": export_id,
            "org_id": org_id,
            "status": "processing",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Trigger async export Lambda
    lambda_client = boto3.client("lambda")
    lambda_client.invoke(
        FunctionName="agentmail-data-export-worker",
        InvocationType="Event",  # Async
        Payload=json.dumps({
            "org_id": org_id,
            "export_id": export_id,
        }),
    )

    return {
        "statusCode": 202,
        "body": json.dumps({
            "export_id": export_id,
            "status": "processing",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }),
    }


def export_worker(event, context):
    """
    Async worker Lambda that generates the data export ZIP.
    Invoked asynchronously by the export request handler.
    """
    org_id = event["org_id"]
    export_id = event["export_id"]

    try:
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

            # --- Export organization metadata ---
            org = table.get_item(
                Key={"PK": f"ORG#{org_id}", "SK": "METADATA"}
            ).get("Item", {})
            # Remove internal fields
            org.pop("PK", None)
            org.pop("SK", None)
            zf.writestr("organization.json", json.dumps(org, indent=2, default=str))

            # --- Export all inboxes ---
            inboxes = query_all_inboxes(org_id)
            zf.writestr("inboxes.json", json.dumps(inboxes, indent=2, default=str))

            # --- Export all messages as EML files ---
            for inbox in inboxes:
                inbox_id = inbox["inbox_id"]
                inbox_name = inbox.get("email_address", inbox_id)
                messages = query_all_messages(org_id, inbox_id)

                for msg in messages:
                    msg_id = msg["message_id"]

                    # Fetch email body from S3
                    try:
                        body_obj = s3.get_object(
                            Bucket="agentmail-email-bodies",
                            Key=f"{org_id}/{inbox_id}/{msg_id}/body.eml",
                        )
                        eml_content = body_obj["Body"].read()
                        zf.writestr(
                            f"inboxes/{inbox_name}/messages/{msg_id}.eml",
                            eml_content,
                        )
                    except s3.exceptions.NoSuchKey:
                        # Body may have been deleted, include metadata only
                        zf.writestr(
                            f"inboxes/{inbox_name}/messages/{msg_id}.json",
                            json.dumps(msg, indent=2, default=str),
                        )

                    # Fetch attachments
                    attachments = msg.get("attachments", [])
                    for att in attachments:
                        att_id = att["attachment_id"]
                        filename = att.get("filename", att_id)
                        try:
                            att_obj = s3.get_object(
                                Bucket="agentmail-attachments",
                                Key=f"{org_id}/{inbox_id}/{msg_id}/{att_id}/{filename}",
                            )
                            zf.writestr(
                                f"inboxes/{inbox_name}/messages/{msg_id}/attachments/{filename}",
                                att_obj["Body"].read(),
                            )
                        except s3.exceptions.NoSuchKey:
                            pass

            # --- Export webhook configurations ---
            webhooks = query_items(org_id, sk_prefix="WEBHOOK#")
            zf.writestr("webhooks.json", json.dumps(webhooks, indent=2, default=str))

            # --- Export domain configurations ---
            domains = query_items(org_id, sk_prefix="DOMAIN#")
            zf.writestr("domains.json", json.dumps(domains, indent=2, default=str))

            # --- Export API key metadata (not secrets) ---
            api_keys = query_items(org_id, sk_prefix="APIKEY#")
            safe_keys = []
            for key in api_keys:
                safe_keys.append({
                    "key_prefix": key.get("key_prefix"),
                    "name": key.get("name"),
                    "scopes": key.get("scopes"),
                    "pod_id": key.get("pod_id"),
                    "status": key.get("status"),
                    "created_at": key.get("created_at"),
                    "last_used_at": key.get("last_used_at"),
                    # key_hash intentionally excluded
                })
            zf.writestr("api_keys.json", json.dumps(safe_keys, indent=2, default=str))

            # --- Export usage history ---
            usage_records = query_items(org_id, sk_prefix="USAGE#")
            zf.writestr("usage_history.json", json.dumps(usage_records, indent=2, default=str))

            # --- Export pod configurations ---
            pods = query_items(org_id, sk_prefix="POD#")
            pod_configs = []
            for pod in pods:
                if pod.get("entity_type") == "Pod":
                    pod.pop("PK", None)
                    pod.pop("SK", None)
                    # Redact webhook secrets
                    config = pod.get("config", {})
                    if "webhook_secret" in config:
                        config["webhook_secret"] = "[REDACTED]"
                    pod_configs.append(pod)
            zf.writestr("pods.json", json.dumps(pod_configs, indent=2, default=str))

        # Upload ZIP to S3
        zip_buffer.seek(0)
        export_key = f"{org_id}/exports/{export_id}.zip"

        s3.put_object(
            Bucket="agentmail-exports",
            Key=export_key,
            Body=zip_buffer.getvalue(),
            ContentType="application/zip",
            ServerSideEncryption="aws:kms",
            Metadata={"org_id": org_id, "export_id": export_id},
        )

        # Generate presigned download URL (24-hour expiry)
        download_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": "agentmail-exports", "Key": export_key},
            ExpiresIn=86400,  # 24 hours
        )

        # Update export record
        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"EXPORT#{export_id}"},
            UpdateExpression=(
                "SET #status = :status, download_url = :url, "
                "completed_at = :now, expires_at = :expires"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "completed",
                ":url": download_url,
                ":now": datetime.now(timezone.utc).isoformat(),
                ":expires": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            },
        )

        # Send notification email
        org = table.get_item(
            Key={"PK": f"ORG#{org_id}", "SK": "METADATA"}
        ).get("Item", {})

        ses.send_email(
            FromEmailAddress="noreply@agentmail.dev",
            Destination={"ToAddresses": [org["email"]]},
            Content={
                "Simple": {
                    "Subject": {"Data": "Your AgentMail Data Export is Ready"},
                    "Body": {
                        "Text": {
                            "Data": (
                                f"Your data export is ready for download.\n\n"
                                f"Download link (expires in 24 hours):\n{download_url}\n\n"
                                f"This export contains all your organization data including "
                                f"messages, attachments, inbox configurations, and usage history.\n\n"
                                f"-- AgentMail"
                            ),
                        },
                    },
                },
            },
        )

        publish_event("org.export_completed", {
            "org_id": org_id,
            "export_id": export_id,
        })

    except Exception as e:
        print(f"Export failed for org {org_id}: {e}")

        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"EXPORT#{export_id}"},
            UpdateExpression="SET #status = :status, error = :error, failed_at = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "failed",
                ":error": str(e),
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )

        publish_event("org.export_failed", {
            "org_id": org_id,
            "export_id": export_id,
            "error": str(e),
        })

        raise
```

### Export Contents

The exported ZIP file contains:

```
export_01HXYZ.zip
├── organization.json          # Org metadata (name, tier, billing channel)
├── pods.json                  # All pod configurations
├── inboxes.json               # All inbox configurations
├── webhooks.json              # Webhook endpoint configs
├── domains.json               # Custom domain configs
├── api_keys.json              # API key metadata (not secrets)
├── usage_history.json         # Monthly and daily usage records
└── inboxes/
    ├── support@acme.com/
    │   └── messages/
    │       ├── msg_01ABC.eml           # Full email in EML format
    │       ├── msg_01ABC/
    │       │   └── attachments/
    │       │       └── invoice.pdf
    │       ├── msg_01DEF.eml
    │       └── ...
    ├── sales@acme.com/
    │   └── messages/
    │       └── ...
    └── ...
```

### Export Constraints

| Constraint | Value |
|------------|-------|
| Rate limit | 1 export per 24 hours per org |
| Max export size | 10 GB (larger orgs are split into multiple ZIPs) |
| Download URL expiry | 24 hours |
| Export retention in S3 | 7 days (S3 lifecycle policy) |
| Redacted fields | API key hashes, webhook secrets |
| Included fields | All messages (EML), all attachments, all configs, usage history |

---

## Provisioning Timeline Summary

```
Day 0: Sign up
    → Cognito account created
    → Post-confirmation Lambda provisions org
    → User has org_id + API key

Day 0+: Active usage
    → API calls, emails sent/received, AI features
    → Usage metered (Stripe or Marketplace)
    → Tier upgrades/downgrades via billing channel

Day N: Account deletion requested (or subscription cancelled)
    → Phase 1: Disable (immediate)
    → API returns 403, email stops, metering stops

Day N+30: Archive
    → Phase 2: SES routing removed, domains unverified
    → DynamoDB TTL set (60 days from now)
    → Last chance for self-service recovery expired

Day N+90: Delete
    → Phase 3: S3 objects deleted, OpenSearch cleaned, DynamoDB TTL expires
    → org.deleted event published
    → No recovery possible
```
