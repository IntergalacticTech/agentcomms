# Multi-Tenancy Architecture

AgentMail is a multi-tenant platform where every layer of the stack enforces tenant isolation. The tenant model is hierarchical: **Organization** (top-level billing entity, linked to either a Stripe subscription or an AWS Marketplace contract) contains **Pods** (logical groupings that platform builders use to isolate their own customers) which contain **Inboxes** (individual email addresses). Every data store, compute layer, and network path enforces isolation at the Organization level, with optional stricter isolation at the Pod level.

---

## Billing Channel

Every organization has a `billing_channel` field that determines how usage is billed and how features are gated. Both channels use the same tenant isolation, data model, and API surface.

### Values

| Value | Description |
|-------|-------------|
| `"stripe"` | Direct SaaS customer. Signed up at agentmail.dev. Billed via Stripe. |
| `"marketplace"` | AWS Marketplace customer. Billed via AWS Marketplace metering. |

### What billing_channel Determines

| Aspect | `"stripe"` | `"marketplace"` |
|--------|-----------|-----------------|
| **Usage metering** | Stripe Usage Records (reported via Stripe API) | `BatchMeterUsage` (reported via AWS Marketplace Metering API) |
| **Feature gating source** | Stripe subscription tier (Free/Pro/Business/Scale) | Marketplace entitlements (Starter/Growth/Scale/Enterprise) |
| **Support SLA** | Community (Free), Email (Pro/Business), Priority (Scale) | Per-contract SLA, named TAM for Enterprise |
| **Free tier** | Available (permanent, $0) | Not available (31-day free trial only) |
| **AI features** | Gated by tier (none on Free, graduated on paid) | Included on all tiers |

### DynamoDB Organization Entity

The `billing_channel` is stored on the Organization item:

```json
{
  "PK": "ORG#01HXYZ1234567890ABCDEFGHJK",
  "SK": "METADATA",
  "entity_type": "Organization",
  "org_id": "01HXYZ1234567890ABCDEFGHJK",
  "name": "Acme Corp",
  "billing_channel": "stripe",
  "stripe_customer_id": "cus_abc123",
  "marketplace_customer_id": null,
  "tier": "pro",
  "status": "active",
  "created_at": "2026-01-15T09:00:00.000Z"
}
```

When an organization migrates from SaaS to Marketplace, the `billing_channel` updates from `"stripe"` to `"marketplace"`, the `marketplace_customer_id` is populated, and the `stripe_customer_id` is retained for historical reference. All other data (pods, inboxes, messages, API keys) remains unchanged.

---

## Tenant Model

```
Organization (ORG#{org_id})
    |
    | -- Billing entity linked to AWS Marketplace CustomerIdentifier
    | -- API keys scoped to this org
    | -- Resource quotas enforced at this level
    | -- Data isolation boundary (hard boundary)
    |
    +-- Pod (POD#{pod_id})
    |     |
    |     | -- Logical grouping within an org
    |     | -- Optional webhook configuration
    |     | -- Optional per-pod quotas (subset of org quota)
    |     | -- Soft isolation boundary (configurable)
    |     |
    |     +-- Inbox (INBOX#{inbox_id})
    |     |     |-- Email address (e.g., agent-123@pods.agentmail.aws)
    |     |     |-- Messages, Threads, Drafts, Attachments
    |     |     |-- Per-inbox allow/block lists
    |     |     |-- Per-inbox AI configuration
    |     |
    |     +-- Inbox ...
    |
    +-- Pod ...
```

### Why Pods Exist

Pods solve the "platform within a platform" problem. When an AgentMail customer is itself a platform (e.g., an AI agent framework serving multiple end-customers), pods allow them to create isolated groups of inboxes:

- **One pod per end-customer**: A customer service AI platform creates one pod per company they serve. Each company's email data is isolated from other companies.
- **One pod per team/department**: An enterprise creates pods for sales-agents, support-agents, and ops-agents.
- **One pod per environment**: A developer creates pods for production, staging, and testing.

Pods inherit the parent organization's quotas by default but can have stricter sub-quotas applied.

---

## Data Isolation

### DynamoDB: Partition Key Prefix

All DynamoDB items are prefixed with the organization ID as the partition key. No query can cross organization boundaries.

