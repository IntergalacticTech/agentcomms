# Webhook Delivery System

The webhook system delivers platform events to customer-specified HTTP endpoints with HMAC-SHA256 signatures, automatic retry with exponential backoff, and delivery logging for every attempt. Customers register webhook endpoints scoped to an organization, a pod, or a specific inbox, and AgentMail delivers matching events via HTTP POST within seconds of occurrence.

---

## Data Model

### webhook-endpoints Table

Webhook endpoints are stored in the main AgentMail DynamoDB table using composite keys.

```
Entity: WebhookEndpoint
  PK: ORG#{orgId}
  SK: WHE#{endpointId}

  Attributes:
    endpointId:    "whe_01JRWX9H0PQNF6S7T5U2V3W4X5"
    orgId:         "org_01JRQ4F8M2NXKB6P3C7D9E0H5W"
    podId:         "pod_01JRQ4G9N3PYKC7Q4D8E0F1J6X" | null   (null = org-wide)
    inboxId:       "inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y" | null  (null = pod-wide or org-wide)
    url:           "https://api.customer.com/webhooks/agentmail"
    secret:        "whsec_K7dF9mN2pQ4xR8sT1vW3yA6bC0eG5hJ"  (encrypted at rest)
    eventTypes:    ["message.received", "message.bounced"]     (empty = all types)
    status:        "active" | "disabled" | "pending_validation"
    description:   "Production webhook for support inbox"
    createdAt:     "2026-04-10T10:00:00.000Z"
    updatedAt:     "2026-04-10T10:00:00.000Z"
    disabledAt:    null
    disabledReason: null
    failureCount:  0
    lastDeliveryAt: "2026-04-10T14:30:01.200Z"
    lastFailureAt:  null
    metadata:      {}

  GSI: GSI-webhook-scope
    PK: WHSCOPE#{orgId}#{podId}#{inboxId}
    SK: WHE#{endpointId}
    Purpose: Query all endpoints matching a given scope level
```

### Webhook Delivery Logs

Every delivery attempt -- success or failure -- is logged.

```
Entity: WebhookDeliveryLog
  PK: WHE#{endpointId}
  SK: WHDEL#{timestamp}#{attemptId}

  Attributes:
    endpointId:    "whe_01JRWX9H0PQNF6S7T5U2V3W4X5"
    eventId:       "evt_01JRWX6E7MNKD3P4Q8R2S5T9V0"
    eventType:     "message.received"
    attemptNumber: 1
    status:        "success" | "failure" | "timeout"
    httpStatusCode: 200
    responseTimeMs: 145
    errorMessage:   null
    requestUrl:    "https://api.customer.com/webhooks/agentmail"
    requestHeaders: { "Content-Type": "application/json", "X-AgentMail-Event-Id": "..." }
    responseBody:  ""   (truncated to 1KB)
    attemptedAt:   "2026-04-10T14:30:01.200Z"
    ttl:           1746057600  (30 days from creation, epoch seconds)

  GSI: GSI-event-deliveries
    PK: EVT#{eventId}
    SK: WHE#{endpointId}#{attemptNumber}
    Purpose: Look up all delivery attempts for a specific event
```

---

## Pipeline Architecture

```
Kinesis Data Streams (agentmail-events)
    │
    │  Enhanced fan-out consumer: webhook-pipeline
    │
    ▼
Lambda: webhook-dispatcher
    │
    │  For each event:
    │  1. Query matching webhook endpoints (see fan-out algorithm)
    │  2. For each matching endpoint, enqueue SQS message
    │
    ▼
SQS: agentmail-webhook-delivery (per-endpoint routing via message attributes)
    │
    │  Batch size: 1 (one delivery per invocation for isolation)
    │  Visibility timeout: 60s (allows for retry scheduling)
    │
    ▼
Lambda: webhook-sender
    │
    │  1. HMAC-SHA256 sign the payload
    │  2. POST to customer endpoint (10s timeout)
    │  3. Log delivery attempt to DynamoDB
    │  4. On failure: change SQS visibility timeout for backoff
    │  5. On final failure: send to DLQ
    │
    ├── Success ──→ DynamoDB delivery log (status: success)
    │
    └── Failure ──→ SQS visibility timeout manipulation (exponential backoff)
                    │
                    └── After 5 retries ──→ DLQ: agentmail-webhook-dlq
```

