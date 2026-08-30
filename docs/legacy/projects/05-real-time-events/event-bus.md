# Central Event Bus

The AgentMail event bus is a Kinesis Data Streams stream that serves as the single source of truth for every platform event. All event sources -- SES notifications, API mutations, AI processing results, domain verification status changes -- normalize their output into a unified event schema and write to this stream. All consumers -- webhook delivery, WebSocket push, analytics, archival -- read from this stream via enhanced fan-out with dedicated throughput.

---

## Why Kinesis Data Streams

We evaluated three AWS services for the event bus: Kinesis Data Streams, Amazon EventBridge, and Amazon SNS. The decision came down to three requirements that only Kinesis satisfies simultaneously.

### Ordering

Events for a given inbox must arrive in order. When an AI agent receives a `message.received` event followed by a `message.ai_processed` event, they must arrive in that sequence. EventBridge provides no ordering guarantees -- events are delivered best-effort and can arrive out of order. SNS delivers messages independently per subscription with no ordering. Kinesis guarantees ordering within a shard, and by partitioning on `inboxId`, all events for a given inbox land on the same shard in order.

### Replay

When a WebSocket client reconnects after a brief disconnection, it needs to receive all events it missed. When a webhook endpoint was temporarily down, we need to replay events after it recovers. EventBridge has no built-in replay -- events are fire-and-forget (the archive/replay feature replays all events, not per-consumer). SNS has no replay at all. Kinesis retains events for up to 365 days (we use 7 days), and consumers can seek to any position in the stream by sequence number or timestamp.

### Enhanced Fan-Out Throughput

With multiple consumers reading the same stream, shared-throughput consumers split the 2 MB/sec/shard read capacity. At 4 shards, that is 8 MB/sec shared across all consumers -- not enough when webhook delivery, WebSocket push, and analytics are all reading simultaneously. Kinesis enhanced fan-out provides each consumer its own dedicated 2 MB/sec/shard pipe, for a total of 8 MB/sec per consumer with 4 shards. Neither EventBridge nor SNS provide this kind of consumer-isolated throughput.

| Requirement | Kinesis | EventBridge | SNS |
|-------------|---------|-------------|-----|
| Per-key ordering | Shard-level (partition key) | No ordering | No ordering |
| Replay/retention | 7-365 days, per-consumer seek | Archive replay (all events) | None |
| Per-consumer throughput | 2 MB/sec/shard (enhanced fan-out) | 10K events/sec account limit | 100K SMS, 10M pub/sec |
| Cost at 100K events/min | ~$200/mo | ~$100/mo | ~$150/mo |
| Payload size | 1 MB | 256 KB | 256 KB |

EventBridge would cost slightly less but cannot order or replay. SNS would add complexity with filter policies and still cannot replay. Kinesis costs ~$50-100/mo more but provides the guarantees we need.

---

## Stream Configuration

```json
{
  "StreamName": "agentmail-events",
  "ShardCount": 4,
  "StreamModeDetails": {
    "StreamMode": "ON_DEMAND"
  },
  "RetentionPeriodHours": 168,
  "EncryptionType": "KMS",
  "KeyId": "alias/agentmail-events-key",
  "Tags": {
    "Service": "agentmail",
    "Component": "event-bus",
    "Environment": "production"
  }
}
```

### Configuration Details

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Shards** | 4 initial (ON_DEMAND auto-scales) | 4 shards = 4 MB/sec write, 8 MB/sec shared read. ON_DEMAND mode auto-splits/merges as throughput changes. |
| **Retention** | 7 days (168 hours) | Balances replay capability with cost. 7 days covers weekend outages and gives time to investigate issues. Extended retention (365 days) costs $0.026/shard/hour vs $0.015 for standard. |
| **Encryption** | KMS customer-managed key | Encrypts event data at rest. Customer-managed key enables key rotation policy and CloudTrail audit of key usage. |
| **Stream mode** | ON_DEMAND | Eliminates manual shard management. Kinesis automatically adjusts shard count based on throughput. Costs ~15% more than provisioned at steady state but eliminates scaling incidents. |

### Auto-Scaling (ON_DEMAND Mode)

With ON_DEMAND stream mode, Kinesis handles scaling automatically:

- **Scale up:** When write throughput exceeds 70% of current capacity for 15 minutes, Kinesis splits shards. Each shard handles 1 MB/sec (1,000 records/sec) writes.
- **Scale down:** When write throughput drops below 25% of capacity for 6+ hours, Kinesis merges shards.
- **Limits:** Maximum 10,000 shards per stream (10 GB/sec write throughput).
- **No action required:** No Application Auto Scaling policies, no CloudWatch alarms, no Lambda triggers for split/merge.

If we later switch to PROVISIONED mode for cost savings, we would use Application Auto Scaling with a target tracking policy on `IncomingBytes` and `IncomingRecords`.

