# Customer Lifecycle

This document covers the complete customer lifecycle for AgentMail on the AWS Marketplace: from initial subscription through onboarding, entitlement management, and unsubscribe handling.

---

## Onboarding Flow

When a customer subscribes to AgentMail through the AWS Marketplace, the following sequence executes:

```
1. Customer clicks "Subscribe" on AWS Marketplace listing
   |
2. Customer configures contract (tier, duration) and accepts EULA
   |
3. AWS Marketplace creates the subscription
   |
4. AWS redirects customer's browser via POST to our fulfillment URL
   | (POST body contains x-amzn-marketplace-token)
   |
5. Our backend calls ResolveCustomer with the token
   | → Returns: CustomerIdentifier, ProductCode, CustomerAWSAccountId
   |
6. Create tenant in DynamoDB (or link to existing tenant)
   |
7. Provision resources: default pod, generate API keys
   |
8. Associate CustomerIdentifier with tenant record
   |
9. Redirect customer to onboarding dashboard
   |
10. Begin metering usage
```

### Step 1-3: Customer Subscribes on AWS Marketplace

The customer visits the AgentMail listing on AWS Marketplace, selects a contract tier (Starter, Growth, Scale, or accepts a private offer), chooses the contract duration, and clicks "Subscribe." AWS handles all payment processing.

### Step 4: Fulfillment URL Receives POST

AWS redirects the customer's browser to our **fulfillment URL** via an HTTP POST. The POST body contains a single form-encoded parameter:

```
POST https://api.agentmail.aws/v1/marketplace/fulfill
Content-Type: application/x-www-form-urlencoded

x-amzn-marketplace-token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**CRITICAL: This token expires within minutes. Process it immediately in the request handler -- do not queue it for later processing.**

### Step 5: ResolveCustomer

The fulfillment Lambda immediately calls `ResolveCustomer` to exchange the token for customer details:

```python
import boto3
import json
import os
import uuid
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

marketplace = boto3.client("meteringmarketplace")
dynamodb = boto3.resource("dynamodb")
tenant_table = dynamodb.Table(os.environ["TENANT_TABLE_NAME"])


def handle_fulfillment(event, context):
    """
    Handle POST from AWS Marketplace fulfillment redirect.
    Called when a customer subscribes and is redirected to our registration URL.
    """
    # Parse the marketplace token from the POST body
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")

    params = parse_qs(body)
    token = params.get("x-amzn-marketplace-token", [None])[0]

    if not token:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing marketplace token"}),
        }

    # Resolve the token to get customer details
    try:
        resolve_response = marketplace.resolve_customer(
            RegistrationToken=token
        )
    except marketplace.exceptions.InvalidTokenException:
        # Token expired or invalid
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Invalid or expired marketplace token. "
                "Please return to AWS Marketplace and subscribe again."
            }),
        }
    except marketplace.exceptions.ExpiredTokenException:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Marketplace token has expired. "
                "Please return to AWS Marketplace and subscribe again."
            }),
        }

    customer_id = resolve_response["CustomerIdentifier"]
    product_code = resolve_response["ProductCode"]
    customer_aws_account = resolve_response.get("CustomerAWSAccountId", "unknown")

    print(f"Resolved customer: {customer_id}, product: {product_code}, "
          f"AWS account: {customer_aws_account}")

    # Check if this customer already has a tenant (re-subscribe scenario)
    existing = tenant_table.query(
        IndexName="MarketplaceCustomerIndex",
        KeyConditionExpression="marketplace_customer_id = :cid",
        ExpressionAttributeValues={":cid": customer_id},
    )

    if existing["Items"]:
        # Reactivate existing tenant
        tenant = existing["Items"][0]
        org_id = tenant["org_id"]
        tenant_table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
            UpdateExpression="SET #s = :active, updated_at = :now, "
            "marketplace_product_code = :pc, customer_aws_account = :acct",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":active": "active",
                ":now": datetime.now(timezone.utc).isoformat(),
                ":pc": product_code,
                ":acct": customer_aws_account,
            },
        )
        print(f"Reactivated existing tenant: {org_id}")
    else:
        # Create new tenant
        org_id = f"org-{uuid.uuid4().hex[:12]}"
        create_tenant(org_id, customer_id, product_code, customer_aws_account)
        print(f"Created new tenant: {org_id}")

    # Generate a one-time registration token for the onboarding dashboard
    registration_token = uuid.uuid4().hex
    store_registration_token(registration_token, org_id, ttl=3600)  # 1 hour expiry

    # Redirect to onboarding dashboard
    dashboard_url = (
        f"https://dashboard.agentmail.aws/onboard?"
        f"token={registration_token}&org={org_id}"
    )

    return {
        "statusCode": 302,
        "headers": {"Location": dashboard_url},
        "body": "",
    }