### Lambda: webhook-dispatcher

```json
{
  "FunctionName": "agentmail-webhook-dispatcher",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 512,
  "Timeout": 30,
  "ReservedConcurrentExecutions": 20,
  "Environment": {
    "Variables": {
      "SQS_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/ACCOUNT/agentmail-webhook-delivery",
      "TABLE_NAME": "agentmail"
    }
  }
}
```

### Lambda: webhook-sender

```json
{
  "FunctionName": "agentmail-webhook-sender",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 256,
  "Timeout": 30,
  "ReservedConcurrentExecutions": 100,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "DLQ_URL": "https://sqs.us-east-1.amazonaws.com/ACCOUNT/agentmail-webhook-dlq"
    }
  },
  "EventSourceMapping": {
    "EventSourceArn": "arn:aws:sqs:us-east-1:ACCOUNT:agentmail-webhook-delivery",
    "BatchSize": 1,
    "MaximumBatchingWindowInSeconds": 0
  }
}
```

---

## Fan-Out: Matching Events to Endpoints

When an event arrives, the webhook-dispatcher must find all webhook endpoints that should receive it. Endpoints are scoped at three levels: organization (receives all events for the org), pod (receives events for all inboxes in the pod), and inbox (receives events for a specific inbox only).

### Algorithm

```python
def find_matching_endpoints(event: dict) -> list[dict]:
    """Find all webhook endpoints that should receive this event.
    
    An endpoint matches if:
    1. It belongs to the same org as the event
    2. Its scope includes the event's pod/inbox:
       - Org-scoped (podId=null, inboxId=null): matches all events in the org
       - Pod-scoped (podId=X, inboxId=null): matches events with podId=X
       - Inbox-scoped (podId=X, inboxId=Y): matches events with inboxId=Y
    3. Its eventTypes filter includes the event type (or filter is empty = all types)
    4. Its status is "active"
    """
    org_id = event["orgId"]
    pod_id = event["podId"]
    inbox_id = event["inboxId"]
    event_type = event["eventType"]
    
    # Query all three scope levels in parallel using DynamoDB BatchGetItem
    # or three parallel queries on the GSI
    scope_keys = [
        f"WHSCOPE#{org_id}#null#null",          # Org-scoped endpoints
        f"WHSCOPE#{org_id}#{pod_id}#null",       # Pod-scoped endpoints
        f"WHSCOPE#{org_id}#{pod_id}#{inbox_id}", # Inbox-scoped endpoints
    ]
    
    matching_endpoints = []
    
    for scope_key in scope_keys:
        response = table.query(
            IndexName="GSI-webhook-scope",
            KeyConditionExpression="PK = :pk",
            FilterExpression="(#status = :active) AND "
                           "(size(eventTypes) = :zero OR contains(eventTypes, :eventType))",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pk": scope_key,
                ":active": "active",
                ":zero": 0,
                ":eventType": event_type,
            },
        )
        matching_endpoints.extend(response.get("Items", []))
    
    return matching_endpoints
```

### Performance Optimization

The three DynamoDB queries are executed in parallel using `asyncio` or `concurrent.futures.ThreadPoolExecutor`. Typical latency for all three queries: 10-30ms.

For high-traffic organizations with many endpoints, we cache the endpoint list in Redis with a 60-second TTL:

```python
cache_key = f"webhooks:endpoints:{org_id}"
cached = redis_client.get(cache_key)
if cached:
    all_endpoints = json.loads(cached)
    # Filter in memory for pod/inbox/event type
    return filter_endpoints(all_endpoints, pod_id, inbox_id, event_type)
```

---

## HMAC-SHA256 Signature

Every webhook delivery includes a cryptographic signature that allows the customer to verify the payload was sent by AgentMail and was not tampered with in transit.

### Signing Algorithm

