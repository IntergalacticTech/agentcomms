# Pod Architecture

This document covers the complete Pod system -- AgentMail's mechanism for platform builders to create isolated tenant boundaries within their organization. Pods solve the "platform within a platform" problem: when an AgentMail customer is itself a multi-tenant platform, pods let them isolate each of their own customers' data without managing separate AgentMail accounts.

---

## What Pods Are

A Pod is a logical grouping of inboxes within an organization. It acts as a sub-tenant boundary, providing data isolation, scoped API keys, dedicated webhooks, and independent configuration. The hierarchy is:

```
Organization (billing entity, hard isolation boundary)
    |
    +-- Pod A (logical isolation boundary)
    |     +-- Inbox 1
    |     +-- Inbox 2
    |     +-- Pod-scoped API key
    |     +-- Pod-level webhook
    |
    +-- Pod B (logical isolation boundary)
    |     +-- Inbox 3
    |     +-- Inbox 4
    |     +-- Pod-scoped API key
    |     +-- Pod-level webhook
    |
    +-- Default Pod (always exists, created at org provisioning)
          +-- Inbox 5
```

Every organization has at least one pod (the "Default" pod, created during provisioning). Inboxes always belong to exactly one pod. Pods cannot be nested -- the hierarchy is always Organization > Pod > Inbox.

---

## Why Pods Exist

Without pods, a platform builder serving 500 end-customers would face an impossible choice:

1. **One AgentMail org per customer**: 500 separate API keys, 500 billing relationships, no unified view
2. **All customers in one flat org**: No isolation between customers' email data, no per-customer webhooks, no per-customer configs

Pods provide option 3: one AgentMail organization with 500 pods, each fully isolated.

---

## Use Cases

### AI Agent Framework: One Pod per End-Customer Company

An AI agent platform (e.g., "AgentFlow") serves multiple companies. Each company gets its own pod:

```
AgentFlow (org-agentflow)
    |
    +-- Pod: "widgetco" (pod-wid)
    |     +-- support-bot@pods.agentmail.aws
    |     +-- sales-bot@pods.agentmail.aws
    |     +-- Webhook: https://agentflow.ai/hooks/widgetco
    |     +-- Config: categorize emails as widget orders, defect reports, billing inquiries
    |
    +-- Pod: "megacorp" (pod-meg)
    |     +-- helpdesk@megacorp.com (custom domain)
    |     +-- onboarding@megacorp.com
    |     +-- Webhook: https://agentflow.ai/hooks/megacorp
    |     +-- Config: categorize emails as IT tickets, HR requests, facilities
    |
    +-- Pod: "startup-xyz" (pod-xyz)
          +-- agent@pods.agentmail.aws
          +-- Webhook: https://agentflow.ai/hooks/startupxyz
```

WidgetCo's emails are invisible to MegaCorp's pod-scoped API key, and vice versa.

### Enterprise: One Pod per Department

A large company uses pods to separate departmental email automation:

```
Acme Corp (org-acme)
    |
    +-- Pod: "sales" (pod-sales)
    |     +-- lead-qualifier@acme.com
    |     +-- proposal-sender@acme.com
    |     +-- Webhook: https://acme.com/api/sales-emails
    |
    +-- Pod: "support" (pod-support)
    |     +-- tier1@acme.com
    |     +-- escalations@acme.com
    |     +-- Webhook: https://acme.com/api/support-emails
    |
    +-- Pod: "ops" (pod-ops)
          +-- alerts@acme.com
          +-- vendor-comms@acme.com
          +-- Webhook: https://acme.com/api/ops-emails
```

The sales team's API key cannot read support tickets. Each department gets independent webhook delivery.

### Developer: One Pod per Environment

A developer uses pods to separate environments:

```
My App (org-myapp)
    |
    +-- Pod: "production" (pod-prod)
    |     +-- notifications@myapp.com
    |     +-- Webhook: https://myapp.com/webhooks/email
    |
    +-- Pod: "staging" (pod-staging)
    |     +-- notifications@staging.pods.agentmail.aws
    |     +-- Webhook: https://staging.myapp.com/webhooks/email
    |
    +-- Pod: "test" (pod-test)
          +-- test-inbox-1@pods.agentmail.aws
          +-- test-inbox-2@pods.agentmail.aws
          +-- Webhook: https://localhost:8080/webhooks/email
```