def create_tenant(org_id, customer_id, product_code, customer_aws_account):
    """Create a new tenant with default configuration."""
    now = datetime.now(timezone.utc).isoformat()
    ttl = None  # Tenants do not expire

    # Create organization record
    tenant_table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": "METADATA",
            "org_id": org_id,
            "marketplace_customer_id": customer_id,
            "marketplace_product_code": product_code,
            "customer_aws_account": customer_aws_account,
            "status": "active",
            "tier": "starter",  # Default; updated when entitlements are checked
            "created_at": now,
            "updated_at": now,
        }
    )

    # Create default pod
    default_pod_id = f"pod-{uuid.uuid4().hex[:12]}"
    tenant_table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": f"POD#{default_pod_id}",
            "pod_id": default_pod_id,
            "org_id": org_id,
            "name": "default",
            "status": "active",
            "created_at": now,
        }
    )

    # Generate initial API key
    import hashlib
    import secrets

    raw_key = f"am_{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]  # "am_" + first 9 hex chars, for display

    tenant_table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": f"APIKEY#{key_hash}",
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "org_id": org_id,
            "name": "Default API Key",
            "scopes": ["*"],  # Full access
            "status": "active",
            "created_at": now,
        }
    )

    # Store the raw key temporarily for the onboarding flow
    # This is the ONLY time the raw key is available
    store_onboarding_api_key(org_id, raw_key, ttl=3600)

    return org_id


def store_registration_token(token, org_id, ttl):
    """Store a one-time registration token in DynamoDB with TTL."""
    tenant_table.put_item(
        Item={
            "PK": f"REGTOKEN#{token}",
            "SK": "TOKEN",
            "org_id": org_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ttl": int(time.time()) + ttl,
        }
    )


def store_onboarding_api_key(org_id, raw_key, ttl):
    """
    Temporarily store the raw API key for the onboarding flow.
    This is encrypted at rest in DynamoDB and deleted after first retrieval.
    """
    tenant_table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": "ONBOARD_KEY",
            "raw_key": raw_key,
            "ttl": int(time.time()) + ttl,
        }
    )
```

### Step 6-9: Tenant Creation

The `create_tenant` function above:
1. Creates an organization record in DynamoDB with the Marketplace `CustomerIdentifier` linked
2. Creates a default pod for the organization
3. Generates an API key (SHA-256 hashed for storage, raw key shown once during onboarding)
4. Redirects the customer to the onboarding dashboard where they can:
   - View their API key (shown exactly once)
   - Configure their first webhook
   - Verify a custom domain
   - Read quickstart documentation

### Step 10: Begin Metering

Once the tenant is active, all API requests are metered. The API Lambda functions emit usage events to Kinesis (see [Metering Pipeline](./metering-pipeline.md)). The `customer_identifier` is resolved from the tenant record on each authenticated request.

---

## SNS Notifications

AWS Marketplace publishes customer lifecycle events to an SNS topic. We subscribe an SQS queue to this topic for durable processing.

### SNS Topic Subscription Architecture

```
AWS Marketplace SNS Topic
    |
    v
SQS Queue: agentmail-marketplace-events
    |
    | (SQS trigger with batch size 1, visibility timeout 300s)
    v
Lambda: MarketplaceEventHandler
    |
    v
DynamoDB: Update tenant status
    |
    +---> SES: Send customer notification email