```python
import hashlib
import hmac
import time
import json


def sign_webhook_payload(payload: dict, secret: str, timestamp: int = None) -> dict:
    """Sign a webhook payload with HMAC-SHA256.
    
    Args:
        payload: The event JSON payload to deliver
        secret: The webhook endpoint's secret key (whsec_...)
        timestamp: Unix epoch seconds (defaults to now)
    
    Returns:
        Dict with signature headers to include in the HTTP request
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    # Step 1: Serialize payload to canonical JSON (sorted keys, no whitespace)
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    
    # Step 2: Construct the signed content
    # Format: "{timestamp}.{payload_json}"
    signed_content = f"{timestamp}.{payload_json}"
    
    # Step 3: Compute HMAC-SHA256
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_content.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    
    return {
        "X-AgentMail-Signature": f"v1={signature}",
        "X-AgentMail-Timestamp": str(timestamp),
        "X-AgentMail-Event-Id": payload["eventId"],
    }
```

### Headers Sent with Every Webhook

| Header | Example Value | Purpose |
|--------|--------------|---------|
| `Content-Type` | `application/json` | Standard JSON content type |
| `User-Agent` | `AgentMail-Webhook/1.0` | Identifies the sender |
| `X-AgentMail-Signature` | `v1=a1b2c3d4e5f6...` | HMAC-SHA256 signature of `{timestamp}.{payload}` |
| `X-AgentMail-Timestamp` | `1712757001` | Unix epoch seconds when the signature was generated |
| `X-AgentMail-Event-Id` | `evt_01JRWX6E7MNKD3P4Q8R2S5T9V0` | Unique event ID for idempotency |
| `X-AgentMail-Delivery-Attempt` | `1` | Which attempt this is (1-5) |

### Customer Verification Instructions

Customers verify webhook signatures as follows. This is included in our API documentation:

```python
# Python verification example
import hashlib
import hmac
import time

WEBHOOK_SECRET = "whsec_K7dF9mN2pQ4xR8sT1vW3yA6bC0eG5hJ"
TOLERANCE_SECONDS = 300  # Reject events older than 5 minutes


def verify_webhook(payload_body: str, headers: dict) -> bool:
    """Verify an incoming AgentMail webhook.
    
    Args:
        payload_body: Raw request body as string (do not parse first)
        headers: Request headers dict
    
    Returns:
        True if signature is valid and timestamp is recent
    
    Raises:
        ValueError: If signature is invalid or timestamp is stale
    """
    signature_header = headers.get("X-AgentMail-Signature", "")
    timestamp_str = headers.get("X-AgentMail-Timestamp", "")
    
    if not signature_header or not timestamp_str:
        raise ValueError("Missing signature headers")
    
    # Step 1: Check timestamp freshness (prevent replay attacks)
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        raise ValueError("Invalid timestamp")
    
    if abs(time.time() - timestamp) > TOLERANCE_SECONDS:
        raise ValueError(f"Timestamp too old: {timestamp}")
    
    # Step 2: Reconstruct the signed content
    signed_content = f"{timestamp}.{payload_body}"
    
    # Step 3: Compute expected signature
    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        signed_content.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    
    # Step 4: Compare signatures (constant-time to prevent timing attacks)
    received = signature_header.removeprefix("v1=")
    if not hmac.compare_digest(expected, received):
        raise ValueError("Invalid signature")
    
    return True
```

```javascript
// Node.js verification example
const crypto = require('crypto');

const WEBHOOK_SECRET = 'whsec_K7dF9mN2pQ4xR8sT1vW3yA6bC0eG5hJ';
const TOLERANCE_SECONDS = 300;

function verifyWebhook(payloadBody, headers) {
  const signature = headers['x-agentmail-signature'];
  const timestamp = headers['x-agentmail-timestamp'];

  if (!signature || !timestamp) {
    throw new Error('Missing signature headers');
  }

  // Check timestamp freshness
  const ts = parseInt(timestamp, 10);
  if (Math.abs(Date.now() / 1000 - ts) > TOLERANCE_SECONDS) {
    throw new Error('Timestamp too old');
  }

  // Compute expected signature
  const signedContent = `${timestamp}.${payloadBody}`;
  const expected = crypto
    .createHmac('sha256', WEBHOOK_SECRET)
    .update(signedContent)
    .digest('hex');

  // Constant-time comparison
  const received = signature.replace('v1=', '');
  if (!crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(received))) {
    throw new Error('Invalid signature');
  }

  return true;
}
```