Test emails never pollute production. Staging uses a separate webhook endpoint.

---

## Pod Creation Flow

### API Request

```http
POST /pods
Authorization: Bearer am_abc123...
Content-Type: application/json

{
  "name": "customer-widgetco",
  "config": {
    "webhook_url": "https://example.com/hooks/widgetco",
    "webhook_secret": "whsec_random_secret_here",
    "default_from_name": "WidgetCo Support",
    "ai_categorization_prompt": "Categorize for a widget company...",
    "allow_list": ["*@widgetco.com"]
  },
  "quotas": {
    "max_inboxes": 10,
    "max_messages_per_day": 5000
  }
}
```

### API Response

```json
{
  "pod_id": "pod_01HXYZ9876543210ABCDEFGHJK",
  "org_id": "org_01HXYZ1234567890ABCDEFGHJK",
  "name": "customer-widgetco",
  "status": "active",
  "config": {
    "webhook_url": "https://example.com/hooks/widgetco",
    "default_from_name": "WidgetCo Support",
    "ai_categorization_prompt": "Categorize for a widget company...",
    "allow_list": ["*@widgetco.com"]
  },
  "quotas": {
    "max_inboxes": 10,
    "max_messages_per_day": 5000
  },
  "created_at": "2026-04-10T14:30:00.000Z"
}
```

### Lambda Implementation

```python
import ulid
import json
from datetime import datetime, timezone

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("agentmail-main")


def create_pod(org_id: str, name: str, config: dict = None, quotas: dict = None) -> dict:
    """
    Create a new pod within an organization.

    Steps:
    1. Verify org exists and is active
    2. Check pod count against org quota
    3. Validate pod-level quotas don't exceed org quotas
    4. Write pod record to DynamoDB
    5. Inherit org defaults for any unspecified config fields
    6. Publish pod.created event
    """
    now = datetime.now(timezone.utc).isoformat()
    pod_id = f"pod_{ulid.new().str}"

    # 1. Fetch org record and validate
    org = table.get_item(
        Key={"PK": f"ORG#{org_id}", "SK": "METADATA"}
    ).get("Item")

    if not org or org.get("status") != "active":
        raise ValueError("Organization not found or inactive")

    # 2. Check pod count quota
    org_quotas = get_org_quotas(org_id)
    current_pod_count = count_pods(org_id)

    if current_pod_count >= org_quotas["max_pods"]:
        raise QuotaExceededException(
            quota="max_pods",
            current=current_pod_count,
            limit=org_quotas["max_pods"],
        )

    # 3. Validate pod-level quotas are a subset of org quotas
    if quotas:
        validate_pod_quotas(quotas, org_quotas)

    # 4. Merge config with org defaults
    org_config = get_org_default_config(org_id)
    merged_config = {**org_config, **(config or {})}

    # 5. Write pod record
    pod_item = {
        "PK": f"ORG#{org_id}",
        "SK": f"POD#{pod_id}",
        "entity_type": "Pod",
        "pod_id": pod_id,
        "org_id": org_id,
        "name": name,
        "status": "active",
        "config": merged_config,
        "quotas": quotas or {},
        "inbox_count": 0,
        "created_at": now,
        "updated_at": now,
    }

    # GSI1 for listing pods by org (sorted by creation date)
    pod_item["GSI1PK"] = f"ORG#{org_id}#PODS"
    pod_item["GSI1SK"] = now

    table.put_item(Item=pod_item)

    # 6. Publish event
    publish_event("pod.created", {
        "org_id": org_id,
        "pod_id": pod_id,
        "name": name,
    })

    return pod_item


def validate_pod_quotas(pod_quotas: dict, org_quotas: dict):
    """
    Pod quotas must not exceed org quotas. If a pod quota field is specified,
    it must be <= the corresponding org-level quota.
    """
    quota_mapping = {
        "max_inboxes": "max_inboxes_per_pod",
        "max_messages_per_day": "max_messages_per_day",
    }

    for pod_key, org_key in quota_mapping.items():
        if pod_key in pod_quotas:
            org_limit = org_quotas.get(org_key)
            if org_limit and pod_quotas[pod_key] > org_limit:
                raise ValueError(
                    f"Pod quota {pod_key}={pod_quotas[pod_key]} exceeds "
                    f"org quota {org_key}={org_limit}"
                )
```