**Key structure:**
```
PK: ORG#{org_id}
SK: [METADATA | POD#{pod_id} | INBOX#{inbox_id} | MSG#{msg_id} | ...]
```

**IAM condition for Lambda execution roles:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EnforceLeadingKeys",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query"
      ],
      "Resource": "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/agentmail-main",
      "Condition": {
        "ForAllValues:StringLike": {
          "dynamodb:LeadingKeys": ["ORG#${aws:PrincipalTag/org_id}*"]
        }
      }
    }
  ]
}
```

**How this works**: The Lambda authorizer resolves the API key to an organization ID and passes it as a session tag. The Lambda execution role's IAM policy uses `dynamodb:LeadingKeys` condition to ensure the function can only access items where the partition key starts with the authenticated organization's prefix. Even if a code bug constructs a query for the wrong org, IAM denies the request.

**Defense in depth**: The application code also validates `org_id` in every query, but the IAM condition is the hard enforcement layer that cannot be bypassed by application bugs.

### S3: Prefix-Based Isolation

All S3 objects are stored under the organization ID prefix:

```
s3://agentmail-email-bodies/{org_id}/{inbox_id}/{message_id}/body.html
s3://agentmail-attachments/{org_id}/{inbox_id}/{message_id}/{attachment_id}/{filename}
s3://agentmail-exports/{org_id}/export-{timestamp}.zip
```

**Bucket policy enforcing prefix isolation:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EnforceOrgPrefix",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::agentmail-email-bodies/*",
        "arn:aws:s3:::agentmail-attachments/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:PrincipalTag/org_id": ""
        },
        "StringNotLike": {
          "s3:prefix": ["${aws:PrincipalTag/org_id}/*"]
        }
      }
    },
    {
      "Sid": "VPCEndpointOnly",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::agentmail-email-bodies",
        "arn:aws:s3:::agentmail-email-bodies/*",
        "arn:aws:s3:::agentmail-attachments",
        "arn:aws:s3:::agentmail-attachments/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:sourceVpce": "vpce-0abc123def456789"
        }
      }
    }
  ]
}
```

**Pre-signed URLs**: When customers download attachments or email bodies, the API generates pre-signed S3 URLs scoped to their org prefix with a 15-minute expiry. The pre-signed URL contains the org prefix in the path, ensuring cross-tenant access is impossible even if the URL is shared.

### OpenSearch: Mandatory org_id Filter

The OpenSearch search service enforces organization isolation at the query layer. The `org_id` filter is added server-side and is never controllable by the user.

```python
def search_emails(org_id: str, query: str, filters: dict = None) -> list:
    """
    Search emails in OpenSearch. The org_id filter is mandatory and injected
    server-side -- it is NEVER part of the user's query.
    """
    must_clauses = [
        # MANDATORY: org_id filter injected by server, not user-controllable
        {"term": {"org_id.keyword": org_id}},
    ]

    if query:
        must_clauses.append({
            "multi_match": {
                "query": query,
                "fields": ["subject^3", "body", "from_address", "to_addresses"],
            }
        })

    if filters:
        if "pod_id" in filters:
            must_clauses.append({"term": {"pod_id.keyword": filters["pod_id"]}})
        if "inbox_id" in filters:
            must_clauses.append({"term": {"inbox_id.keyword": filters["inbox_id"]}})
        if "date_from" in filters:
            must_clauses.append({"range": {"received_at": {"gte": filters["date_from"]}}})
        if "date_to" in filters:
            must_clauses.append({"range": {"received_at": {"lte": filters["date_to"]}}})
        if "has_attachment" in filters:
            must_clauses.append({"term": {"has_attachment": filters["has_attachment"]}})

    body = {
        "query": {"bool": {"must": must_clauses}},
        "size": filters.get("limit", 20),
        "sort": [{"received_at": {"order": "desc"}}],
    }

    response = opensearch_client.search(
        index="agentmail-emails",
        body=body,
    )

    return [hit["_source"] for hit in response["hits"]["hits"]]
```

### SES: Per-Organization Configuration Sets

