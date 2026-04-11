# Resource Quotas

This document covers the complete resource quota system in AgentMail -- how quotas are structured, enforced, cached, reset, and how they interact with tier upgrades, downgrades, and overage billing.

---

## Quota Hierarchy

Quotas resolve through a four-level hierarchy. Each level can restrict (but never expand beyond) the level above it:

```
Platform Defaults (hardcoded ceiling -- protects infrastructure)
    |
    v
Tier Limits (determined by subscription tier -- Free/Pro/Business/Scale/Enterprise)
    |
    v
Org Overrides (custom limits for enterprise customers -- stored in DynamoDB)
    |
    v
Pod Sub-Quotas (per-pod limits set by org admin -- subset of org quota)
```

Resolution order: when checking a quota, the system uses the **most restrictive** value across all applicable levels. Platform defaults are the absolute ceiling. Tier limits are the standard for that plan. Org overrides can raise limits above tier (for enterprise deals) or lower them. Pod sub-quotas further restrict within a pod.

---

## Complete Quota Object

Every organization has a quota object stored in DynamoDB. Here is the full schema with all fields:

```json
{
  "org_id": "org_01HXYZ1234567890ABCDEFGHJK",
  "tier": "pro",
  "quotas": {
    "max_pods": 3,
    "max_inboxes_per_pod": 100,
    "max_inboxes_total": 25,
    "max_emails_per_month": 10000,
    "max_emails_per_day": 1000,
    "max_email_size_mb": 25,
    "max_attachment_size_mb": 10,
    "max_attachments_per_email": 10,
    "max_webhooks": 10,
    "max_websocket_connections": 5,
    "max_api_keys": 5,
    "max_custom_domains": 3,
    "max_api_rate_per_second": 50,
    "max_storage_mb": 1024,
    "retention_days": 90,
    "ai_search_queries_per_month": 500,
    "ai_categorizations_per_month": 2000,
    "ai_extractions_per_month": 500,
    "features": {
      "semantic_search": true,
      "categorization": true,
      "extraction": true,
      "imap_smtp": false,
      "pods": true,
      "custom_domains": true,
      "bulk_send": true,
      "long_poll": true,
      "otp_extraction": true,
      "mcp_server": true
    }
  },
  "overrides": {}
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `max_pods` | int | Maximum number of pods the org can create |
| `max_inboxes_per_pod` | int | Maximum inboxes within a single pod |
| `max_inboxes_total` | int | Maximum inboxes across all pods in the org |
| `max_emails_per_month` | int | Total emails (sent + received) per calendar month |
| `max_emails_per_day` | int | Total emails (sent + received) per day |
| `max_email_size_mb` | int | Maximum size of a single email (headers + body + attachments) |
| `max_attachment_size_mb` | int | Maximum size of a single attachment |
| `max_attachments_per_email` | int | Maximum number of attachments on a single email |
| `max_webhooks` | int | Maximum webhook endpoints across all pods |
| `max_websocket_connections` | int | Maximum concurrent WebSocket connections |
| `max_api_keys` | int | Maximum API keys (org-scoped + pod-scoped combined) |
| `max_custom_domains` | int | Maximum verified custom domains |
| `max_api_rate_per_second` | int | Maximum API requests per second |
| `max_storage_mb` | int | Total storage for email bodies and attachments |
| `retention_days` | int | How long messages are retained before auto-deletion |
| `ai_search_queries_per_month` | int | Semantic search queries per month |
| `ai_categorizations_per_month` | int | AI email categorizations per month |
| `ai_extractions_per_month` | int | AI data extractions per month |
| `features` | object | Boolean feature flags gated by tier |

### Feature Flags

| Feature | Description | Free | Pro | Business | Scale | Enterprise |
|---------|-------------|------|-----|----------|-------|------------|
| `semantic_search` | AI-powered email search | No | Yes | Yes | Yes | Yes |
| `categorization` | AI email categorization | No | Yes | Yes | Yes | Yes |
| `extraction` | AI data extraction from emails | No | Yes | Yes | Yes | Yes |
| `imap_smtp` | IMAP/SMTP protocol access | No | No | Yes | Yes | Yes |
| `pods` | Multiple pods (beyond Default) | No | Yes | Yes | Yes | Yes |
| `custom_domains` | Verified custom sending domains | No | Yes | Yes | Yes | Yes |
| `bulk_send` | Batch email sending API | No | Yes | Yes | Yes | Yes |
| `long_poll` | Long-polling for new messages | Yes | Yes | Yes | Yes | Yes |
| `otp_extraction` | OTP/verification code extraction | Yes | Yes | Yes | Yes | Yes |
| `mcp_server` | Model Context Protocol server | No | Yes | Yes | Yes | Yes |

---

## Tier Quota Defaults

### SaaS Tiers (billing_channel = "stripe")

| Quota | Free | Pro | Business | Scale | Enterprise |
|-------|------|-----|----------|-------|------------|
| `max_pods` | 1 | 3 | 10 | Unlimited | Unlimited |
| `max_inboxes_total` | 5 | 25 | 100 | 1,000 | 100,000+ |
| `max_inboxes_per_pod` | 5 | 25 | 50 | 500 | 10,000+ |
| `max_emails_per_month` | 500 | 10,000 | 50,000 | 500,000 | 5,000,000+ |
| `max_emails_per_day` | 50 | 1,000 | 5,000 | 50,000 | 500,000+ |
| `max_email_size_mb` | 10 | 25 | 25 | 50 | 50 |
| `max_webhooks` | 2 | 10 | 50 | 200 | 1,000+ |
| `max_websocket_connections` | 1 | 5 | 20 | 100 | 500+ |
| `max_api_keys` | 1 | 5 | 20 | 50 | 200+ |
| `max_custom_domains` | 0 | 3 | 10 | 50 | 200+ |
| `max_api_rate_per_second` | 10 | 50 | 200 | 1,000 | 5,000+ |
| `max_storage_mb` | 100 | 1,024 | 10,240 | 102,400 | 1,048,576+ |
| `retention_days` | 30 | 90 | 365 | 730 | Unlimited |
| `ai_search_queries_per_month` | 0 | 500 | 5,000 | 50,000 | Unlimited |
| `ai_categorizations_per_month` | 0 | 2,000 | 20,000 | 200,000 | Unlimited |
| `ai_extractions_per_month` | 0 | 500 | 5,000 | 50,000 | Unlimited |

### Marketplace Tiers (billing_channel = "marketplace")

| Quota | Starter | Growth | Scale | Enterprise |
|-------|---------|--------|-------|------------|
| `max_pods` | 3 | 20 | 100 | 1,000+ |
| `max_inboxes_total` | 10 | 100 | 1,000 | 100,000+ |
| `max_emails_per_month` | 5,000 | 50,000 | 500,000 | 5,000,000+ |
| `max_api_rate_per_second` | 25 | 100 | 500 | 2,500+ |
| `retention_days` | 90 | 365 | 730 | Unlimited |

---

## Quota Enforcement Implementation

Quotas are enforced at multiple layers, each optimized for the type of check being performed.

### Architecture Overview

```
API Request
    |
    v