```

### Why SQS, Not Direct Lambda

| Approach | Failure Mode | Risk |
|----------|-------------|------|
| SNS → Lambda (direct) | Lambda error = message lost (SNS retries 3x then drops) | Missed unsubscribe = continued metering for a cancelled customer |
| SNS → SQS → Lambda | Lambda error = message returns to queue. DLQ after N failures | Zero message loss. Failed events are preserved in DLQ for manual processing |

**Always use SQS between SNS and Lambda for Marketplace events.** These events control billing state -- a missed `unsubscribe-success` means you continue metering and billing a customer who cancelled.

### SNS Event Types

| Event Type | When It Fires | Required Action |
|-----------|---------------|-----------------|
| `subscribe-success` | Customer subscription is activated | Confirm tenant is provisioned. If fulfillment URL was never visited, send welcome email with registration link. |
| `subscribe-fail` | Subscription payment failed | Do not provision. If tenant exists from fulfillment URL visit, mark as `payment_failed`. |
| `unsubscribe-pending` | Customer initiated cancellation | Send data export notification. Begin 30-day grace period. |
| `unsubscribe-success` | Cancellation finalized | Stop metering. Begin data retention countdown. Disable API keys. |
| `entitlement-updated` | Customer changed tier (upgrade/downgrade) | Refresh entitlement cache immediately. Update quotas. |

### SNS Message Format

```json
{
  "Type": "Notification",
  "MessageId": "abc123-def456-ghi789",
  "TopicArn": "arn:aws:sns:us-east-1:123456789012:aws-mp-subscription-notification-PRODUCTCODE",
  "Subject": null,
  "Message": "{\"action\":\"subscribe-success\",\"customer-identifier\":\"cust-abc123\",\"product-code\":\"prod-abcdef1234567\"}",
  "Timestamp": "2026-04-10T14:30:00.000Z",
  "SignatureVersion": "1",
  "Signature": "...",
  "SigningCertURL": "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-...",
  "UnsubscribeURL": "https://sns.us-east-1.amazonaws.com/..."
}
```

The `Message` field is a JSON string that must be parsed separately:

```json
{
  "action": "subscribe-success",
  "customer-identifier": "cust-abc123",
  "product-code": "prod-abcdef1234567"
}
```

For `entitlement-updated`:
```json
{
  "action": "entitlement-updated",
  "customer-identifier": "cust-abc123",
  "product-code": "prod-abcdef1234567"
}
```

**Note**: The SNS message for `entitlement-updated` does not include the new entitlement details. You must call `GetEntitlements` to fetch the updated values.

### SNS Event Handler Lambda

```python
"""
AgentMail Marketplace Event Handler Lambda

Triggered: SQS queue subscribed to AWS Marketplace SNS topic
Purpose: Process customer lifecycle events (subscribe, unsubscribe, entitlement changes)
"""

import json
import os
from datetime import datetime, timezone

import boto3

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")
marketplace_entitlements = boto3.client("marketplace-entitlement")

tenant_table = dynamodb.Table(os.environ["TENANT_TABLE_NAME"])
PRODUCT_CODE = os.environ["MARKETPLACE_PRODUCT_CODE"]


def handler(event, context):
    """Process SQS messages containing Marketplace SNS notifications."""
    for sqs_record in event["Records"]:
        # Parse SNS message from SQS body
        sns_message = json.loads(sqs_record["body"])
        marketplace_event = json.loads(sns_message["Message"])

        action = marketplace_event["action"]
        customer_id = marketplace_event["customer-identifier"]
        product_code = marketplace_event["product-code"]

        print(f"Processing {action} for customer {customer_id}")

        if action == "subscribe-success":
            handle_subscribe_success(customer_id, product_code)
        elif action == "subscribe-fail":
            handle_subscribe_fail(customer_id, product_code)
        elif action == "unsubscribe-pending":
            handle_unsubscribe_pending(customer_id)
        elif action == "unsubscribe-success":
            handle_unsubscribe_success(customer_id)
        elif action == "entitlement-updated":
            handle_entitlement_updated(customer_id, product_code)
        else:
            print(f"Unknown action: {action}")