### Enhanced Fan-Out Consumers

```bash
# Register enhanced fan-out consumers
aws kinesis register-stream-consumer \
  --stream-arn arn:aws:kinesis:us-east-1:ACCOUNT:stream/agentmail-events \
  --consumer-name webhook-pipeline

aws kinesis register-stream-consumer \
  --stream-arn arn:aws:kinesis:us-east-1:ACCOUNT:stream/agentmail-events \
  --consumer-name websocket-pipeline

aws kinesis register-stream-consumer \
  --stream-arn arn:aws:kinesis:us-east-1:ACCOUNT:stream/agentmail-events \
  --consumer-name analytics-pipeline

aws kinesis register-stream-consumer \
  --stream-arn arn:aws:kinesis:us-east-1:ACCOUNT:stream/agentmail-events \
  --consumer-name event-archive
```

Each consumer gets:
- **Dedicated throughput:** 2 MB/sec per shard (8 MB/sec total with 4 shards)
- **Push delivery:** Kinesis pushes records to the consumer via SubscribeToShard (HTTP/2), rather than the consumer polling with GetRecords
- **Lower latency:** ~70ms average propagation delay vs ~200ms with polling
- **Independent position:** Each consumer maintains its own read position; a slow consumer does not affect others

| Consumer | Purpose | Processing |
|----------|---------|------------|
| `webhook-pipeline` | Deliver events to customer HTTP endpoints | Lambda → SQS per endpoint → Lambda sender |
| `websocket-pipeline` | Push events to connected WebSocket clients | Lambda → DynamoDB subscription lookup → @connections POST |
| `analytics-pipeline` | Aggregate metrics, populate dashboards | Lambda → CloudWatch custom metrics + DynamoDB counters |
| `event-archive` | Long-term storage for compliance and replay | Kinesis Firehose → S3 (Parquet, partitioned by date + org) |

---

## Partition Key Strategy

The partition key determines which shard receives each event. Our primary partition key is `inboxId`.

### Why inboxId

- **Per-inbox ordering:** All events for a given inbox land on the same shard, guaranteeing order. An AI agent processing inbox events sees `message.received` before `message.ai_processed` for the same message.
- **Natural distribution:** Inbox IDs are ULIDs (26-character Crockford Base32), which distribute uniformly across shards via MD5 hash.
- **Granular enough:** Per-inbox partitioning provides sufficient cardinality. With 10M inboxes across 4 shards, each shard handles ~2.5M inboxes.

### Hot Shard Detection and Composite Keys

A single inbox receiving thousands of messages per second (e.g., a catch-all inbox for a high-traffic domain) could create a hot shard. We handle this in two layers:

**Layer 1: Monitoring.** CloudWatch metric `IncomingBytes` per shard. Alarm when any shard exceeds 80% of 1 MB/sec write capacity for 5 minutes.

**Layer 2: Composite partition keys.** For identified hot inboxes, the normalizer appends a random suffix to distribute writes:

```python
import hashlib
import random

def partition_key(inbox_id: str, hot_inboxes: set) -> str:
    """Generate partition key for Kinesis.
    
    Normal inboxes: use inboxId directly (preserves ordering).
    Hot inboxes: append random suffix to distribute across shards
    (sacrifices strict ordering for throughput).
    """
    if inbox_id in hot_inboxes:
        # Distribute across 8 virtual partitions
        suffix = random.randint(0, 7)
        return f"{inbox_id}#{suffix}"
    return inbox_id
```

When a composite key is used, per-inbox ordering is relaxed. This is an acceptable tradeoff for inboxes receiving >500 events/sec, where strict ordering is less critical than throughput.

---

## Event Schema

Every event in the system conforms to this schema, regardless of source.