---

## Retry Strategy

Failed webhook deliveries are retried with exponential backoff using SQS visibility timeout manipulation.

### Backoff Schedule

| Attempt | Delay | Visibility Timeout | Cumulative Time |
|---------|-------|-------------------|-----------------|
| 1 | Immediate | 60s (default) | 0s |
| 2 | 10 seconds | 10s | ~10s |
| 3 | 30 seconds | 30s | ~40s |
| 4 | 60 seconds | 60s | ~100s |
| 5 | 300 seconds | 300s | ~400s (~6.5 min) |

### Implementation

```python
import json
import time
import httpx
import boto3

sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("agentmail")

RETRY_DELAYS = [0, 10, 30, 60, 300]  # Seconds for attempts 1-5
MAX_RETRIES = 5
DELIVERY_TIMEOUT = 10  # Seconds


def handler(event, context):
    """SQS-triggered Lambda that delivers a single webhook."""
    for record in event["Records"]:
        body = json.loads(record["body"])
        
        endpoint_id = body["endpointId"]
        webhook_event = body["event"]
        attempt = body.get("attemptNumber", 1)
        secret = body["secret"]  # Decrypted by dispatcher before enqueueing
        url = body["url"]
        
        # Sign the payload
        timestamp = int(time.time())
        payload_json = json.dumps(webhook_event, sort_keys=True, separators=(",", ":"))
        signed_content = f"{timestamp}.{payload_json}"
        
        import hmac as hmac_lib
        import hashlib
        signature = hmac_lib.new(
            secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentMail-Webhook/1.0",
            "X-AgentMail-Signature": f"v1={signature}",
            "X-AgentMail-Timestamp": str(timestamp),
            "X-AgentMail-Event-Id": webhook_event["eventId"],
            "X-AgentMail-Delivery-Attempt": str(attempt),
        }
        
        # Deliver
        start_time = time.monotonic()
        try:
            with httpx.Client(timeout=DELIVERY_TIMEOUT) as client:
                response = client.post(url, content=payload_json, headers=headers)
            
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            
            if 200 <= response.status_code < 300:
                # Success
                log_delivery(
                    endpoint_id=endpoint_id,
                    event_id=webhook_event["eventId"],
                    event_type=webhook_event["eventType"],
                    attempt=attempt,
                    status="success",
                    http_status=response.status_code,
                    response_time_ms=response_time_ms,
                )
                # Reset failure counter
                reset_failure_count(endpoint_id)
            else:
                # Non-2xx response - treat as failure
                handle_failure(
                    record=record,
                    body=body,
                    endpoint_id=endpoint_id,
                    event=webhook_event,
                    attempt=attempt,
                    http_status=response.status_code,
                    error_message=f"HTTP {response.status_code}: {response.text[:500]}",
                    response_time_ms=response_time_ms,
                )
                
        except httpx.TimeoutException:
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            handle_failure(
                record=record,
                body=body,
                endpoint_id=endpoint_id,
                event=webhook_event,
                attempt=attempt,
                http_status=None,
                error_message="Connection timeout after 10s",
                response_time_ms=response_time_ms,
            )
        except Exception as e:
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            handle_failure(
                record=record,
                body=body,
                endpoint_id=endpoint_id,
                event=webhook_event,
                attempt=attempt,
                http_status=None,
                error_message=str(e)[:500],
                response_time_ms=response_time_ms,
            )


def handle_failure(record, body, endpoint_id, event, attempt, http_status, error_message, response_time_ms):
    """Handle a failed delivery attempt."""
    # Log the failure
    log_delivery(
        endpoint_id=endpoint_id,
        event_id=event["eventId"],
        event_type=event["eventType"],
        attempt=attempt,
        status="failure" if http_status else "timeout",
        http_status=http_status,
        response_time_ms=response_time_ms,
        error_message=error_message,
    )
    
    # Increment failure counter
    increment_failure_count(endpoint_id)
    
    if attempt < MAX_RETRIES:
        # Schedule retry by changing SQS visibility timeout
        next_delay = RETRY_DELAYS[attempt]  # attempt is 1-indexed, next delay is at index=attempt
        
        # Re-enqueue with incremented attempt number
        sqs.send_message(
            QueueUrl=body["queueUrl"],
            MessageBody=json.dumps({
                **body,
                "attemptNumber": attempt + 1,
            }),
            DelaySeconds=min(next_delay, 900),  # SQS max delay is 900s
        )
    else:
        # Final failure - send to DLQ
        sqs.send_message(
            QueueUrl=body["dlqUrl"],
            MessageBody=json.dumps({
                "endpointId": endpoint_id,
                "event": event,
                "totalAttempts": attempt,
                "lastError": error_message,
                "lastHttpStatus": http_status,
                "failedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            }),
        )


def log_delivery(endpoint_id, event_id, event_type, attempt, status, http_status, response_time_ms, error_message=None):
    """Log a delivery attempt to DynamoDB."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    ttl = int(time.time()) + (30 * 86400)  # 30-day TTL
    
    table.put_item(Item={
        "PK": f"WHE#{endpoint_id}",
        "SK": f"WHDEL#{now}#{attempt}",
        "endpointId": endpoint_id,
        "eventId": event_id,
        "eventType": event_type,
        "attemptNumber": attempt,
        "status": status,
        "httpStatusCode": http_status,
        "responseTimeMs": response_time_ms,
        "errorMessage": error_message,
        "attemptedAt": now,
        "ttl": ttl,
        "GSI1PK": f"EVT#{event_id}",
        "GSI1SK": f"WHE#{endpoint_id}#{attempt}",
    })


def reset_failure_count(endpoint_id):
    """Reset consecutive failure counter on successful delivery."""
    table.update_item(
        Key={"PK": f"ORG#lookup", "SK": f"WHE#{endpoint_id}"},
        UpdateExpression="SET failureCount = :zero, lastDeliveryAt = :now",
        ExpressionAttributeValues={
            ":zero": 0,
            ":now": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        },
    )


def increment_failure_count(endpoint_id):
    """Increment consecutive failure counter."""
    table.update_item(
        Key={"PK": f"ORG#lookup", "SK": f"WHE#{endpoint_id}"},
        UpdateExpression="SET failureCount = failureCount + :one, lastFailureAt = :now",
        ExpressionAttributeValues={
            ":one": 1,
            ":now": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        },
    )
```