Each organization gets a dedicated SES configuration set that enables:
- Per-org sending quotas (isolated from other tenants)
- Per-org reputation tracking (one tenant's spam complaints don't affect others)
- Per-org event destinations (bounce, complaint, delivery notifications)

```python
def create_org_ses_config(org_id: str):
    """Create a dedicated SES configuration set for an organization."""
    ses = boto3.client("sesv2")

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
        ],
    )

    # Add SNS event destination for bounces and complaints
    ses.create_configuration_set_event_destination(
        ConfigurationSetName=config_set_name,
        EventDestinationName=f"{config_set_name}-events",
        EventDestination={
            "Enabled": True,
            "MatchingEventTypes": [
                "BOUNCE", "COMPLAINT", "DELIVERY", "SEND", "REJECT",
            ],
            "SnsDestination": {
                "TopicArn": f"arn:aws:sns:us-east-1:ACCOUNT_ID:agentmail-ses-events"
            },
        },
    )
```

### Redis: Key Prefix Isolation

All Redis keys are prefixed with the organization ID:

```
{org_id}:auth:{key_hash}           → API key metadata cache
{org_id}:rate:{endpoint}:{window}  → Rate limit counter
{org_id}:entitlement               → Cached entitlements
{org_id}:inbox:{inbox_id}:routing  → Inbox routing cache
{org_id}:quota:usage               → Current period usage counters
```

Application code enforces the prefix on all Redis operations. Unlike DynamoDB (where IAM provides a hard boundary), Redis isolation is application-enforced only. This is acceptable because Redis contains only cached/ephemeral data, not primary data.

### Kinesis: Event Tagging

All Kinesis records include the `orgId` field for downstream filtering:

```json
{
  "eventType": "message.received",
  "orgId": "org-abc123",
  "podId": "pod-def456",
  "inboxId": "inbox-ghi789",
  "messageId": "msg-jkl012",
  "timestamp": "2026-04-10T14:23:45Z"
}
```

Consumers (Lambda, Firehose) filter by `orgId` before processing. The partition key is the `orgId`, ensuring all events for an organization are on the same shard and processed in order.

---

## Noisy Neighbor Protection

### API Gateway: Per-API-Key Throttle via Usage Plans

Each API key is associated with a usage plan that enforces per-tenant rate limits:

```python
def create_usage_plan_for_tier(tier: str) -> dict:
    """Create an API Gateway usage plan for a pricing tier."""
    tier_limits = {
        "starter": {"burstLimit": 50, "rateLimit": 25},     # 25 rps, 50 burst
        "growth": {"burstLimit": 200, "rateLimit": 100},    # 100 rps, 200 burst
        "scale": {"burstLimit": 1000, "rateLimit": 500},    # 500 rps, 1000 burst
        "enterprise": {"burstLimit": 5000, "rateLimit": 2500},  # 2500 rps, 5000 burst
    }

    limits = tier_limits[tier]

    apigw = boto3.client("apigateway")
    response = apigw.create_usage_plan(
        name=f"agentmail-{tier}",
        description=f"AgentMail {tier.title()} tier rate limits",
        throttle={
            "burstLimit": limits["burstLimit"],
            "rateLimit": limits["rateLimit"],
        },
        quota={
            # Monthly API call quota (per pricing tier)
            "limit": {
                "starter": 10000,
                "growth": 50000,
                "scale": 500000,
                "enterprise": 5000000,
            }[tier],
            "period": "MONTH",
        },
        apiStages=[
            {
                "apiId": os.environ["API_ID"],
                "stage": "v1",
            }
        ],
    )
    return response
```

### SQS: Per-Organization Message Groups

For webhook delivery and event processing, SQS FIFO queues use the `org_id` as the message group ID. This ensures:
- Events within an organization are processed in order
- One organization's backlog does not block another organization's events
- SQS distributes processing capacity fairly across message groups

```python
sqs.send_message(
    QueueUrl=WEBHOOK_QUEUE_URL,
    MessageBody=json.dumps(event),
    MessageGroupId=org_id,  # Isolates processing per tenant
    MessageDeduplicationId=f"{org_id}-{event_id}",
)
```

### SES: Per-Configuration-Set Sending Quotas

Each organization's SES configuration set has independent sending quotas. One tenant hitting their limit does not affect other tenants.