def handle_subscribe_success(customer_id, product_code):
    """
    Customer subscription activated.
    If tenant already exists (fulfillment URL was visited), confirm active status.
    If tenant does not exist (customer subscribed but never visited), create placeholder
    and send registration email.
    """
    tenant = find_tenant_by_customer_id(customer_id)

    if tenant:
        # Tenant exists -- ensure status is active
        tenant_table.update_item(
            Key={"PK": f"ORG#{tenant['org_id']}", "SK": "METADATA"},
            UpdateExpression="SET #s = :active, updated_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":active": "active",
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Confirmed active status for tenant {tenant['org_id']}")
    else:
        # Customer subscribed but never visited fulfillment URL
        # This happens when the customer closes the browser before redirect completes
        print(f"WARNING: No tenant for customer {customer_id}. "
              "Customer may not have completed registration.")
        # Create a placeholder tenant that will be completed when they visit the
        # fulfillment URL. Store just enough to link the customer later.
        # The customer can re-visit the Marketplace to trigger the redirect again.
        create_pending_tenant(customer_id, product_code)


def handle_subscribe_fail(customer_id, product_code):
    """Subscription payment failed. Mark tenant as payment_failed if exists."""
    tenant = find_tenant_by_customer_id(customer_id)
    if tenant:
        tenant_table.update_item(
            Key={"PK": f"ORG#{tenant['org_id']}", "SK": "METADATA"},
            UpdateExpression="SET #s = :status, updated_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "payment_failed",
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Marked tenant {tenant['org_id']} as payment_failed")


def handle_unsubscribe_pending(customer_id):
    """
    Customer initiated cancellation. Begin grace period.
    - Send data export notification
    - Mark tenant as 'cancelling'
    - Do NOT stop metering yet (customer still has access until period ends)
    """
    tenant = find_tenant_by_customer_id(customer_id)
    if not tenant:
        print(f"WARNING: No tenant for unsubscribe-pending customer {customer_id}")
        return

    org_id = tenant["org_id"]
    tenant_table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
        UpdateExpression="SET #s = :status, cancellation_initiated_at = :now, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "cancelling",
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Send notification email about data export options
    send_cancellation_notice(tenant)
    print(f"Tenant {org_id} marked as cancelling")


def handle_unsubscribe_success(customer_id):
    """
    Cancellation finalized. Stop all services.
    - Stop metering
    - Disable API keys
    - Begin data retention countdown (30 days, then archive; 90 days, then delete)
    """
    tenant = find_tenant_by_customer_id(customer_id)
    if not tenant:
        print(f"WARNING: No tenant for unsubscribe-success customer {customer_id}")
        return

    org_id = tenant["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Update tenant status
    tenant_table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
        UpdateExpression="SET #s = :status, cancelled_at = :now, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "cancelled",
            ":now": now,
        },
    )

    # Disable all API keys for this organization
    disable_all_api_keys(org_id)

    # Disable all webhooks
    disable_all_webhooks(org_id)

    print(f"Tenant {org_id} cancelled. API keys disabled. Data retention initiated.")


def handle_entitlement_updated(customer_id, product_code):
    """
    Customer changed tier. Fetch new entitlements and update quotas.
    """
    tenant = find_tenant_by_customer_id(customer_id)
    if not tenant:
        print(f"WARNING: No tenant for entitlement-updated customer {customer_id}")
        return

    # Fetch new entitlements
    entitlements = get_entitlements(customer_id, product_code)

    # Update tenant quotas
    org_id = tenant["org_id"]
    tenant_table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"},
        UpdateExpression="SET entitlements = :ent, updated_at = :now",
        ExpressionAttributeValues={
            ":ent": entitlements,
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )

    print(f"Updated entitlements for tenant {org_id}: {entitlements}")


def find_tenant_by_customer_id(customer_id):
    """Look up tenant by Marketplace CustomerIdentifier."""
    response = tenant_table.query(
        IndexName="MarketplaceCustomerIndex",
        KeyConditionExpression="marketplace_customer_id = :cid",
        ExpressionAttributeValues={":cid": customer_id},
    )
    return response["Items"][0] if response["Items"] else None


def get_entitlements(customer_id, product_code):
    """Fetch current entitlements from AWS Marketplace Entitlement Service."""
    response = marketplace_entitlements.get_entitlements(
        ProductCode=product_code,
        Filter={"CUSTOMER_IDENTIFIER": [customer_id]},
    )
    entitlements = {}
    for entitlement in response.get("Entitlements", []):
        dimension = entitlement["Dimension"]
        value = entitlement.get("Value", {})
        if "IntegerValue" in value:
            entitlements[dimension] = value["IntegerValue"]
        elif "BooleanValue" in value:
            entitlements[dimension] = value["BooleanValue"]
        elif "StringValue" in value:
            entitlements[dimension] = value["StringValue"]
        elif "DoubleValue" in value:
            entitlements[dimension] = value["DoubleValue"]
    return entitlements


def create_pending_tenant(customer_id, product_code):
    """Create a placeholder for customers who subscribed but didn't complete registration."""
    import uuid
    org_id = f"org-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    tenant_table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": "METADATA",
            "org_id": org_id,
            "marketplace_customer_id": customer_id,
            "marketplace_product_code": product_code,
            "status": "pending_registration",
            "created_at": now,
            "updated_at": now,
        }
    )
    return org_id


def disable_all_api_keys(org_id):
    """Disable all API keys for an organization."""
    response = tenant_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"ORG#{org_id}",
            ":prefix": "APIKEY#",
        },
    )
    for key in response["Items"]:
        tenant_table.update_item(
            Key={"PK": key["PK"], "SK": key["SK"]},
            UpdateExpression="SET #s = :disabled",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":disabled": "disabled"},
        )