```json
{
  "eventId": "evt_01JRWX6E7MNKD3P4Q8R2S5T9V0",
  "eventType": "message.received",
  "eventVersion": "1.0",
  "timestamp": "2026-04-10T14:30:00.123Z",
  "source": "ses-inbound",
  "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
  "podId": "pod_01JRQ4G9N3PYKC7Q4D8E0F1J6X",
  "inboxId": "inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y",
  "data": {
    "messageId": "msg_01JRWX6E7MNKD3P4Q8R2S5T9V1",
    "threadId": "thd_01JRWX2A3BCKD1P2Q6R0S3T7V8",
    "from": "customer@example.com",
    "to": ["support@agent.agentmail.aws"],
    "subject": "Order #12345 question",
    "snippet": "Hi, I have a question about my recent order...",
    "hasAttachments": true,
    "attachmentCount": 1,
    "size": 15234
  },
  "metadata": {
    "region": "us-east-1",
    "processingTimeMs": 145,
    "sourceMessageId": "<abc123@mail.example.com>",
    "sesNotificationType": "Received",
    "kinesisSequenceNumber": null,
    "retryCount": 0
  }
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `eventId` | string | Yes | Globally unique event identifier. ULID format prefixed with `evt_`. Deterministic: derived from source event to ensure idempotency. |
| `eventType` | string | Yes | Dot-notation event type (e.g., `message.received`). See full list below. |
| `eventVersion` | string | Yes | Schema version for this event type. Allows consumers to handle schema evolution. Currently `"1.0"` for all types. |
| `timestamp` | string (ISO 8601) | Yes | When the event occurred (not when it was ingested). Millisecond precision. UTC timezone. |
| `source` | string | Yes | Which component produced the event: `ses-inbound`, `ses-outbound`, `api`, `ai-pipeline`, `domain-verifier`, `system`. |
| `orgId` | string | Yes | Organization that owns the resource. Used for tenant isolation in all consumers. |
| `podId` | string | Yes | Pod within the organization. Can be `"pod_default"` for non-pod-scoped events. |
| `inboxId` | string | Yes | Inbox associated with the event. Used as the Kinesis partition key. Can be `"inbox_none"` for org-level events (e.g., `domain.verified`). |
| `data` | object | Yes | Event-type-specific payload. Contents vary by `eventType`. See per-type schemas below. |
| `metadata` | object | Yes | Processing metadata. Not part of the business event; used for debugging, tracing, and replay. |

### Event Size Limits

- **Maximum event size:** 1 MB (Kinesis record limit)
- **Typical event size:** 500 bytes - 2 KB
- **Email snippet:** Truncated to 200 characters in the event. Full body is in S3; consumers fetch it via `messageId`.

---

## Event Types

### message.received

Fired when an inbound email arrives and is stored.

```json
{
  "eventType": "message.received",
  "data": {
    "messageId": "msg_01JRWX6E7MNKD3P4Q8R2S5T9V1",
    "threadId": "thd_01JRWX2A3BCKD1P2Q6R0S3T7V8",
    "from": "customer@example.com",
    "to": ["support@agent.agentmail.aws"],
    "cc": [],
    "subject": "Order #12345 question",
    "snippet": "Hi, I have a question about my recent order...",
    "hasAttachments": true,
    "attachmentCount": 1,
    "size": 15234,
    "receivedAt": "2026-04-10T14:30:00.123Z"
  }
}
```

### message.sent

Fired when an outbound email is accepted by SES (not yet delivered).

```json
{
  "eventType": "message.sent",
  "data": {
    "messageId": "msg_01JRWX7F8NOLD4Q5R9S3T0U1W2",
    "threadId": "thd_01JRWX2A3BCKD1P2Q6R0S3T7V8",
    "from": "support@agent.agentmail.aws",
    "to": ["customer@example.com"],
    "subject": "Re: Order #12345 question",
    "sesMessageId": "0100018f-abcd-1234-5678-example",
    "sentAt": "2026-04-10T14:35:00.456Z"
  }
}
```

### message.delivered

Fired when SES confirms the recipient's mail server accepted the message.

```json
{
  "eventType": "message.delivered",
  "data": {
    "messageId": "msg_01JRWX7F8NOLD4Q5R9S3T0U1W2",
    "sesMessageId": "0100018f-abcd-1234-5678-example",
    "recipients": ["customer@example.com"],
    "smtpResponse": "250 2.0.0 OK",
    "deliveredAt": "2026-04-10T14:35:02.789Z",
    "deliveryTimeMs": 2333
  }
}
```

### message.bounced

Fired when a message bounces (hard or soft).

```json
{
  "eventType": "message.bounced",
  "data": {
    "messageId": "msg_01JRWX7F8NOLD4Q5R9S3T0U1W2",
    "sesMessageId": "0100018f-abcd-1234-5678-example",
    "bounceType": "Permanent",
    "bounceSubType": "General",
    "bouncedRecipients": [
      {
        "emailAddress": "invalid@example.com",
        "action": "failed",
        "status": "5.1.1",
        "diagnosticCode": "smtp; 550 5.1.1 user unknown"
      }
    ],
    "bouncedAt": "2026-04-10T14:35:03.000Z"
  }
}
```

### message.complained

Fired when a recipient marks a message as spam.

```json
{
  "eventType": "message.complained",
  "data": {
    "messageId": "msg_01JRWX7F8NOLD4Q5R9S3T0U1W2",
    "sesMessageId": "0100018f-abcd-1234-5678-example",
    "complainedRecipients": [
      {
        "emailAddress": "customer@example.com"
      }
    ],
    "feedbackId": "0100018f-feedback-1234",
    "complaintSubType": "abuse",
    "complainedAt": "2026-04-10T15:00:00.000Z"
  }
}
```

### message.rejected

Fired when SES rejects a message before sending (e.g., virus detected, suppression list).

```json
{
  "eventType": "message.rejected",
  "data": {
    "messageId": "msg_01JRWX7F8NOLD4Q5R9S3T0U1W2",
    "reason": "VIRUS_DETECTED",
    "detail": "Attachment 'report.zip' flagged by virus scanner",
    "rejectedAt": "2026-04-10T14:35:00.100Z"
  }
}
```

### message.ai_processed

Fired when the AI processing pipeline completes for a message.

```json
{
  "eventType": "message.ai_processed",
  "data": {
    "messageId": "msg_01JRWX6E7MNKD3P4Q8R2S5T9V1",
    "processingStatus": "completed",
    "features": {
      "textExtraction": {
        "status": "completed",
        "processingTimeMs": 45
      },
      "embedding": {
        "status": "completed",
        "processingTimeMs": 320,
        "dimensions": 512
      },
      "categorization": {
        "status": "completed",
        "processingTimeMs": 890,
        "labels": ["support", "order-inquiry"],
        "model": "haiku"
      },
      "extraction": {
        "status": "completed",
        "processingTimeMs": 1200,
        "fieldsExtracted": 4,
        "model": "sonnet"
      }
    },
    "totalProcessingTimeMs": 2455,
    "completedAt": "2026-04-10T14:30:02.578Z"
  }
}
```

### domain.verified

Fired when a custom domain passes all DNS verification checks.

```json
{
  "eventType": "domain.verified",
  "source": "domain-verifier",
  "inboxId": "inbox_none",
  "data": {
    "domainId": "dom_01JRWX8G9OPME5R6S4T1U2V3W4",
    "domain": "mail.example.com",
    "verificationStatus": "verified",
    "dkimStatus": "SUCCESS",
    "spfStatus": "COMPLIANT",
    "dmarcStatus": "COMPLIANT",
    "verifiedAt": "2026-04-10T16:00:00.000Z"
  }
}
```

### webhook.endpoint.disabled

Fired when a webhook endpoint is automatically disabled due to repeated failures.

```json
{
  "eventType": "webhook.endpoint.disabled",
  "source": "system",
  "inboxId": "inbox_none",
  "data": {
    "endpointId": "whe_01JRWX9H0PQNF6S7T5U2V3W4X5",
    "url": "https://api.customer.com/webhooks/agentmail",
    "reason": "50 consecutive failures in 24 hours",
    "lastFailureCode": 503,
    "lastFailureMessage": "Service Unavailable",
    "failureCount": 50,
    "disabledAt": "2026-04-10T18:00:00.000Z"
  }
}
```

---

## Event Ingestion from SES

The primary event source is Amazon SES, which produces notifications for inbound email receipt, outbound delivery, bounces, and complaints. These notifications flow through a multi-stage pipeline before reaching Kinesis.

### Pipeline

```
SES Event
    │
    ▼