```python
# SES v2 account-level sending quota is shared, but configuration sets
# provide per-tenant sending rate limits
ses.put_configuration_set_sending_options(
    ConfigurationSetName=f"agentmail-{org_id}",
    SendingOptions={"SendingEnabled": True},
)

# For fine-grained control, use SES sending authorization policies
# to limit per-tenant sending rates
```

### DynamoDB: On-Demand Mode + Adaptive Capacity

DynamoDB on-demand mode automatically scales throughput. Adaptive capacity redistributes throughput to hot partitions. Combined, these prevent one tenant's traffic spike from affecting others.

For extreme cases (a single tenant doing 100K writes/sec), the partition key structure (`ORG#{org_id}`) means their traffic lands on a small set of partitions. DynamoDB handles this with partition splitting, but if needed, we can implement application-level write sharding:

```python
import random

def sharded_pk(org_id: str, shard_count: int = 10) -> str:
    """Generate a sharded partition key to distribute hot tenant writes."""
    shard = random.randint(0, shard_count - 1)
    return f"ORG#{org_id}#SHARD#{shard}"
```

### Lambda: Reserved Concurrency on Critical Functions

Critical functions (metering, webhook delivery, inbound email processing) have reserved concurrency to prevent one tenant's traffic from starving others:

```python
# CDK configuration
from aws_cdk import aws_lambda as lambda_

metering_function = lambda_.Function(
    self, "MeterUsageSubmitter",
    # ... other config ...
    reserved_concurrent_executions=50,  # Always available for metering
)

webhook_function = lambda_.Function(
    self, "WebhookDelivery",
    # ... other config ...
    reserved_concurrent_executions=200,  # Dedicated capacity for webhooks
)

inbound_processor = lambda_.Function(
    self, "InboundEmailProcessor",
    # ... other config ...
    reserved_concurrent_executions=100,  # Email processing never starved
)
```

---

## Per-Tenant Resource Quotas