def disable_all_webhooks(org_id):
    """Disable all webhooks for an organization."""
    response = tenant_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"ORG#{org_id}",
            ":prefix": "WEBHOOK#",
        },
    )
    for webhook in response["Items"]:
        tenant_table.update_item(
            Key={"PK": webhook["PK"], "SK": webhook["SK"]},
            UpdateExpression="SET #s = :disabled",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":disabled": "disabled"},
        )


def send_cancellation_notice(tenant):
    """Send email notification about pending cancellation and data export."""
    # Implementation: SES email to the tenant's admin contact
    pass
```

---

## Entitlement Checking

### GetEntitlements API

Use `GetEntitlements` to verify what a customer is entitled to before processing requests.

### Request Format

```python
response = marketplace_entitlements.get_entitlements(
    ProductCode="prod-abcdef1234567",
    Filter={
        "CUSTOMER_IDENTIFIER": ["cust-abc123"]
    }
)
```

### Response Format

```json
{
  "Entitlements": [
    {
      "CustomerIdentifier": "cust-abc123",
      "ProductCode": "prod-abcdef1234567",
      "Dimension": "messages_sent",
      "Value": {
        "IntegerValue": 5000
      },
      "ExpirationDate": "2027-04-10T00:00:00Z"
    },
    {
      "CustomerIdentifier": "cust-abc123",
      "ProductCode": "prod-abcdef1234567",
      "Dimension": "inboxes_active",
      "Value": {
        "IntegerValue": 25
      },
      "ExpirationDate": "2027-04-10T00:00:00Z"
    },
    {
      "CustomerIdentifier": "cust-abc123",
      "ProductCode": "prod-abcdef1234567",
      "Dimension": "ai_searches",
      "Value": {
        "IntegerValue": 1000
      },
      "ExpirationDate": "2027-04-10T00:00:00Z"
    }
  ]
}
```

### Entitlement Caching Strategy

Calling `GetEntitlements` on every API request adds 50-100ms latency and risks throttling (the API has a low TPS limit). Instead, cache entitlements and refresh on a schedule:

```python
"""
Entitlement cache using Redis.
- Cache TTL: 15 minutes
- Immediate refresh on entitlement-updated SNS notification
- Fallback to GetEntitlements on cache miss
"""

import json
import os
import time

import boto3
import redis

redis_client = redis.Redis(
    host=os.environ["REDIS_HOST"],
    port=6379,
    decode_responses=True,
)
marketplace_entitlements = boto3.client("marketplace-entitlement")
PRODUCT_CODE = os.environ["MARKETPLACE_PRODUCT_CODE"]
CACHE_TTL_SECONDS = 900  # 15 minutes


def get_entitlements_cached(customer_id: str) -> dict:
    """
    Get entitlements for a customer, using Redis cache with fallback.
    Returns dict of dimension -> entitled_quantity.
    """
    cache_key = f"entitlement:{customer_id}"

    # Try cache first
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Cache miss -- fetch from Marketplace
    entitlements = fetch_entitlements(customer_id)

    # Write to cache
    redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(entitlements))

    return entitlements


def refresh_entitlement_cache(customer_id: str) -> dict:
    """
    Force refresh entitlement cache. Called on entitlement-updated SNS event.
    """
    entitlements = fetch_entitlements(customer_id)
    cache_key = f"entitlement:{customer_id}"
    redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(entitlements))
    return entitlements


def fetch_entitlements(customer_id: str) -> dict:
    """Fetch entitlements from AWS Marketplace Entitlement Service."""
    response = marketplace_entitlements.get_entitlements(
        ProductCode=PRODUCT_CODE,
        Filter={"CUSTOMER_IDENTIFIER": [customer_id]},
    )
    entitlements = {}
    for ent in response.get("Entitlements", []):
        dimension = ent["Dimension"]
        value = ent.get("Value", {})
        if "IntegerValue" in value:
            entitlements[dimension] = value["IntegerValue"]
        elif "DoubleValue" in value:
            entitlements[dimension] = value["DoubleValue"]
    return entitlements