---

## Endpoint Validation

When a customer registers a new webhook endpoint, we validate that they control the URL by sending a challenge request.

### Challenge Flow

```
Customer: POST /v1/webhook-endpoints
  { "url": "https://api.customer.com/webhooks/agentmail", "eventTypes": [...] }

AgentMail:
  1. Generate random challenge token: "ch_K7dF9mN2pQ4xR8sT1vW3y"
  2. POST to customer URL with challenge payload:
     {
       "type": "webhook.validation",
       "challenge": "ch_K7dF9mN2pQ4xR8sT1vW3y"
     }
  3. Customer endpoint must respond within 10 seconds with:
     HTTP 200
     { "challenge": "ch_K7dF9mN2pQ4xR8sT1vW3y" }
  4. If challenge echoed correctly:
     - Create endpoint with status: "active"
     - Return 201 Created with endpoint details
  5. If challenge fails:
     - Return 400 Bad Request with error:
       { "error": "webhook_validation_failed", "message": "Endpoint did not respond to challenge" }
```

### Validation Requirements

- Endpoint must be HTTPS (HTTP rejected at API level)
- Must respond within 10 seconds
- Must return HTTP 200
- Must echo the challenge token exactly in JSON response body
- No IP allowlist restrictions (customers may use any public URL)
- Validation is re-run when the URL is updated

---

## Dead Letter Handling

### DLQ Processor

Events that fail all 5 delivery attempts land in the dead letter queue (`agentmail-webhook-dlq`). A separate Lambda processes the DLQ:

```
SQS DLQ (agentmail-webhook-dlq)
    │
    ▼
Lambda: webhook-dlq-processor
    │
    ├── 1. Archive failed event to S3
    │      s3://agentmail-webhook-dlq-archive/{orgId}/{endpointId}/{date}/{eventId}.json
    │
    ├── 2. Increment 24-hour failure counter (DynamoDB atomic counter)
    │      Key: "WHFAIL#{endpointId}#2026-04-10"
    │      TTL: 48 hours
    │
    ├── 3. Check if failures exceed threshold
    │      If failures in last 24h >= 50:
    │        - Set endpoint status to "disabled"
    │        - Set disabledReason: "50 consecutive failures in 24 hours"
    │        - Fire webhook.endpoint.disabled event to Kinesis
    │        - Send notification email to org admin
    │
    └── 4. Log to CloudWatch custom metric: WebhookDLQDepth
```

### Auto-Disable Logic

```python
def check_auto_disable(endpoint_id: str, org_id: str) -> bool:
    """Check if endpoint should be auto-disabled.
    
    Criteria: 50 or more failures within a rolling 24-hour window.
    We track failures per calendar day and sum the current + previous day.
    """
    today = time.strftime("%Y-%m-%d", time.gmtime())
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Get failure counts for today and yesterday
    response = dynamodb.batch_get_item(
        RequestItems={
            "agentmail": {
                "Keys": [
                    {"PK": f"WHFAIL#{endpoint_id}#{today}", "SK": "COUNT"},
                    {"PK": f"WHFAIL#{endpoint_id}#{yesterday}", "SK": "COUNT"},
                ],
            }
        }
    )
    
    total_failures = sum(
        item.get("count", 0) 
        for item in response.get("Responses", {}).get("agentmail", [])
    )
    
    if total_failures >= 50:
        # Disable the endpoint
        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"WHE#{endpoint_id}"},
            UpdateExpression="SET #status = :disabled, disabledAt = :now, "
                           "disabledReason = :reason",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":disabled": "disabled",
                ":now": datetime.utcnow().isoformat() + "Z",
                ":reason": f"{total_failures} failures in 24 hours",
            },
        )
        return True
    
    return False
```

### S3 Archival of Failed Events

Failed events are archived to S3 for customer support investigation and potential manual replay:

```
s3://agentmail-webhook-dlq-archive/
  {orgId}/
    {endpointId}/
      2026/04/10/
        evt_01JRWX6E7MNKD3P4Q8R2S5T9V0.json
        evt_01JRWX7F8NOLD4Q5R9S3T0U1W2.json
```

Each archived file contains the full event payload, all delivery attempt metadata, and the final error:

```json
{
  "event": { "...full event payload..." },
  "endpointId": "whe_01JRWX9H0PQNF6S7T5U2V3W4X5",
  "endpointUrl": "https://api.customer.com/webhooks/agentmail",
  "totalAttempts": 5,
  "attempts": [
    { "attempt": 1, "status": 503, "responseTimeMs": 1200, "at": "..." },
    { "attempt": 2, "status": 503, "responseTimeMs": 1500, "at": "..." },
    { "attempt": 3, "status": 0, "error": "Connection timeout", "at": "..." },
    { "attempt": 4, "status": 503, "responseTimeMs": 800, "at": "..." },
    { "attempt": 5, "status": 503, "responseTimeMs": 950, "at": "..." }
  ],
  "archivedAt": "2026-04-10T14:36:41.000Z"
}
```

Retention: 90 days in S3 Standard, then deleted via lifecycle policy.

---

## Delivery Logging

Every webhook delivery attempt is logged to DynamoDB for observability and customer self-service debugging.

### What is Logged

| Field | Description |
|-------|-------------|
| `endpointId` | Which endpoint received the delivery attempt |
| `eventId` | Which event was being delivered |
| `eventType` | Event type (for filtering) |
| `attemptNumber` | 1-5 |
| `status` | `success`, `failure`, or `timeout` |
| `httpStatusCode` | Response status code (null for connection errors) |
| `responseTimeMs` | Total time from request start to response complete |
| `errorMessage` | Error details for failures (truncated to 500 chars) |
| `attemptedAt` | ISO 8601 timestamp |
| `ttl` | 30 days from creation (auto-deleted) |