---

## Pod-Level Features

### Pod-Scoped API Keys

API keys can be scoped to a single pod, restricting access to only inboxes within that pod:

```python
def generate_pod_api_key(org_id: str, pod_id: str, name: str) -> dict:
    """
    Generate an API key scoped to a specific pod.
    This key can only access inboxes, messages, and threads within this pod.
    """
    raw_key = f"am_{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]
    now = datetime.now(timezone.utc).isoformat()

    table.put_item(
        Item={
            "PK": f"ORG#{org_id}",
            "SK": f"APIKEY#{key_hash}",
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "org_id": org_id,
            "pod_id": pod_id,       # Pod scope -- null for org-scoped keys
            "name": name,
            "scopes": ["pod:*"],    # All operations, but only within this pod
            "status": "active",
            "created_at": now,
            "last_used_at": None,
        }
    )

    # Cache includes pod_id for authorization checks
    redis_client.setex(
        f"auth:{key_hash}",
        3600,
        json.dumps({
            "org_id": org_id,
            "pod_id": pod_id,
            "scopes": ["pod:*"],
            "status": "active",
        }),
    )

    return {"raw_key": raw_key, "key_hash": key_hash, "key_prefix": key_prefix}
```

**Authorization enforcement**: When a pod-scoped key is used, the authorizer injects `pod_id` into the request context. Every downstream handler checks:

```python
def authorize_request(auth_context: dict, requested_pod_id: str = None):
    """
    Enforce pod-scoped access. If the API key is pod-scoped,
    the request must target that pod (or a resource within it).
    """
    key_pod_id = auth_context.get("pod_id")

    if key_pod_id is None:
        # Org-scoped key -- can access any pod
        return

    if requested_pod_id and requested_pod_id != key_pod_id:
        raise ForbiddenException(
            "This API key is scoped to pod "
            f"{key_pod_id} and cannot access pod {requested_pod_id}"
        )

    if requested_pod_id is None:
        # Org-level operation attempted with pod-scoped key
        raise ForbiddenException(
            "This API key is pod-scoped and cannot perform org-level operations"
        )
```

### Pod-Level Webhooks

Each pod can have its own webhook URL. When an event occurs in an inbox, the webhook dispatcher checks for a pod-level webhook first, then falls back to the org-level webhook:

```python
def dispatch_webhook(org_id: str, pod_id: str, event: dict):
    """
    Dispatch a webhook event. Pod-level webhook takes priority over org-level.
    """
    # Check pod-level webhook
    pod = get_pod(org_id, pod_id)
    webhook_url = pod.get("config", {}).get("webhook_url")
    webhook_secret = pod.get("config", {}).get("webhook_secret")

    if not webhook_url:
        # Fall back to org-level webhook
        org = get_org(org_id)
        webhook_url = org.get("config", {}).get("webhook_url")
        webhook_secret = org.get("config", {}).get("webhook_secret")

    if not webhook_url:
        return  # No webhook configured at either level

    # Include pod_id in every event payload
    event["pod_id"] = pod_id
    event["org_id"] = org_id

    # Sign and deliver
    signature = compute_hmac(webhook_secret, json.dumps(event))

    sqs.send_message(
        QueueUrl=WEBHOOK_QUEUE_URL,
        MessageBody=json.dumps({
            "url": webhook_url,
            "signature": signature,
            "event": event,
        }),
        MessageGroupId=org_id,
        MessageDeduplicationId=f"{org_id}-{event['event_id']}",
    )
```

### Pod-Level Quotas

Pod quotas are a subset of the org's quotas. They allow the org admin to prevent any single pod from consuming the entire org's resources:

```json
{
  "pod_id": "pod_01HXYZ9876543210ABCDEFGHJK",
  "quotas": {
    "max_inboxes": 10,
    "max_messages_per_day": 5000,
    "max_storage_mb": 100
  }
}
```

Enforcement checks pod quotas first, then org quotas:

```python
def enforce_pod_quota(org_id: str, pod_id: str, resource_type: str):
    """
    Two-level quota check: pod quota first, then org quota.
    Both must pass for the operation to proceed.
    """
    pod = get_pod(org_id, pod_id)
    pod_quotas = pod.get("quotas", {})

    # Check pod-level quota (if defined)
    pod_limit_key = f"max_{resource_type}"
    if pod_limit_key in pod_quotas:
        current = count_resources_in_pod(org_id, pod_id, resource_type)
        if current >= pod_quotas[pod_limit_key]:
            raise QuotaExceededException(
                quota=pod_limit_key,
                current=current,
                limit=pod_quotas[pod_limit_key],
                scope="pod",
            )

    # Check org-level quota (always enforced)
    enforce_quota(org_id, resource_type)
```

### Pod-Level Categorization and Extraction Configs

Pods can override the organization's default AI configuration. This allows each end-customer to have email categorization and data extraction tuned to their domain:

```json
{
  "pod_id": "pod-widgetco",
  "config": {
    "ai_categorization_prompt": "You are categorizing emails for WidgetCo, a widget manufacturer. Categories: order_inquiry, defect_report, shipping_issue, billing_question, partnership_request, other.",
    "ai_categorization_categories": [
      "order_inquiry", "defect_report", "shipping_issue",
      "billing_question", "partnership_request", "other"
    ],
    "ai_extraction_schema": {
      "order_number": {"type": "string", "pattern": "^WC-\\d{6}$"},
      "product_sku": {"type": "string"},
      "issue_type": {"type": "enum", "values": ["defect", "shipping", "billing", "other"]},
      "urgency": {"type": "enum", "values": ["low", "medium", "high", "critical"]}
    }
  }
}
```

When an email arrives, the AI pipeline resolves configuration in order: inbox config > pod config > org config > platform defaults.

### Pod-Level Allow/Block Lists

Pods can define their own allow and block lists that apply to all inboxes within the pod:

```python
def check_allow_block_lists(org_id: str, pod_id: str, inbox_id: str, sender: str) -> str:
    """
    Check allow/block lists in order: inbox > pod > org.
    Returns: "allow", "block", or "none" (no match, fall through to default behavior).
    """
    # 1. Check inbox-level lists
    inbox = get_inbox(org_id, inbox_id)
    result = match_lists(inbox.get("allow_list", []), inbox.get("block_list", []), sender)
    if result != "none":
        return result

    # 2. Check pod-level lists
    pod = get_pod(org_id, pod_id)
    pod_config = pod.get("config", {})
    result = match_lists(pod_config.get("allow_list", []), pod_config.get("block_list", []), sender)
    if result != "none":
        return result

    # 3. Check org-level lists
    org = get_org(org_id)
    org_config = org.get("config", {})
    result = match_lists(org_config.get("allow_list", []), org_config.get("block_list", []), sender)
    return result
```

---

## Pod Isolation Guarantees

### Data Isolation

Every query involving messages, threads, drafts, or attachments includes `pod_id` as a filter. The sort key structure in DynamoDB encodes the pod:

```
PK: ORG#{org_id}
SK: POD#{pod_id}#INBOX#{inbox_id}#MSG#{msg_id}
```

This means a DynamoDB query with `begins_with(SK, "POD#{pod_id}")` returns only items within that pod. There is no way to construct a key condition that spans pods accidentally.

### API Isolation

Pod-scoped API keys include the `pod_id` in the cached auth context. The Lambda authorizer rejects any request that targets a resource outside the key's pod:

```python
# In the Lambda authorizer
if auth_context["pod_id"] and resource_pod_id != auth_context["pod_id"]:
    return generate_deny_policy(principal_id, resource_arn)
```

### Webhook Isolation

Events include `pod_id` in the payload. The webhook dispatcher filters events to deliver only to the matching pod's webhook URL. An org-level webhook receives events from all pods (for org-admin use cases).

### Metrics Isolation

Usage counters are tracked per-pod in addition to per-org:

```
DynamoDB:
  PK: ORG#{org_id}    SK: USAGE#POD#{pod_id}#2026-04-10

Redis:
  {org_id}:pod:{pod_id}:usage:emails_today → atomic counter
  {org_id}:pod:{pod_id}:usage:api_calls_today → atomic counter
```

---

## Pod Limits by Tier