API Gateway Usage Plan (rate limit: rps/burst)
    |
    v
Lambda Authorizer (resolve API key → org_id, tier, pod_id)
    |
    v
Quota Middleware (pre-handler check)
    |
    |-- Feature check: is this feature enabled for the tier?
    |     └─ Source: Redis cache (5 min TTL) ← DynamoDB quota record
    |
    |-- Rate check: has the per-second/per-day limit been hit?
    |     └─ Source: Redis atomic counter (INCR + EXPIRE)
    |
    |-- Resource count check: has the max resource count been hit?
    |     └─ Source: DynamoDB count query (or cached count)
    |
    |-- Monthly counter check: has the monthly quota been hit?
    |     └─ Source: DynamoDB atomic counter
    |
    v
Handler (business logic)
    |
    v
Post-handler (increment usage counters)
```

### Pre-Request Checks: Quota Middleware

Every API request passes through quota middleware that runs before the handler:

```python
import json
import time
from functools import wraps

import boto3
import redis

redis_client = redis.Redis(host="agentmail-redis.xxxxx.use1.cache.amazonaws.com")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("agentmail-main")

QUOTA_CACHE_TTL = 300  # 5 minutes


def get_cached_quotas(org_id: str) -> dict:
    """
    Fetch org quotas from Redis cache, falling back to DynamoDB.
    Cache TTL is 5 minutes -- quota changes take up to 5 min to take effect.
    """
    cache_key = f"{org_id}:quotas"
    cached = redis_client.get(cache_key)

    if cached:
        return json.loads(cached)

    # Cache miss -- read from DynamoDB
    response = table.get_item(
        Key={"PK": f"ORG#{org_id}", "SK": "QUOTAS"}
    )
    quotas = response.get("Item", {})

    if not quotas:
        # No custom quotas -- use tier defaults
        org = table.get_item(
            Key={"PK": f"ORG#{org_id}", "SK": "METADATA"}
        ).get("Item", {})
        tier = org.get("tier", "free")
        quotas = get_tier_defaults(tier)

    # Apply org overrides
    overrides = quotas.get("overrides", {})
    merged = {**quotas.get("quotas", {}), **overrides}
    quotas["quotas"] = merged

    # Cache in Redis
    redis_client.setex(cache_key, QUOTA_CACHE_TTL, json.dumps(quotas))

    return quotas