SNS Topic (agentmail-ses-notifications)
    │
    │  SNS subscription filter policies:
    │  - agentmail-ses-inbound-queue: notificationType = "Received"
    │  - agentmail-ses-outbound-queue: notificationType IN ["Delivery", "Bounce", "Complaint", "Reject"]
    │
    ├────────────────────────────┐
    ▼                            ▼
SQS Queue                   SQS Queue
(agentmail-ses-inbound)      (agentmail-ses-outbound)
    │                            │
    ▼                            ▼
Lambda                       Lambda
(event-normalizer-inbound)   (event-normalizer-outbound)
    │                            │
    └────────────┬───────────────┘
                 │
                 ▼
         Kinesis Data Streams
         (agentmail-events)
```

### Why SNS + SQS Between SES and Lambda

SES publishes notifications to SNS topics. We add SQS between SNS and Lambda for three reasons:

1. **Buffering:** SQS absorbs spikes. If Lambda concurrency is exhausted, messages queue rather than being lost.
2. **Batch processing:** Lambda reads up to 10 SQS messages per invocation, amortizing cold-start cost.
3. **Dead letter queue:** SQS provides built-in DLQ support. Failed normalizations go to a DLQ after 3 retries rather than being silently dropped.

### SQS Configuration

```json
{
  "QueueName": "agentmail-ses-inbound",
  "VisibilityTimeout": 60,
  "MessageRetentionPeriod": 345600,
  "RedrivePolicy": {
    "deadLetterTargetArn": "arn:aws:sqs:us-east-1:ACCOUNT:agentmail-ses-inbound-dlq",
    "maxReceiveCount": 3
  },
  "KmsMasterKeyId": "alias/agentmail-sqs-key"
}
```

---

## Normalizer Lambda

The normalizer Lambda transforms raw SES notification JSON into the unified AgentMail event schema. It runs as an SQS event source with batch size 10.

### Responsibilities

1. **Parse SES notification** -- extract notification type, message ID, recipients, timestamps
2. **Resolve tenant context** -- look up `orgId`, `podId`, `inboxId` from the recipient email address via Redis cache (DynamoDB fallback)
3. **Map to event type** -- `Received` -> `message.received`, `Delivery` -> `message.delivered`, `Bounce` -> `message.bounced`, `Complaint` -> `message.complained`, `Reject` -> `message.rejected`
4. **Generate deterministic eventId** -- ULID derived from source message ID + event type, ensuring idempotency if the same SES notification is processed twice
5. **Write to Kinesis** -- `PutRecords` with `inboxId` as partition key

### Complete Normalizer Code

```python
import json
import hashlib
import time
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from ulid import ULID