| Tier | Max Pods | Notes |
|------|----------|-------|
| Free | 1 | Default pod only; cannot create additional pods |
| Pro | 3 | Includes default pod |
| Business | 10 | Includes default pod |
| Scale | Unlimited | Fair use policy applies |
| Enterprise | Unlimited | Per-pod SLA options available; dedicated support per pod |

Marketplace tier mapping:

| Marketplace Tier | Max Pods |
|------------------|----------|
| Starter | 3 |
| Growth | 20 |
| Scale | 100 |
| Enterprise | 1,000+ (negotiable) |

---

## DynamoDB Access Patterns

### List All Pods in an Organization

```python
def list_pods(org_id: str) -> list:
    """List all pods in an organization, sorted by creation date."""
    response = table.query(
        IndexName="GSI1",
        KeyConditionExpression="GSI1PK = :pk",
        ExpressionAttributeValues={
            ":pk": f"ORG#{org_id}#PODS",
        },
        ScanIndexForward=True,  # Oldest first
    )
    return response["Items"]
```

### List Inboxes in a Pod

```python
def list_inboxes_in_pod(org_id: str, pod_id: str, limit: int = 50, cursor: str = None) -> dict:
    """List inboxes within a specific pod with pagination."""
    kwargs = {
        "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
        "ExpressionAttributeValues": {
            ":pk": f"ORG#{org_id}",
            ":sk_prefix": f"POD#{pod_id}#INBOX#",
        },
        "Limit": limit,
    }

    if cursor:
        kwargs["ExclusiveStartKey"] = json.loads(base64.b64decode(cursor))

    response = table.query(**kwargs)

    next_cursor = None
    if "LastEvaluatedKey" in response:
        next_cursor = base64.b64encode(
            json.dumps(response["LastEvaluatedKey"]).encode()
        ).decode()

    return {
        "items": response["Items"],
        "next_cursor": next_cursor,
    }
```

### Get Pod Metrics

```python
def get_pod_metrics(org_id: str, pod_id: str, date: str) -> dict:
    """Get usage metrics for a specific pod on a given date."""
    response = table.get_item(
        Key={
            "PK": f"ORG#{org_id}",
            "SK": f"USAGE#POD#{pod_id}#{date}",
        }
    )

    item = response.get("Item", {})
    return {
        "pod_id": pod_id,
        "date": date,
        "emails_received": item.get("emails_received", 0),
        "emails_sent": item.get("emails_sent", 0),
        "api_calls": item.get("api_calls", 0),
        "ai_categorizations": item.get("ai_categorizations", 0),
        "ai_extractions": item.get("ai_extractions", 0),
        "storage_bytes": item.get("storage_bytes", 0),
    }
```

### Count Pods in an Organization

```python
def count_pods(org_id: str) -> int:
    """Count the number of pods in an organization (for quota enforcement)."""
    response = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"ORG#{org_id}",
            ":prefix": "POD#",
        },
        Select="COUNT",
        FilterExpression="entity_type = :et",
        ExpressionAttributeNames={},
        ExpressionAttributeValues={
            ":pk": f"ORG#{org_id}",
            ":prefix": "POD#",
            ":et": "Pod",
        },
    )
    return response["Count"]
```

---

## Pod Deletion

Pod deletion is a multi-phase process to prevent accidental data loss.

### Phase 1: Soft Delete (Immediate)

```python
def delete_pod(org_id: str, pod_id: str):
    """
    Soft-delete a pod. Marks the pod as deleted and disables all access.
    Child inboxes stop receiving email but data is retained for 30 days.
    """
    now = datetime.now(timezone.utc).isoformat()
    ttl_30_days = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())

    # Cannot delete the default pod
    pod = get_pod(org_id, pod_id)
    if pod.get("name") == "Default":
        raise ValueError("Cannot delete the default pod")

    # Mark pod as deleted
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"POD#{pod_id}"},
        UpdateExpression="SET #status = :status, deleted_at = :now, deletion_ttl = :ttl",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "deleted",
            ":now": now,
            ":ttl": ttl_30_days,
        },
    )

    # Disable all inboxes in the pod (stop receiving email)
    inboxes = list_inboxes_in_pod(org_id, pod_id, limit=1000)
    for inbox in inboxes["items"]:
        disable_inbox_receiving(org_id, inbox["inbox_id"])

    # Revoke all pod-scoped API keys
    revoke_pod_api_keys(org_id, pod_id)

    # Remove pod webhook
    disable_pod_webhook(org_id, pod_id)

    # Invalidate Redis cache
    redis_client.delete(f"{org_id}:pod:{pod_id}:config")

    # Publish event
    publish_event("pod.deleted", {
        "org_id": org_id,
        "pod_id": pod_id,
        "retention_until": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    })
```