def quota_check(resource_type: str = None, feature: str = None, counter: str = None):
    """
    Decorator that performs quota checks before the handler executes.

    Args:
        resource_type: Check resource count (e.g., "inboxes", "webhooks")
        feature: Check feature flag (e.g., "semantic_search", "imap_smtp")
        counter: Check usage counter (e.g., "emails_per_day", "emails_per_month")
    """
    def decorator(handler):
        @wraps(handler)
        def wrapper(event, context):
            org_id = event["requestContext"]["authorizer"]["org_id"]
            quotas = get_cached_quotas(org_id)
            quota_values = quotas.get("quotas", {})
            features = quota_values.get("features", {})

            # Feature gate check
            if feature and not features.get(feature, False):
                tier = quotas.get("tier", "free")
                required_tier = get_minimum_tier_for_feature(feature)
                return {
                    "statusCode": 403,
                    "body": json.dumps({
                        "error": "feature_not_available",
                        "feature": feature,
                        "current_tier": tier,
                        "required_tier": required_tier,
                        "upgrade_url": f"https://agentmail.dev/settings/billing?upgrade_to={required_tier}",
                    }),
                }

            # Resource count check
            if resource_type:
                quota_key = f"max_{resource_type}"
                max_allowed = quota_values.get(quota_key)

                if max_allowed is not None:
                    current_count = count_resources(org_id, resource_type)
                    if current_count >= max_allowed:
                        return {
                            "statusCode": 429,
                            "body": json.dumps({
                                "error": "quota_exceeded",
                                "quota": quota_key,
                                "current": current_count,
                                "limit": max_allowed,
                                "upgrade_url": "https://agentmail.dev/settings/billing",
                            }),
                        }

            # Usage counter check
            if counter:
                check_result = check_usage_counter(org_id, counter, quota_values)
                if check_result:
                    return check_result

            return handler(event, context)
        return wrapper
    return decorator


# Usage example:
@quota_check(resource_type="inboxes")
def create_inbox_handler(event, context):
    """Create a new inbox -- quota_check ensures we're under the inbox limit."""
    # ... handler logic ...
    pass


@quota_check(feature="semantic_search", counter="ai_search_queries_per_month")
def search_handler(event, context):
    """Search emails -- quota_check ensures the feature is enabled and under monthly limit."""
    # ... handler logic ...
    pass