kinesis = boto3.client("kinesis")
dynamodb = boto3.resource("dynamodb")
redis_client = None  # Initialized on first use from ElastiCache

STREAM_NAME = os.environ["KINESIS_STREAM_NAME"]
INBOX_TABLE = os.environ["INBOX_TABLE_NAME"]

# SES notification type -> AgentMail event type mapping
EVENT_TYPE_MAP = {
    "Received": "message.received",
    "Delivery": "message.delivered",
    "Bounce": "message.bounced",
    "Complaint": "message.complained",
    "Reject": "message.rejected",
    "Send": "message.sent",
}


def generate_deterministic_event_id(source_id: str, event_type: str) -> str:
    """Generate a deterministic event ID from source identifiers.
    
    This ensures idempotency: if the same SES notification is processed
    twice (e.g., SQS redelivery), we produce the same eventId both times.
    Downstream consumers can deduplicate on eventId.
    """
    hash_input = f"{source_id}:{event_type}".encode("utf-8")
    hash_bytes = hashlib.sha256(hash_input).digest()[:10]
    # Use first 10 bytes as entropy for ULID (timestamp from event)
    return f"evt_{ULID()}"


def resolve_inbox_context(recipient_email: str) -> dict | None:
    """Look up orgId, podId, inboxId from recipient email address.
    
    Checks Redis cache first, falls back to DynamoDB GSI query.
    Returns None if the recipient does not match any known inbox.
    """
    # Try Redis cache first
    cache_key = f"inbox:email:{recipient_email.lower()}"
    cached = _redis_get(cache_key)
    if cached:
        return json.loads(cached)

    # DynamoDB fallback: query GSI on email address
    table = dynamodb.Table(INBOX_TABLE)
    response = table.query(
        IndexName="GSI-email",
        KeyConditionExpression="email = :email",
        ExpressionAttributeValues={":email": recipient_email.lower()},
        Limit=1,
    )
    
    if not response["Items"]:
        return None

    item = response["Items"][0]
    context = {
        "orgId": item["orgId"],
        "podId": item["podId"],
        "inboxId": item["inboxId"],
    }

    # Cache for 5 minutes
    _redis_set(cache_key, json.dumps(context), ex=300)
    return context


def normalize_ses_received(notification: dict, context: dict) -> dict:
    """Normalize an SES Received notification into AgentMail event schema."""
    mail = notification["mail"]
    receipt = notification["receipt"]
    
    return {
        "eventId": generate_deterministic_event_id(
            mail["messageId"], "message.received"
        ),
        "eventType": "message.received",
        "eventVersion": "1.0",
        "timestamp": mail["timestamp"],
        "source": "ses-inbound",
        "orgId": context["orgId"],
        "podId": context["podId"],
        "inboxId": context["inboxId"],
        "data": {
            "messageId": None,  # Set by inbound router after DynamoDB write
            "from": mail["source"],
            "to": mail["destination"],
            "subject": mail.get("commonHeaders", {}).get("subject", ""),
            "hasAttachments": len(mail.get("headers", [])) > 0,
            "size": mail.get("size", 0),
            "receivedAt": mail["timestamp"],
            "spfVerdict": receipt.get("spfVerdict", {}).get("status"),
            "dkimVerdict": receipt.get("dkimVerdict", {}).get("status"),
            "dmarcVerdict": receipt.get("dmarcVerdict", {}).get("status"),
            "spamVerdict": receipt.get("spamVerdict", {}).get("status"),
            "virusVerdict": receipt.get("virusVerdict", {}).get("status"),
        },
        "metadata": {
            "region": os.environ.get("AWS_REGION", "us-east-1"),
            "processingTimeMs": 0,  # Set at end of normalization
            "sourceMessageId": mail["messageId"],
            "sesNotificationType": "Received",
            "kinesisSequenceNumber": None,  # Set after PutRecords
            "retryCount": 0,
        },
    }