### Phase 2: Hard Delete (After 30 Days)

A scheduled Lambda runs daily and permanently deletes pods past their retention period:

```python
def cleanup_deleted_pods():
    """
    Scheduled Lambda (daily). Permanently deletes pods that have been
    soft-deleted for more than 30 days.
    """
    now = int(datetime.now(timezone.utc).timestamp())

    # Query for pods with expired deletion TTL
    expired_pods = table.query(
        IndexName="GSI-DeletionTTL",
        KeyConditionExpression="entity_type = :et AND deletion_ttl <= :now",
        ExpressionAttributeValues={
            ":et": "Pod",
            ":now": now,
        },
    )

    for pod in expired_pods["Items"]:
        org_id = pod["org_id"]
        pod_id = pod["pod_id"]

        # Delete all inboxes and their messages
        inboxes = list_inboxes_in_pod(org_id, pod_id, limit=1000)
        for inbox in inboxes["items"]:
            hard_delete_inbox(org_id, inbox["inbox_id"])

        # Delete S3 objects (email bodies, attachments)
        for bucket in ["agentmail-email-bodies", "agentmail-attachments"]:
            delete_all_objects(bucket, prefix=f"{org_id}/{pod_id}/")

        # Delete OpenSearch documents
        opensearch_client.delete_by_query(
            index="agentmail-emails",
            body={"query": {"term": {"pod_id.keyword": pod_id}}},
        )

        # Delete the pod record itself
        table.delete_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"POD#{pod_id}"}
        )

        # Delete usage records
        delete_pod_usage_records(org_id, pod_id)

        print(f"Hard-deleted pod {pod_id} from org {org_id}")
```

### Recovery During Retention Window

During the 30-day retention period, the org admin can restore a deleted pod:

```python
def restore_pod(org_id: str, pod_id: str):
    """Restore a soft-deleted pod within the 30-day retention window."""
    pod = get_pod(org_id, pod_id)

    if pod.get("status") != "deleted":
        raise ValueError("Pod is not in deleted state")

    if pod.get("deletion_ttl", 0) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Retention period has expired; pod cannot be restored")

    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"POD#{pod_id}"},
        UpdateExpression="SET #status = :status REMOVE deleted_at, deletion_ttl",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "active"},
    )

    # Re-enable inboxes
    inboxes = list_inboxes_in_pod(org_id, pod_id, limit=1000)
    for inbox in inboxes["items"]:
        enable_inbox_receiving(org_id, inbox["inbox_id"])

    publish_event("pod.restored", {"org_id": org_id, "pod_id": pod_id})
```

---

## Cross-Pod Operations

Some operations span pods (available only to org-scoped API keys), while others are strictly pod-scoped.

### Org-Level (Cross-Pod) Operations

| Operation | Description |
|-----------|-------------|
| `GET /pods` | List all pods in the organization |
| `GET /organizations/me/metrics` | Aggregated usage metrics across all pods |
| `GET /search?q=...` (without pod_id filter) | Search emails across all pods |
| `GET /organizations/me/usage` | Billing usage summary across all pods |
| `POST /pods` | Create a new pod |
| `DELETE /pods/{pod_id}` | Delete a pod |

### Pod-Scoped Operations

| Operation | Description |
|-----------|-------------|
| `GET /pods/{pod_id}/inboxes` | List inboxes within a pod |
| `POST /pods/{pod_id}/inboxes` | Create inbox within a pod |
| `GET /pods/{pod_id}/messages` | List messages across all inboxes in a pod |
| `GET /search?q=...&pod_id=...` | Search emails within a single pod |
| `PUT /pods/{pod_id}/config` | Update pod configuration |
| `GET /pods/{pod_id}/metrics` | Usage metrics for a single pod |

Pod-scoped API keys can only perform pod-scoped operations. Attempting an org-level operation with a pod-scoped key returns `403 Forbidden`.