```

### Counter Tracking: Redis Atomic Counters

Rate-sensitive quotas (emails per day, API calls per second) use Redis atomic counters for low-latency enforcement:

```python
def check_rate_limit(org_id: str, limit_per_second: int) -> dict | None:
    """
    Check per-second rate limit using Redis sliding window.
    Returns an error response if rate limited, None if allowed.
    """
    now = time.time()
    window_key = f"{org_id}:rate:api:{int(now)}"

    # Atomic increment + expire in one pipeline
    pipe = redis_client.pipeline()
    pipe.incr(window_key)
    pipe.expire(window_key, 2)  # Expire after 2 seconds (current + previous window)
    results = pipe.execute()

    current_count = results[0]

    if current_count > limit_per_second:
        return {
            "statusCode": 429,
            "headers": {"Retry-After": "2"},
            "body": json.dumps({
                "error": "rate_limited",
                "retry_after": 2,
            }),
        }

    return None


def check_daily_counter(org_id: str, counter_name: str, daily_limit: int) -> dict | None:
    """
    Check daily usage counter using Redis atomic counter.
    Counter key includes the date so it resets at midnight UTC.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counter_key = f"{org_id}:daily:{counter_name}:{today}"

    # Atomic increment
    current = redis_client.incr(counter_key)

    if current == 1:
        # First increment today -- set expiry to end of day + 1 hour buffer
        seconds_until_midnight = seconds_until_utc_midnight()
        redis_client.expire(counter_key, seconds_until_midnight + 3600)

    if current > daily_limit:
        # Decrement back (we incremented optimistically)
        redis_client.decr(counter_key)
        return {
            "statusCode": 429,
            "body": json.dumps({
                "error": "quota_exceeded",
                "quota": f"max_{counter_name}",
                "current": current - 1,
                "limit": daily_limit,
                "resets_at": f"{(datetime.now(timezone.utc) + timedelta(days=1)).strftime('%Y-%m-%d')}T00:00:00Z",
                "upgrade_url": "https://agentmail.dev/settings/billing",
            }),
        }

    return None
```

### Monthly Counters: DynamoDB Atomic Counters

Monthly counters (emails per month, AI operations per month) use DynamoDB atomic updates because they need durability across Redis restarts:

```python
def increment_monthly_counter(org_id: str, counter_name: str, amount: int = 1) -> int:
    """
    Atomically increment a monthly usage counter in DynamoDB.
    Returns the new counter value.
    """
    month = datetime.now(timezone.utc).strftime("%Y-%m")

    response = table.update_item(
        Key={
            "PK": f"ORG#{org_id}",
            "SK": f"USAGE#MONTHLY#{month}",
        },
        UpdateExpression="SET #counter = if_not_exists(#counter, :zero) + :amount, "
                         "updated_at = :now",
        ExpressionAttributeNames={"#counter": counter_name},
        ExpressionAttributeValues={
            ":zero": 0,
            ":amount": amount,
            ":now": datetime.now(timezone.utc).isoformat(),
        },
        ReturnValues="UPDATED_NEW",
    )

    return int(response["Attributes"][counter_name])


def check_monthly_counter(org_id: str, counter_name: str, monthly_limit: int) -> dict | None:
    """
    Check if a monthly counter has been exceeded.
    Reads from DynamoDB (not Redis) for accuracy on monthly totals.
    """
    month = datetime.now(timezone.utc).strftime("%Y-%m")

    response = table.get_item(
        Key={
            "PK": f"ORG#{org_id}",
            "SK": f"USAGE#MONTHLY#{month}",
        },
        ProjectionExpression=counter_name,
    )

    current = int(response.get("Item", {}).get(counter_name, 0))

    if current >= monthly_limit:
        # Calculate reset date (1st of next month at midnight UTC)
        now = datetime.now(timezone.utc)
        if now.month == 12:
            reset_date = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            reset_date = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)

        return {
            "statusCode": 429,
            "body": json.dumps({
                "error": "quota_exceeded",
                "quota": counter_name,
                "current": current,
                "limit": monthly_limit,
                "resets_at": reset_date.isoformat(),
                "upgrade_url": "https://agentmail.dev/settings/billing",
            }),
        }

    return None
```

### Storage Tracking

Storage is tracked via a DynamoDB counter that is updated on every message store and delete:

```python
def update_storage_counter(org_id: str, size_bytes: int, operation: str = "add"):
    """
    Update the org's storage counter. Called on message store (add) and delete (subtract).
    """
    amount = size_bytes if operation == "add" else -size_bytes

    table.update_item(
        Key={
            "PK": f"ORG#{org_id}",
            "SK": "USAGE#STORAGE",
        },
        UpdateExpression="SET storage_bytes = if_not_exists(storage_bytes, :zero) + :amount, "
                         "updated_at = :now",
        ExpressionAttributeValues={
            ":zero": 0,
            ":amount": amount,
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )


def check_storage_quota(org_id: str, incoming_size_bytes: int, max_storage_mb: int) -> dict | None:
    """Check if storing a new message would exceed the storage quota."""
    response = table.get_item(
        Key={"PK": f"ORG#{org_id}", "SK": "USAGE#STORAGE"},
        ProjectionExpression="storage_bytes",
    )

    current_bytes = int(response.get("Item", {}).get("storage_bytes", 0))
    max_bytes = max_storage_mb * 1024 * 1024

    if current_bytes + incoming_size_bytes > max_bytes:
        return {
            "statusCode": 429,
            "body": json.dumps({
                "error": "quota_exceeded",
                "quota": "max_storage_mb",
                "current_mb": round(current_bytes / (1024 * 1024), 2),
                "limit_mb": max_storage_mb,
                "upgrade_url": "https://agentmail.dev/settings/billing",
            }),
        }

    return None
```

### Resource Count Checks

For resource limits (inboxes, webhooks, API keys), enforcement queries DynamoDB for the current count:

```python
def count_resources(org_id: str, resource_type: str) -> int:
    """Count existing resources of a given type for an organization."""
    sk_prefix_map = {
        "inboxes": "POD#",           # Inboxes are under pods
        "inboxes_total": "INBOX#",   # GSI for total inbox count
        "webhooks": "WEBHOOK#",
        "api_keys": "APIKEY#",
        "custom_domains": "DOMAIN#",
        "pods": "POD#",
    }

    prefix = sk_prefix_map.get(resource_type)
    if not prefix:
        raise ValueError(f"Unknown resource type: {resource_type}")

    response = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"ORG#{org_id}",
            ":prefix": prefix,
        },
        Select="COUNT",
    )

    return response["Count"]
```

---

## Quota Enforcement Responses

### 403: Feature Not Available

Returned when the org's tier does not include a requested feature:

```json
{
  "error": "feature_not_available",
  "feature": "semantic_search",
  "current_tier": "free",
  "required_tier": "pro",
  "upgrade_url": "https://agentmail.dev/settings/billing?upgrade_to=pro"
}
```

### 429: Quota Exceeded

Returned when a resource or usage quota has been reached:

```json
{
  "error": "quota_exceeded",
  "quota": "max_emails_per_month",
  "current": 10000,
  "limit": 10000,
  "resets_at": "2026-05-01T00:00:00Z",
  "upgrade_url": "https://agentmail.dev/settings/billing"
}
```

### 429: Rate Limited

Returned when the per-second API rate limit is exceeded:

```json
{
  "error": "rate_limited",
  "retry_after": 2
}
```

The `Retry-After` header is also set on the HTTP response.

---

## Quota Reset Schedule

| Counter Type | Reset Behavior |
|--------------|---------------|
| Per-second rate limit | Sliding window, resets every second |
| Daily counters (emails/day, API calls/day) | Reset at midnight UTC |
| Monthly counters (emails/month, AI ops/month) | Reset at midnight UTC on the 1st of each month |
| Resource counts (inboxes, webhooks, keys) | Not time-based -- decrease when resources are deleted |
| Storage | Not time-based -- decreases when messages are deleted |

Monthly counter reset is handled implicitly by the key structure (`USAGE#MONTHLY#2026-04`). When the month changes, the new key has no existing value and starts at zero. Old monthly records are retained for 13 months for billing reconciliation, then deleted via DynamoDB TTL.

---

## Overage Handling

### Free Tier (billing_channel = "stripe", tier = "free")

Hard block. No overage is permitted. When any quota is reached, the API returns 429 until usage drops below the limit (for rate limits) or the counter resets (for daily/monthly quotas).

### Paid SaaS Tiers (billing_channel = "stripe", tier in ["pro", "business", "scale"])

10% grace period above the quota limit. During the grace period, the API continues to function normally but a warning header is added to every response:

```
X-AgentMail-Quota-Warning: max_emails_per_month usage at 105% (10500/10000). Grace period active. Overage will be billed.
```

Once the 10% grace is exhausted (110% of quota), the API returns 429.

Grace period usage is billed as overage via Stripe:

```python
def report_overage_to_stripe(org_id: str, overage_units: int, dimension: str):
    """Report overage usage to Stripe for billing."""
    org = get_org(org_id)
    stripe_subscription_id = org.get("stripe_subscription_id")
    stripe_subscription_item_id = get_metered_item_id(stripe_subscription_id, dimension)

    stripe.SubscriptionItem.create_usage_record(
        stripe_subscription_item_id,
        quantity=overage_units,
        timestamp=int(time.time()),
        action="increment",
    )
```

### Marketplace Tiers (billing_channel = "marketplace")

No hard block. All usage beyond the tier's included allocation is metered and billed via `BatchMeterUsage`. The customer is billed by AWS for overage at the per-unit rate defined in the Marketplace listing.

```python
def check_quota_with_overage(org_id: str, counter_name: str, limit: int, current: int) -> dict | None:
    """
    Quota check that respects billing channel overage policies.
    """
    quotas = get_cached_quotas(org_id)
    billing_channel = quotas.get("billing_channel", "stripe")
    tier = quotas.get("tier", "free")

    if current < limit:
        return None  # Under quota, allow

    if billing_channel == "marketplace":
        # Marketplace: no hard block, metered overage
        return None

    if billing_channel == "stripe" and tier == "free":
        # Free tier: hard block
        return make_quota_exceeded_response(counter_name, current, limit)

    if billing_channel == "stripe" and tier != "free":
        # Paid SaaS: 10% grace
        grace_limit = int(limit * 1.1)
        if current < grace_limit:
            return None  # Within grace period (warning header added separately)
        else:
            return make_quota_exceeded_response(counter_name, current, limit)

    return make_quota_exceeded_response(counter_name, current, limit)
```

---

## Quota Changes on Tier Upgrade/Downgrade

### Upgrade (Immediate Effect)

When a user upgrades their tier:

1. Stripe webhook or Marketplace SNS notification triggers the tier change handler
2. The org record in DynamoDB is updated with the new tier
3. The Redis quota cache is invalidated immediately
4. New limits take effect on the very next API call

```python
def handle_tier_upgrade(org_id: str, new_tier: str):
    """Apply new tier quotas immediately on upgrade."""
    old_quotas = get_cached_quotas(org_id)
    new_quota_defaults = get_tier_defaults(new_tier)

    # Preserve any admin overrides -- they take precedence over tier defaults
    overrides = old_quotas.get("overrides", {})

    # Update DynamoDB
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "QUOTAS"},
        UpdateExpression="SET quotas = :quotas, tier = :tier, updated_at = :now",
        ExpressionAttributeValues={
            ":quotas": new_quota_defaults,
            ":tier": new_tier,
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Invalidate Redis cache -- new quotas will be fetched on next request
    redis_client.delete(f"{org_id}:quotas")
    redis_client.delete(f"{org_id}:entitlement")

    publish_event("org.tier_changed", {
        "org_id": org_id,
        "old_tier": old_quotas.get("tier"),
        "new_tier": new_tier,
    })
```

### Downgrade (Graceful Enforcement)

When a user downgrades their tier:

1. New (lower) limits are stored in DynamoDB
2. Redis cache is invalidated
3. **Existing resources are preserved** -- no inboxes, webhooks, or domains are deleted
4. The user cannot create new resources of any type where the current count exceeds the new limit
5. Once they delete resources to get under the new limit, they can create again

```python
def handle_tier_downgrade(org_id: str, new_tier: str):
    """
    Apply new tier quotas on downgrade. Existing resources are preserved,
    but no new creation is allowed for resource types that are over the new limit.
    """
    new_quota_defaults = get_tier_defaults(new_tier)

    # Check what's currently over the new limits
    over_limit_resources = []
    for resource_type in ["inboxes_total", "pods", "webhooks", "api_keys", "custom_domains"]:
        current = count_resources(org_id, resource_type)
        new_limit = new_quota_defaults.get(f"max_{resource_type}", float("inf"))
        if current > new_limit:
            over_limit_resources.append({
                "resource": resource_type,
                "current": current,
                "new_limit": new_limit,
            })

    # Update DynamoDB with new quotas
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "QUOTAS"},
        UpdateExpression="SET quotas = :quotas, tier = :tier, "
                         "over_limit_resources = :over, updated_at = :now",
        ExpressionAttributeValues={
            ":quotas": new_quota_defaults,
            ":tier": new_tier,
            ":over": over_limit_resources,
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )

    redis_client.delete(f"{org_id}:quotas")

    # Notify the user about resources over the new limit
    if over_limit_resources:
        send_over_limit_notification(org_id, over_limit_resources)

    publish_event("org.tier_changed", {
        "org_id": org_id,
        "new_tier": new_tier,
        "over_limit_resources": over_limit_resources,
    })
```

---

## Admin Quota Overrides

Enterprise customers may have custom quotas negotiated as part of their contract. These overrides are stored on the quota record and take precedence over tier defaults:

```python
def set_quota_overrides(org_id: str, overrides: dict):
    """
    Set custom quota overrides for an enterprise customer.
    Overrides take precedence over tier defaults.
    Only callable by AgentMail platform admins.

    Example overrides:
    {
        "max_inboxes_total": 500000,
        "max_emails_per_month": 20000000,
        "max_api_rate_per_second": 10000,
        "retention_days": -1  # -1 = unlimited
    }
    """
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": "QUOTAS"},
        UpdateExpression="SET overrides = :overrides, updated_at = :now",
        ExpressionAttributeValues={
            ":overrides": overrides,
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Invalidate cache
    redis_client.delete(f"{org_id}:quotas")

    publish_event("org.quotas_overridden", {
        "org_id": org_id,
        "overrides": overrides,
    })
```

### DynamoDB Record with Overrides

```json
{
  "PK": "ORG#org_01HXYZ1234567890ABCDEFGHJK",
  "SK": "QUOTAS",
  "org_id": "org_01HXYZ1234567890ABCDEFGHJK",
  "tier": "scale",
  "quotas": {
    "max_pods": 100,
    "max_inboxes_total": 1000,
    "max_emails_per_month": 500000,
    "max_api_rate_per_second": 500
  },
  "overrides": {
    "max_inboxes_total": 500000,
    "max_emails_per_month": 20000000,
    "max_api_rate_per_second": 10000,
    "retention_days": -1
  },
  "updated_at": "2026-04-10T14:30:00.000Z"
}
```

At resolution time, `overrides` values replace `quotas` values:

```python
def resolve_quotas(quota_record: dict) -> dict:
    """Merge tier defaults with org overrides. Overrides win."""
    base = quota_record.get("quotas", {})
    overrides = quota_record.get("overrides", {})
    return {**base, **overrides}
```

---

## Monitoring

### CloudWatch Custom Metrics

Per-org quota utilization is published to CloudWatch for monitoring and alerting:

```python
def publish_quota_metrics(org_id: str):
    """
    Publish quota utilization metrics to CloudWatch.
    Called by a scheduled Lambda every 5 minutes.
    """
    quotas = get_cached_quotas(org_id)
    quota_values = quotas.get("quotas", {})

    metrics = []

    # Resource utilization metrics
    for resource_type, quota_key in [
        ("inboxes_total", "max_inboxes_total"),
        ("pods", "max_pods"),
        ("webhooks", "max_webhooks"),
        ("api_keys", "max_api_keys"),
        ("custom_domains", "max_custom_domains"),
    ]:
        limit = quota_values.get(quota_key, 0)
        if limit > 0:
            current = count_resources(org_id, resource_type)
            utilization = (current / limit) * 100

            metrics.append({
                "MetricName": "QuotaUtilization",
                "Dimensions": [
                    {"Name": "OrgId", "Value": org_id},
                    {"Name": "QuotaType", "Value": quota_key},
                ],
                "Value": utilization,
                "Unit": "Percent",
            })

    # Monthly counter utilization
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    monthly_usage = table.get_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"USAGE#MONTHLY#{month}"}
    ).get("Item", {})

    for counter, quota_key in [
        ("emails_sent", "max_emails_per_month"),
        ("ai_search_queries", "ai_search_queries_per_month"),
        ("ai_categorizations", "ai_categorizations_per_month"),
        ("ai_extractions", "ai_extractions_per_month"),
    ]:
        limit = quota_values.get(quota_key, 0)
        if limit > 0:
            current = int(monthly_usage.get(counter, 0))
            utilization = (current / limit) * 100

            metrics.append({
                "MetricName": "QuotaUtilization",
                "Dimensions": [
                    {"Name": "OrgId", "Value": org_id},
                    {"Name": "QuotaType", "Value": quota_key},
                ],
                "Value": utilization,
                "Unit": "Percent",
            })

    # Publish to CloudWatch
    cloudwatch = boto3.client("cloudwatch")
    cloudwatch.put_metric_data(
        Namespace="AgentMail/Quotas",
        MetricData=metrics,
    )
```

### CloudWatch Alarms

Alarms are created for each organization at three thresholds:

| Threshold | Action |
|-----------|--------|
| 80% utilization | Informational: log to CloudWatch Logs, visible in admin dashboard |
| 90% utilization | Warning: email notification to org admin, Slack alert to AgentMail ops |
| 100% utilization | Critical: email notification to org admin with upgrade CTA, PagerDuty alert for enterprise customers |

```python
def create_quota_alarms(org_id: str, quota_key: str, limit: int):
    """Create CloudWatch alarms for a specific quota at 80%, 90%, and 100%."""
    cloudwatch = boto3.client("cloudwatch")

    for threshold, severity in [(80, "info"), (90, "warning"), (100, "critical")]:
        cloudwatch.put_metric_alarm(
            AlarmName=f"agentmail-{org_id}-{quota_key}-{threshold}pct",
            MetricName="QuotaUtilization",
            Namespace="AgentMail/Quotas",
            Dimensions=[
                {"Name": "OrgId", "Value": org_id},
                {"Name": "QuotaType", "Value": quota_key},
            ],
            Statistic="Maximum",
            Period=300,
            EvaluationPeriods=1,
            Threshold=threshold,
            ComparisonOperator="GreaterThanOrEqualToThreshold",
            AlarmActions=[
                SNS_TOPICS[severity],
            ],
            Tags=[
                {"Key": "org_id", "Value": org_id},
                {"Key": "severity", "Value": severity},
            ],
        )
```