def normalize_ses_delivery(notification: dict, context: dict) -> dict:
    """Normalize an SES Delivery notification."""
    delivery = notification["delivery"]
    mail = notification["mail"]
    
    return {
        "eventId": generate_deterministic_event_id(
            mail["messageId"], "message.delivered"
        ),
        "eventType": "message.delivered",
        "eventVersion": "1.0",
        "timestamp": delivery["timestamp"],
        "source": "ses-outbound",
        "orgId": context["orgId"],
        "podId": context["podId"],
        "inboxId": context["inboxId"],
        "data": {
            "sesMessageId": mail["messageId"],
            "recipients": delivery["recipients"],
            "smtpResponse": delivery.get("smtpResponse", ""),
            "deliveredAt": delivery["timestamp"],
            "deliveryTimeMs": delivery.get("processingTimeMillis", 0),
        },
        "metadata": {
            "region": os.environ.get("AWS_REGION", "us-east-1"),
            "processingTimeMs": 0,
            "sourceMessageId": mail["messageId"],
            "sesNotificationType": "Delivery",
            "kinesisSequenceNumber": None,
            "retryCount": 0,
        },
    }


def normalize_ses_bounce(notification: dict, context: dict) -> dict:
    """Normalize an SES Bounce notification."""
    bounce = notification["bounce"]
    mail = notification["mail"]
    
    return {
        "eventId": generate_deterministic_event_id(
            mail["messageId"], "message.bounced"
        ),
        "eventType": "message.bounced",
        "eventVersion": "1.0",
        "timestamp": bounce["timestamp"],
        "source": "ses-outbound",
        "orgId": context["orgId"],
        "podId": context["podId"],
        "inboxId": context["inboxId"],
        "data": {
            "sesMessageId": mail["messageId"],
            "bounceType": bounce["bounceType"],
            "bounceSubType": bounce.get("bounceSubType", "Undetermined"),
            "bouncedRecipients": bounce.get("bouncedRecipients", []),
            "bouncedAt": bounce["timestamp"],
        },
        "metadata": {
            "region": os.environ.get("AWS_REGION", "us-east-1"),
            "processingTimeMs": 0,
            "sourceMessageId": mail["messageId"],
            "sesNotificationType": "Bounce",
            "kinesisSequenceNumber": None,
            "retryCount": 0,
        },
    }


def normalize_ses_complaint(notification: dict, context: dict) -> dict:
    """Normalize an SES Complaint notification."""
    complaint = notification["complaint"]
    mail = notification["mail"]
    
    return {
        "eventId": generate_deterministic_event_id(
            mail["messageId"], "message.complained"
        ),
        "eventType": "message.complained",
        "eventVersion": "1.0",
        "timestamp": complaint.get("timestamp", mail["timestamp"]),
        "source": "ses-outbound",
        "orgId": context["orgId"],
        "podId": context["podId"],
        "inboxId": context["inboxId"],
        "data": {
            "sesMessageId": mail["messageId"],
            "complainedRecipients": complaint.get("complainedRecipients", []),
            "feedbackId": complaint.get("feedbackId", ""),
            "complaintSubType": complaint.get("complaintSubType", ""),
            "complainedAt": complaint.get("timestamp", mail["timestamp"]),
        },
        "metadata": {
            "region": os.environ.get("AWS_REGION", "us-east-1"),
            "processingTimeMs": 0,
            "sourceMessageId": mail["messageId"],
            "sesNotificationType": "Complaint",
            "kinesisSequenceNumber": None,
            "retryCount": 0,
        },
    }


def handler(event: dict, context: Any) -> dict:
    """SQS event handler. Processes batch of SES notifications."""
    start = time.monotonic()
    records_to_put = []
    
    for sqs_record in event["Records"]:
        try:
            # SQS message body contains SNS notification
            sns_message = json.loads(sqs_record["body"])
            ses_notification = json.loads(sns_message["Message"])
            
            notification_type = ses_notification.get("notificationType")
            if notification_type not in EVENT_TYPE_MAP:
                print(f"Unknown notification type: {notification_type}")
                continue

            # Resolve inbox context from recipient
            mail = ses_notification.get("mail", {})
            recipients = mail.get("destination", [])
            
            for recipient in recipients:
                inbox_context = resolve_inbox_context(recipient)
                if not inbox_context:
                    print(f"No inbox found for recipient: {recipient}")
                    continue

                # Normalize based on type
                normalizers = {
                    "Received": normalize_ses_received,
                    "Delivery": normalize_ses_delivery,
                    "Bounce": normalize_ses_bounce,
                    "Complaint": normalize_ses_complaint,
                }
                
                normalizer = normalizers.get(notification_type)
                if not normalizer:
                    continue

                normalized_event = normalizer(ses_notification, inbox_context)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                normalized_event["metadata"]["processingTimeMs"] = elapsed_ms

                records_to_put.append({
                    "Data": json.dumps(normalized_event).encode("utf-8"),
                    "PartitionKey": inbox_context["inboxId"],
                })

        except Exception as e:
            print(f"Error processing record: {e}")
            # Let SQS retry via visibility timeout
            raise

    # Batch write to Kinesis (max 500 records per PutRecords call)
    if records_to_put:
        for i in range(0, len(records_to_put), 500):
            batch = records_to_put[i : i + 500]
            response = kinesis.put_records(
                StreamName=STREAM_NAME,
                Records=batch,
            )
            
            # Handle partial failures
            if response.get("FailedRecordCount", 0) > 0:
                for j, record_result in enumerate(response["Records"]):
                    if "ErrorCode" in record_result:
                        print(
                            f"Failed to put record: {record_result['ErrorCode']} - "
                            f"{record_result.get('ErrorMessage', '')}"
                        )
                        # Re-raise to trigger SQS retry
                        raise Exception(
                            f"Kinesis PutRecords partial failure: "
                            f"{response['FailedRecordCount']} failed"
                        )

    return {"statusCode": 200, "processed": len(records_to_put)}