def check_entitlement(customer_id: str, dimension: str, requested_quantity: int = 1) -> bool:
    """
    Check if a customer is entitled to use a dimension.

    For SaaS Contracts with Consumption, the entitlement represents the included
    amount in the contract. Usage above this amount is billed as overage.
    We allow usage above the entitlement (it's metered and billed), but we
    enforce hard limits from the tenant's quota configuration to prevent abuse.

    Returns True if the customer has an active entitlement for this dimension.
    """
    entitlements = get_entitlements_cached(customer_id)

    # If the customer has ANY entitlement, they have an active subscription
    # The entitlement value is the included amount, not a hard cap
    if not entitlements:
        return False  # No active subscription

    return True  # Active subscription; overage is billed via metering
```

### Enforcement in Application Code

```python
def api_middleware_check_entitlement(event, context):
    """
    Middleware that runs before every API request.
    Verifies the customer has an active Marketplace subscription.
    """
    org_id = event["requestContext"]["authorizer"]["org_id"]
    customer_id = get_marketplace_customer_id(org_id)

    if not customer_id:
        # Tenant not linked to Marketplace (should not happen in production)
        return error_response(403, "No active subscription")

    if not check_entitlement(customer_id, dimension="api_calls"):
        return error_response(403, "Subscription inactive. Please renew via AWS Marketplace.")

    # Check tenant-level quota (hard limit, not entitlement)
    quota = get_tenant_quota(org_id)
    usage = get_current_period_usage(org_id)

    if usage.get("api_calls", 0) >= quota.get("max_api_calls", float("inf")):
        return error_response(429, "API call quota exceeded. Upgrade your plan.")

    # Proceed with request
    return None  # No error, continue to handler
```

---

## Edge Cases

### Customer Subscribes but Never Visits Registration Page

This happens when:
- Customer's browser crashes after subscribing
- Customer closes the tab before the redirect completes
- Network error during redirect

**Detection**: `subscribe-success` SNS arrives but no tenant has the `CustomerIdentifier`.

**Handling**:
1. Create a `pending_registration` tenant (shown in handler above)
2. Customer can re-visit the Marketplace listing and click "Set Up Your Account" to trigger a new redirect with a fresh token
3. The fulfillment handler checks for existing tenants by `CustomerIdentifier` and completes setup

### Customer Unsubscribes While Having Active Data

**Policy**:
- Immediately: Disable API keys, stop accepting new messages, stop metering
- 30 days: Keep all data accessible (read-only) via a special export endpoint
- 30-90 days: Archive data to S3 Glacier Deep Archive
- 90 days: Permanently delete all data

**Implementation**:
1. `unsubscribe-pending`: Set tenant status to `cancelling`, send data export notification
2. `unsubscribe-success`: Set status to `cancelled`, disable API keys, set S3 lifecycle to transition to Glacier at day 30
3. DynamoDB TTL on all tenant items: set to `cancelled_at + 90 days`

### Customer Upgrades Mid-Cycle

- `entitlement-updated` SNS fires
- Fetch new entitlements, update tenant quotas immediately
- No data migration needed -- entitlements just change the included amounts and overage rates
- Previous month's usage is billed at the old tier's rates
- New month's usage is billed at the new tier's rates

### Customer Downgrades

- Same flow as upgrade
- If current usage exceeds new tier's included amounts, the difference is billed as overage
- If current inbox count exceeds new tier's limit, existing inboxes are grandfathered but no new inboxes can be created until count is below the limit

---

## GOTCHA: ResolveCustomer Token Expiration

> **The `x-amzn-marketplace-token` received at the fulfillment URL expires within minutes (typically 5 minutes, but not officially documented). You MUST call `ResolveCustomer` immediately in the request handler. Do not queue the token for async processing.**

If the token expires, the customer must return to the AWS Marketplace and click "Set Up Your Account" again to generate a new token.

---

## GOTCHA: Disbursement Timing

> **AWS disburses revenue NET 30-60 days after the customer billing period closes.** This means:
> - A customer subscribes in April
> - AWS bills them at end of April
> - AWS disburses to your bank account in June (April bill + 30-60 days)
>
> Plan cash flow accordingly. Early-stage companies should factor this delay into runway calculations.

---

## Data Retention Policy

| State | Duration | Data Access | Storage |
|-------|----------|-------------|---------|
| Active | Indefinite | Full read/write via API | DynamoDB + S3 Standard |
| Cancelling (unsubscribe-pending) | Until unsubscribe-success | Full read/write via API | DynamoDB + S3 Standard |
| Cancelled | 0-30 days post-cancellation | Read-only export endpoint | DynamoDB + S3 Standard |
| Archived | 30-90 days post-cancellation | No API access, support request only | S3 Glacier Deep Archive |
| Deleted | >90 days post-cancellation | Permanently deleted | None |