Every organization has a quota object that enforces hard limits. These quotas are separate from Marketplace entitlements (which define what's included in the contract price). Quotas are hard caps that prevent abuse and protect platform stability.

### Complete Quota Object

```json
{
  "org_id": "org-abc123",
  "tier": "growth",
  "quotas": {
    "max_inboxes": 100,
    "max_inboxes_per_pod": 50,
    "max_pods": 20,
    "max_messages_per_day": 50000,
    "max_messages_per_hour": 5000,
    "max_message_size_bytes": 26214400,
    "max_attachment_size_bytes": 26214400,
    "max_attachments_per_message": 10,
    "max_storage_gb": 50,
    "max_api_calls_per_second": 100,
    "max_api_calls_per_day": 500000,
    "max_webhooks": 50,
    "max_webhook_payload_size_bytes": 65536,
    "max_domains": 5,
    "max_api_keys": 20,
    "max_allow_list_entries": 1000,
    "max_block_list_entries": 1000,
    "max_ai_searches_per_day": 5000,
    "max_ai_categorizations_per_day": 25000,
    "max_concurrent_imap_connections": 50,
    "max_concurrent_smtp_connections": 50,
    "max_batch_size": 100,
    "max_recipients_per_message": 50,
    "max_labels_per_inbox": 100,
    "rate_limit_burst": 200,
    "rate_limit_sustained": 100
  },
  "overrides": {}
}
```

### Quota Enforcement

Quotas are checked at two levels:

1. **API Gateway (rate limits)**: Per-API-key throttle via usage plans handles rps/burst limits
2. **Application code (resource limits)**: Lambda handlers check resource quotas before creating resources

```python
def enforce_quota(org_id: str, resource_type: str, current_count: int = None):
    """
    Check if creating a new resource would exceed the tenant's quota.
    Raises QuotaExceededException if the quota would be exceeded.
    """
    quota = get_tenant_quota(org_id)
    quota_key = f"max_{resource_type}"

    if quota_key not in quota["quotas"]:
        return  # No quota defined for this resource type

    max_allowed = quota["quotas"][quota_key]

    # Apply override if present
    if resource_type in quota.get("overrides", {}):
        max_allowed = quota["overrides"][resource_type]

    if current_count is None:
        current_count = count_resources(org_id, resource_type)

    if current_count >= max_allowed:
        raise QuotaExceededException(
            f"Quota exceeded: {resource_type} limit is {max_allowed}, "
            f"current count is {current_count}. "
            f"Upgrade your plan or contact support."
        )
```

### Tier-Specific Quotas

| Quota | Starter | Growth | Scale | Enterprise |
|-------|---------|--------|-------|------------|
| Max inboxes | 10 | 100 | 1,000 | 100,000+ |
| Max pods | 3 | 20 | 100 | 1,000+ |
| Max messages/day | 5,000 | 50,000 | 500,000 | 5,000,000+ |
| Max storage (GB) | 5 | 50 | 500 | 5,000+ |
| Max API calls/sec | 25 | 100 | 500 | 2,500+ |
| Max webhooks | 10 | 50 | 200 | 1,000+ |
| Max domains | 1 | 5 | 20 | 100+ |
| Max API keys | 5 | 20 | 50 | 200+ |
| IMAP/SMTP connections | 0 | 50 | 200 | 1,000+ |

---

## Pod Isolation

### How Platform Builders Use Pods

A typical AgentMail customer building an AI agent platform for their own customers:

```
Acme AI (AgentMail Organization: org-acme)
    |
    +-- Pod: "customer-widgetco" (pod-wid)
    |     +-- Inbox: support-agent@pods.agentmail.aws
    |     +-- Inbox: sales-agent@pods.agentmail.aws
    |     +-- Webhook: https://acme.ai/webhooks/widgetco
    |
    +-- Pod: "customer-megacorp" (pod-meg)
    |     +-- Inbox: helpdesk@megacorp.com (custom domain)
    |     +-- Inbox: notifications@megacorp.com
    |     +-- Webhook: https://acme.ai/webhooks/megacorp
    |
    +-- Pod: "internal-testing" (pod-test)
          +-- Inbox: test-1@pods.agentmail.aws
          +-- Webhook: https://acme.ai/webhooks/test
```

### Pod-Level Configuration

Each pod can override organization defaults:

```json
{
  "pod_id": "pod-wid",
  "org_id": "org-acme",
  "name": "customer-widgetco",
  "config": {
    "webhook_url": "https://acme.ai/webhooks/widgetco",
    "webhook_secret": "encrypted:aws:kms:...",
    "default_from_name": "WidgetCo Support",
    "ai_categorization_prompt": "Categorize emails for a widget manufacturing company...",
    "ai_extraction_schema": {
      "order_number": "string",
      "issue_type": "enum:defect,shipping,billing,other"
    },
    "allow_list": ["*@widgetco.com", "*@widgetco-partners.com"],
    "block_list": []
  },
  "quotas": {
    "max_inboxes": 10,
    "max_messages_per_day": 5000
  }
}
```

### Pod Isolation Enforcement

Pods provide logical isolation within an organization. All pod-scoped queries include the `pod_id` filter:

```python
def list_inboxes(org_id: str, pod_id: str = None):
    """List inboxes, optionally filtered by pod."""
    key_condition = "PK = :pk"
    expression_values = {":pk": f"ORG#{org_id}"}

    if pod_id:
        # Filter to specific pod
        key_condition += " AND begins_with(SK, :pod_prefix)"
        expression_values[":pod_prefix"] = f"POD#{pod_id}#INBOX#"
    else:
        # All inboxes in org (admin view)
        filter_expression = "begins_with(SK, :inbox_prefix)"
        expression_values[":inbox_prefix"] = "INBOX#"

    response = table.query(
        KeyConditionExpression=key_condition,
        ExpressionAttributeValues=expression_values,
    )
    return response["Items"]
```

---

## Tenant Provisioning Flow

### Create Organization

```python
def provision_tenant(customer_id: str, product_code: str, customer_aws_account: str) -> dict:
    """
    Complete tenant provisioning flow.
    Called after ResolveCustomer during Marketplace onboarding.
    """
    org_id = generate_org_id()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Create organization record
    create_organization(org_id, customer_id, product_code, customer_aws_account)

    # 2. Fetch and store initial entitlements
    entitlements = fetch_entitlements(customer_id, product_code)
    tier = determine_tier_from_entitlements(entitlements)
    update_tenant_tier(org_id, tier, entitlements)

    # 3. Create SES configuration set
    create_org_ses_config(org_id)

    # 4. Generate initial API key
    api_key = generate_api_key(org_id)

    # 5. Create default pod
    default_pod = create_pod(org_id, name="default")

    # 6. Initialize quota from tier
    initialize_quotas(org_id, tier)

    # 7. Create Redis cache entries
    initialize_cache(org_id, tier, entitlements)

    return {
        "org_id": org_id,
        "api_key": api_key["raw_key"],  # Shown once, never stored in plaintext
        "default_pod_id": default_pod["pod_id"],
        "tier": tier,
    }
```

### Generate Initial API Key

```python
import hashlib
import secrets


def generate_api_key(org_id: str, name: str = "Default API Key") -> dict:
    """
    Generate an API key for an organization.
    The raw key is returned exactly once and never stored in plaintext.
    """
    # Format: am_{random_hex}
    raw_key = f"am_{secrets.token_hex(32)}"

    # Store SHA-256 hash only
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]  # For identification in UI: "am_a1b2c3d4e..."

    now = datetime.now(timezone.utc).isoformat()

    tenant_table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": f"APIKEY#{key_hash}",
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "org_id": org_id,
            "name": name,
            "scopes": ["*"],
            "status": "active",
            "created_at": now,
            "last_used_at": None,
        }
    )

    # Cache in Redis for fast auth lookups
    redis_client.setex(
        f"auth:{key_hash}",
        3600,  # 1 hour cache
        json.dumps({
            "org_id": org_id,
            "scopes": ["*"],
            "status": "active",
        }),
    )

    return {
        "raw_key": raw_key,
        "key_hash": key_hash,
        "key_prefix": key_prefix,
    }
```

---

## Tenant Deprovisioning

When a customer unsubscribes (see [Customer Lifecycle](../08-marketplace/customer-lifecycle.md)):

### Phase 1: Disable (Immediate on unsubscribe-success)

```python
def disable_tenant(org_id: str):
    """Immediately disable all tenant access."""
    # Disable API keys
    disable_all_api_keys(org_id)

    # Disable webhooks
    disable_all_webhooks(org_id)

    # Delete Redis cache
    delete_redis_keys(f"{org_id}:*")

    # Disable SES configuration set
    ses.put_configuration_set_sending_options(
        ConfigurationSetName=f"agentmail-{org_id}",
        SendingOptions={"SendingEnabled": False},
    )

    # Update tenant status
    update_tenant_status(org_id, "cancelled")
```

### Phase 2: Archive (30 days post-cancellation)

Implemented via S3 Lifecycle rules and a scheduled Lambda:

```python
# S3 Lifecycle rule (applied per-org prefix)
{
    "Rules": [
        {
            "ID": f"archive-{org_id}",
            "Filter": {"Prefix": f"{org_id}/"},
            "Status": "Enabled",
            "Transitions": [
                {
                    "Days": 30,
                    "StorageClass": "GLACIER_DEEP_ARCHIVE"
                }
            ]
        }
    ]
}
```

### Phase 3: Delete (90 days post-cancellation)

DynamoDB items have TTL set to `cancelled_at + 90 days`. DynamoDB automatically deletes expired items.

S3 objects are deleted by a scheduled Lambda that scans for org prefixes past the 90-day retention period:

```python
def cleanup_expired_tenants():
    """
    Scheduled Lambda (daily) that deletes S3 data for tenants
    past the 90-day retention period.
    """
    expired_tenants = query_expired_tenants(days_since_cancellation=90)

    for tenant in expired_tenants:
        org_id = tenant["org_id"]

        # Delete all S3 objects under this org prefix
        for bucket in ["agentmail-email-bodies", "agentmail-attachments", "agentmail-exports"]:
            delete_all_objects(bucket, prefix=f"{org_id}/")

        # Delete SES configuration set
        try:
            ses.delete_configuration_set(
                ConfigurationSetName=f"agentmail-{org_id}"
            )
        except ses.exceptions.NotFoundException:
            pass

        # Mark tenant as permanently deleted
        update_tenant_status(org_id, "deleted")

        print(f"Permanently deleted all data for tenant {org_id}")
```