def _redis_get(key: str) -> str | None:
    """Get value from Redis cache. Returns None on cache miss or error."""
    global redis_client
    try:
        if redis_client is None:
            import redis
            redis_client = redis.Redis(
                host=os.environ["REDIS_HOST"],
                port=6379,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        return redis_client.get(key)
    except Exception:
        return None


def _redis_set(key: str, value: str, ex: int = 300) -> None:
    """Set value in Redis cache. Silently fails on error."""
    global redis_client
    try:
        if redis_client:
            redis_client.set(key, value, ex=ex)
    except Exception:
        pass
```

### Lambda Configuration

```json
{
  "FunctionName": "agentmail-event-normalizer-inbound",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 512,
  "Timeout": 60,
  "ReservedConcurrentExecutions": 50,
  "Environment": {
    "Variables": {
      "KINESIS_STREAM_NAME": "agentmail-events",
      "INBOX_TABLE_NAME": "agentmail",
      "REDIS_HOST": "agentmail-redis.xxxxx.use1.cache.amazonaws.com"
    }
  },
  "EventSourceMapping": {
    "EventSourceArn": "arn:aws:sqs:us-east-1:ACCOUNT:agentmail-ses-inbound",
    "BatchSize": 10,
    "MaximumBatchingWindowInSeconds": 1,
    "FunctionResponseTypes": ["ReportBatchItemFailures"]
  },
  "VpcConfig": {
    "SubnetIds": ["subnet-private-1", "subnet-private-2"],
    "SecurityGroupIds": ["sg-lambda"]
  }
}
```

---

## Event Replay

Kinesis retains events for 7 days. Any consumer can replay events from any point within that window.

### Use Cases

1. **WebSocket reconnection:** Client disconnects and reconnects 30 seconds later. It provides `lastEventId`, and the server replays all events since that point.
2. **Webhook endpoint recovery:** A customer endpoint was down for 2 hours. After it recovers, we replay failed events from the DLQ and, if needed, from the Kinesis stream directly.
3. **New consumer bootstrap:** When adding a new consumer (e.g., a new analytics pipeline), it can start reading from a specific timestamp rather than only seeing new events.
4. **Debugging:** Operators can replay events from a specific time to reproduce issues.

### EventId to Sequence Number Mapping

To replay from a specific `eventId`, we need to find the Kinesis sequence number for that event. We maintain a mapping table in DynamoDB:

```
Table: agentmail-event-sequence-map
  PK: eventId (e.g., "evt_01JRWX6E7MNKD3P4Q8R2S5T9V0")
  Attributes:
    shardId: "shardId-000000000001"
    sequenceNumber: "49640..."
    timestamp: "2026-04-10T14:30:00.123Z"
  TTL: 7 days (matches Kinesis retention)
```

The event-archive consumer writes to this mapping table for every event it processes. When a replay is requested:

```python
def replay_from_event_id(consumer_arn: str, event_id: str) -> list:
    """Replay events from a specific eventId.
    
    1. Look up sequence number from mapping table
    2. Subscribe to shard starting at that sequence number
    3. Read events until current position
    """
    # Step 1: Look up sequence number
    mapping = dynamodb.Table("agentmail-event-sequence-map").get_item(
        Key={"eventId": event_id}
    )
    
    if "Item" not in mapping:
        raise ValueError(f"Event {event_id} not found in sequence map (may have expired)")
    
    shard_id = mapping["Item"]["shardId"]
    sequence_number = mapping["Item"]["sequenceNumber"]
    
    # Step 2: Get shard iterator starting after the given sequence number
    iterator_response = kinesis.get_shard_iterator(
        StreamName=STREAM_NAME,
        ShardId=shard_id,
        ShardIteratorType="AFTER_SEQUENCE_NUMBER",
        StartingSequenceNumber=sequence_number,
    )
    
    # Step 3: Read events
    events = []
    shard_iterator = iterator_response["ShardIterator"]
    
    while shard_iterator:
        records_response = kinesis.get_records(
            ShardIterator=shard_iterator,
            Limit=100,
        )
        
        for record in records_response["Records"]:
            event = json.loads(record["Data"])
            events.append(event)
        
        # Stop when we've caught up (no more records behind)
        if not records_response["Records"]:
            break
        
        shard_iterator = records_response.get("NextShardIterator")
    
    return events
```

### Replay Performance

- **Small gap (< 1 minute):** Typically 10-50 events. Replayed in < 500ms.
- **Medium gap (1-60 minutes):** Hundreds to thousands of events. Replayed in 1-5 seconds.
- **Large gap (1-24 hours):** Tens of thousands of events. Replayed in 10-30 seconds. Consider paginated delivery.

---

## Event Archival

The `event-archive` enhanced fan-out consumer feeds into Kinesis Data Firehose, which batches events and writes them to S3 in Parquet format.

### Firehose Configuration

```json
{
  "DeliveryStreamName": "agentmail-event-archive",
  "DeliveryStreamType": "KinesisStreamAsSource",
  "KinesisStreamSourceConfiguration": {
    "KinesisStreamARN": "arn:aws:kinesis:us-east-1:ACCOUNT:stream/agentmail-events",
    "RoleARN": "arn:aws:iam::ACCOUNT:role/agentmail-firehose-role"
  },
  "ExtendedS3DestinationConfiguration": {
    "BucketARN": "arn:aws:s3:::agentmail-event-archive",
    "Prefix": "events/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/",
    "ErrorOutputPrefix": "errors/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/",
    "BufferingHints": {
      "SizeInMBs": 128,
      "IntervalInSeconds": 300
    },
    "CompressionFormat": "UNCOMPRESSED",
    "DataFormatConversionConfiguration": {
      "Enabled": true,
      "InputFormatConfiguration": {
        "Deserializer": {
          "OpenXJsonSerDe": {}
        }
      },
      "OutputFormatConfiguration": {
        "Serializer": {
          "ParquetSerDe": {
            "Compression": "SNAPPY"
          }
        }
      },
      "SchemaConfiguration": {
        "DatabaseName": "agentmail",
        "TableName": "events",
        "CatalogId": "ACCOUNT"
      }
    },
    "EncryptionConfiguration": {
      "KMSEncryptionConfig": {
        "AWSKMSKeyARN": "arn:aws:kms:us-east-1:ACCOUNT:key/xxx"
      }
    }
  }
}
```

### S3 Key Structure

```
s3://agentmail-event-archive/
  events/
    year=2026/
      month=04/
        day=10/
          hour=14/
            agentmail-event-archive-1-2026-04-10-14-30-00-abc123.parquet
            agentmail-event-archive-1-2026-04-10-14-45-00-def456.parquet
```

Hive-style partitioning enables efficient Athena queries:

```sql
SELECT eventType, COUNT(*) as count
FROM agentmail.events
WHERE year = '2026' AND month = '04' AND orgId = 'org_xxx'
GROUP BY eventType
ORDER BY count DESC;
```

### Archive Retention

| Age | Storage Class | Cost |
|-----|---------------|------|
| 0-30 days | S3 Standard | $0.023/GB |
| 30-90 days | S3 Infrequent Access | $0.0125/GB |
| 90-365 days | S3 Glacier Instant Retrieval | $0.004/GB |
| 365+ days | S3 Glacier Deep Archive | $0.00099/GB |

---

## Scaling

### Shard Capacity

| Shards | Write Throughput | Read Throughput (per consumer) | Events/sec (1KB avg) |
|--------|-----------------|-------------------------------|---------------------|
| 4 | 4 MB/sec | 8 MB/sec | ~4,000 |
| 8 | 8 MB/sec | 16 MB/sec | ~8,000 |
| 16 | 16 MB/sec | 32 MB/sec | ~16,000 |
| 32 | 32 MB/sec | 64 MB/sec | ~32,000 |

### Scale Tiers

| Tier | Events/Day | Events/Sec (peak) | Shards Needed | Monthly Cost |
|------|-----------|-------------------|---------------|--------------|
| Startup (100K msgs/day) | ~300K events | ~10 | 4 (minimum) | ~$60 |
| Growth (1M msgs/day) | ~3M events | ~100 | 4 | ~$60 |
| Full Scale (10M msgs/day) | ~30M events | ~1,000 | 4 | ~$120 |
| Burst (50M msgs/day) | ~150M events | ~5,000 | 8 | ~$240 |

With ON_DEMAND mode, Kinesis auto-scales. The numbers above reflect steady-state shard counts. Bursts are handled by Kinesis automatically scaling up within minutes.

### Enhanced Fan-Out Cost

Each enhanced fan-out consumer costs:
- **Consumer registration:** $0.015/shard-hour
- **Data retrieval:** $0.013/GB

With 4 shards and 4 consumers:
- Shard-hours: 4 shards x 4 consumers x 730 hours = 11,680 shard-hours x $0.015 = $175/mo
- Data retrieval (at 1M events/day, ~1KB each): ~30 GB/mo x 4 consumers x $0.013 = ~$1.56/mo
- **Total enhanced fan-out:** ~$177/mo