### Access Patterns

| Pattern | Query |
|---------|-------|
| All deliveries for an endpoint | PK = `WHE#{endpointId}`, SK begins_with `WHDEL#` |
| Recent deliveries for an endpoint | PK = `WHE#{endpointId}`, SK begins_with `WHDEL#2026-04-10` |
| All attempts for a specific event | GSI: PK = `EVT#{eventId}` |
| Failed deliveries for an endpoint | PK = `WHE#{endpointId}`, FilterExpression: status = "failure" |

### API Exposure

Customers can query their webhook delivery logs via the API:

```
GET /v1/webhook-endpoints/{endpointId}/deliveries
GET /v1/webhook-endpoints/{endpointId}/deliveries?status=failure
GET /v1/events/{eventId}/deliveries
```

---

## Performance Budget

The end-to-end latency from an email arriving at SES to the webhook being delivered to a customer endpoint has a budget of approximately 1,200ms typical, 5,000ms maximum.

### Stage Breakdown

```
Stage                          Typical    P99      Notes
──────────────────────────────────────────────────────────────
SES → SNS notification          50ms     200ms    SES internal
SNS → SQS delivery              20ms     100ms    Regional
SQS → Lambda trigger           100ms     500ms    Includes cold start amortization
Lambda normalizer               80ms     200ms    Redis lookup + Kinesis write
Kinesis write acknowledge       30ms     100ms    PutRecords response
Kinesis → enhanced fan-out      70ms     200ms    Push delivery to consumer
Lambda dispatcher               50ms     150ms    DynamoDB query + SQS write
SQS → Lambda sender trigger    100ms     300ms    Batch window = 0
Lambda sender HTTP POST        300ms    2000ms    Depends on customer endpoint
──────────────────────────────────────────────────────────────
TOTAL                          800ms    3750ms
TARGET                        1200ms    5000ms
```

### Bottlenecks and Mitigations

| Bottleneck | Impact | Mitigation |
|-----------|--------|------------|
| Lambda cold starts | +500ms occasionally | Provisioned concurrency (10) on dispatcher and sender |
| Slow customer endpoints | +1-5s per delivery | 10s hard timeout; does not block other deliveries |
| DynamoDB hot partition (many endpoints per org) | +50ms | DAX cache for endpoint lookups |
| Kinesis throttle (WriteProvisionedThroughputExceeded) | Event loss or delay | ON_DEMAND stream mode auto-scales |

---

## Monitoring

### CloudWatch Metrics (Custom)

| Metric | Dimensions | Alarm Threshold |
|--------|-----------|-----------------|
| `WebhookDeliverySuccess` | orgId, endpointId | < 95% success rate over 5 min |
| `WebhookDeliveryLatencyP99` | orgId | > 5000ms over 5 min |
| `WebhookDeliveryAttempts` | attempt (1-5) | Attempt 5 > 1% of total |
| `WebhookDLQDepth` | - | > 100 messages |
| `WebhookEndpointsDisabled` | orgId | > 0 (alert on any disable) |
| `WebhookDispatcherErrors` | - | > 0 over 1 min |

### Dashboard Widgets

1. **Delivery Success Rate** -- Stacked area chart: success vs failure vs timeout, by hour
2. **Latency Percentiles** -- Line chart: p50, p90, p99 delivery latency
3. **Retry Distribution** -- Bar chart: count by attempt number (healthy = mostly attempt 1)
4. **DLQ Depth** -- Number widget with alarm status
5. **Top Failing Endpoints** -- Table sorted by failure count
6. **Events Per Second** -- Line chart of Kinesis IncomingRecords

### Alerting

| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| High DLQ depth | DLQ depth > 100 for 5 min | P2 | Investigate failing endpoints |
| Low delivery success rate | < 90% success over 15 min | P2 | Check customer endpoints, check Lambda errors |
| Dispatcher errors | Any errors in 5 min | P3 | Check Lambda logs, DynamoDB throttling |
| Endpoint auto-disabled | Any endpoint disabled | P4 (info) | Notify customer via email |
