# Observability

AgentMail is a multi-tenant platform where a single misconfiguration, runaway tenant, or upstream AWS service degradation can affect every customer simultaneously. The observability architecture must answer three questions at all times: Is the platform healthy? Is each tenant healthy? What changed? Every log line, metric, alarm, and trace is designed to answer one of these questions within seconds.

The stack is built entirely on AWS-native observability services -- CloudWatch Logs, CloudWatch Metrics, CloudWatch Alarms, X-Ray, and CloudWatch Dashboards -- with PagerDuty and Slack as notification channels. No third-party observability vendors are required at launch, though Datadog or Grafana Cloud can be added later by forwarding CloudWatch metrics via Kinesis Firehose.

---

## Table of Contents

- [Structured Logging](#structured-logging)
- [Metrics](#metrics)
- [Alarms](#alarms)
- [X-Ray Distributed Tracing](#x-ray-distributed-tracing)
- [Per-Tenant Dashboards](#per-tenant-dashboards)
- [Runbooks](#runbooks)

---

## Structured Logging

### Log Format

Every log line emitted by every component (Lambda, ECS, API Gateway) is a JSON object with a consistent set of fields. No unstructured log lines. No `console.log("something happened")`. Every line is machine-parseable and tenant-scoped.

```json
{
  "timestamp": "2027-03-15T14:23:45.123Z",
  "level": "INFO",
  "service": "inbound-processor",
  "function": "parse_mime",
  "request_id": "req_a1b2c3d4",
  "trace_id": "1-65f5a1b2-abc123def456789012345678",
  "org_id": "org_456",
  "inbox_id": "inb_xyz789",
  "message_id": "msg_abc123",
  "duration_ms": 45,
  "message": "MIME parsing complete",
  "details": {
    "content_type": "multipart/mixed",
    "attachments": 2,
    "body_size_bytes": 15234,
    "thread_id": "thr_def456"
  }
}
```

### Required Fields on Every Log Line

| Field | Source | Purpose |
|-------|--------|---------|
| `timestamp` | ISO 8601 with milliseconds | Ordering, correlation |
| `level` | ERROR, WARN, INFO, DEBUG | Filtering |
| `service` | Lambda function name or ECS service name | Component identification |
| `function` | Code function/method name | Pinpoint location |
| `request_id` | API Gateway request ID or Lambda invocation ID | Request tracing |
| `trace_id` | X-Ray trace ID (propagated through all services) | Distributed tracing |
| `org_id` | Extracted from API key or message metadata | Tenant scoping |
| `message` | Human-readable summary | Quick scanning |

### Optional Fields (Contextual)

| Field | When Present |
|-------|-------------|
| `inbox_id` | Any operation scoped to an inbox |
| `message_id` | Any operation on a specific message |
| `thread_id` | Threading operations |
| `webhook_id` | Webhook delivery operations |
| `domain_id` | Domain verification operations |
| `pod_id` | Pod-scoped operations |
| `ses_message_id` | SES sending/receiving operations |
| `duration_ms` | Any timed operation |
| `status_code` | HTTP responses |
| `error_code` | Error responses |
| `error_message` | Error responses |
| `details` | Structured payload with operation-specific data |

### Example Log Entries

**Inbound email received:**
```json
{
  "timestamp": "2027-03-15T14:23:44.001Z",
  "level": "INFO",
  "service": "inbound-router",
  "function": "process_ses_notification",
  "request_id": "req_f1e2d3c4",
  "trace_id": "1-65f5a1b0-111222333444555666777888",
  "org_id": "org_456",
  "inbox_id": "inb_xyz789",
  "message": "Inbound email processed",
  "duration_ms": 234,
  "details": {
    "from": "customer@example.com",
    "to": "agent-smith@agentmail.dev",
    "subject": "Re: Invoice #1234",
    "message_id": "msg_new123",
    "thread_id": "thr_existing456",
    "thread_action": "appended",
    "ses_message_id": "abc123def456@email.amazonses.com",
    "spam_verdict": "PASS",
    "virus_verdict": "PASS",
    "spf_verdict": "PASS",
    "dkim_verdict": "PASS",
    "dmarc_verdict": "PASS",
    "body_size_bytes": 8432,
    "attachment_count": 1
  }
}
```

**Outbound send failed:**
```json
{
  "timestamp": "2027-03-15T14:25:12.789Z",
  "level": "ERROR",
  "service": "send-worker",
  "function": "send_via_ses",
  "request_id": "req_b5a4c3d2",
  "trace_id": "1-65f5a200-aabbccddeeff001122334455",
  "org_id": "org_789",
  "inbox_id": "inb_abc456",
  "message_id": "msg_send789",
  "message": "SES SendRawEmail failed",
  "error_code": "MessageRejected",
  "error_message": "Email address is not verified. The following identities failed the check in region US-EAST-1: unverified@example.com",
  "details": {
    "from": "agent@org789.agentmail.dev",
    "to": ["unverified@example.com"],
    "retry_count": 0,
    "will_retry": false,
    "permanent_failure": true
  }
}
```

**Webhook delivery succeeded after retry:**
```json
{
  "timestamp": "2027-03-15T14:26:00.456Z",
  "level": "INFO",
  "service": "webhook-delivery",
  "function": "deliver_webhook",
  "request_id": "req_c6b5a4d3",
  "trace_id": "1-65f5a230-ffeeddccbbaa998877665544",
  "org_id": "org_456",
  "webhook_id": "whk_def789",
  "message": "Webhook delivered successfully",
  "duration_ms": 892,
  "details": {
    "event_type": "message.received",
    "endpoint": "https://hooks.customer.com/agentmail",
    "status_code": 200,
    "attempt": 3,
    "total_retry_duration_ms": 45230,
    "hmac_signed": true
  }
}
```

**API key authentication failed:**
```json
{
  "timestamp": "2027-03-15T14:27:15.123Z",
  "level": "WARN",
  "service": "authorizer",
  "function": "validate_api_key",
  "request_id": "req_d7c6b5a4",
  "trace_id": "1-65f5a260-112233445566778899aabbcc",
  "message": "API key authentication failed",
  "details": {
    "key_prefix": "ak_prod_a1b2",
    "reason": "key_revoked",
    "source_ip": "203.0.113.42",
    "endpoint": "POST /v1/inboxes",
    "user_agent": "agentmail-python/1.2.0"
  }
}
```

**Marketplace metering submission:**
```json
{
  "timestamp": "2027-03-15T15:00:05.789Z",
  "level": "INFO",
  "service": "metering-submitter",
  "function": "submit_batch_meter_usage",
  "request_id": "req_e8d7c6b5",
  "trace_id": "1-65f5a300-ddeeff001122334455667788",
  "message": "Marketplace metering batch submitted",
  "duration_ms": 342,
  "details": {
    "hour": "2027-03-15T14:00:00Z",
    "records_submitted": 47,
    "dimensions": {
      "messages_sent": 12450,
      "messages_received": 8320,
      "ai_categorizations": 3100,
      "ai_extractions": 890,
      "semantic_searches": 1240
    },
    "orgs_metered": 47,
    "failures": 0
  }
}
```

### CloudWatch Logs Configuration

```yaml
# Log groups (one per service/function)
Log Groups:
  /agentmail/api/authorizer:
    retention: 30 days
  /agentmail/api/handlers:
    retention: 30 days
  /agentmail/inbound/router:
    retention: 30 days
  /agentmail/inbound/processor:
    retention: 30 days
  /agentmail/outbound/send-worker:
    retention: 30 days
  /agentmail/webhooks/delivery:
    retention: 30 days
  /agentmail/events/ws-fanout:
    retention: 30 days
  /agentmail/ai/categorizer:
    retention: 30 days
  /agentmail/ai/extractor:
    retention: 30 days
  /agentmail/ai/embeddings:
    retention: 30 days
  /agentmail/marketplace/metering:
    retention: 90 days   # longer retention for billing audit
  /agentmail/marketplace/lifecycle:
    retention: 90 days
  /agentmail/ecs/imap-server:
    retention: 30 days
  /agentmail/ecs/smtp-relay:
    retention: 30 days
```

### Log Retention Strategy

| Tier | Retention | Storage | Purpose |
|------|-----------|---------|---------|
| **Hot** | 30 days | CloudWatch Logs | Active debugging, CloudWatch Insights queries |
| **Warm** | 90 days | S3 (exported via CloudWatch Logs subscription + Firehose) | Compliance, audit trail, deeper investigations |
| **Cold** | 1 year | S3 Glacier Instant Retrieval | Regulatory compliance (if required by customer contracts) |
| **Archive** | 7 years | S3 Glacier Deep Archive | SOC 2 / legal hold (only billing-related logs) |

**Export pipeline:**
```
CloudWatch Logs → Subscription Filter → Kinesis Firehose → S3 (partitioned by date/service)
                                                            |
                                                            → S3 Lifecycle Policy
                                                                90 days → Glacier IR
                                                                365 days → Glacier DA
```

### CloudWatch Logs Insights Queries

Pre-built queries saved in CloudWatch for common investigations:

**All errors for a specific organization in the last hour:**
```
fields @timestamp, service, function, message, error_code, error_message
| filter org_id = "org_456" and level = "ERROR"
| sort @timestamp desc
| limit 100
```

**Trace a specific request across all services:**
```
fields @timestamp, service, function, message, duration_ms
| filter request_id = "req_a1b2c3d4" or trace_id = "1-65f5a1b2-abc123def456789012345678"
| sort @timestamp asc
```

**Top 10 slowest API requests in the last 24 hours:**
```
fields @timestamp, org_id, request_id, duration_ms, details.endpoint
| filter service = "api-handler" and duration_ms > 0
| sort duration_ms desc
| limit 10
```

**Webhook failure rate by organization:**
```
fields org_id, webhook_id
| filter service = "webhook-delivery"
| stats count(*) as total, sum(level = "ERROR") as failures by org_id
| display org_id, total, failures, (failures / total * 100) as failure_pct
| sort failure_pct desc
```

**Inbound email volume by inbox (last 24 hours):**
```
fields inbox_id, org_id
| filter service = "inbound-router" and level = "INFO" and message = "Inbound email processed"
| stats count(*) as emails_received by inbox_id, org_id
| sort emails_received desc
| limit 50
```

---

## Metrics

All metrics are published to CloudWatch as custom metrics under the `AgentMail` namespace. Every metric includes dimensions that enable per-tenant, per-service, and per-endpoint slicing.

### API Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `api.requests` | Count | `org_id`, `endpoint`, `method`, `status_code` | Total API requests |
| `api.latency` | Milliseconds | `org_id`, `endpoint`, `method` | End-to-end API response time |
| `api.errors.4xx` | Count | `org_id`, `endpoint`, `error_code` | Client errors (400, 401, 403, 404, 422, 429) |
| `api.errors.5xx` | Count | `org_id`, `endpoint`, `error_code` | Server errors (500, 502, 503) |
| `api.throttled` | Count | `org_id`, `endpoint` | Requests rejected by rate limiter (429) |
| `api.payload_size` | Bytes | `org_id`, `endpoint`, `direction` (request/response) | Request and response body sizes |
| `api.auth.success` | Count | `org_id`, `key_prefix` | Successful API key authentications |
| `api.auth.failure` | Count | `source_ip`, `key_prefix`, `reason` | Failed authentication attempts |

### Email Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `email.sent` | Count | `org_id`, `inbox_id`, `source` (api/smtp) | Messages sent |
| `email.received` | Count | `org_id`, `inbox_id` | Messages received (inbound) |
| `email.bounced` | Count | `org_id`, `inbox_id`, `bounce_type` (hard/soft) | Bounced messages |
| `email.complained` | Count | `org_id`, `inbox_id` | Spam complaints received |
| `email.delivered` | Count | `org_id`, `inbox_id` | Confirmed deliveries (SES delivery event) |
| `email.rejected` | Count | `org_id`, `inbox_id`, `reason` | Messages rejected before send (quota, blocklist, etc.) |
| `email.send_latency` | Milliseconds | `org_id` | Time from API call to SES acceptance |
| `email.inbound_processing_latency` | Milliseconds | `org_id` | Time from SES receipt to DynamoDB write |
| `email.thread_created` | Count | `org_id`, `inbox_id` | New threads created |
| `email.thread_appended` | Count | `org_id`, `inbox_id` | Messages added to existing threads |
| `email.attachment_uploaded` | Count | `org_id`, `inbox_id` | Attachments uploaded |
| `email.attachment_size` | Bytes | `org_id`, `inbox_id` | Attachment sizes |

### Webhook Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `webhook.delivered` | Count | `org_id`, `webhook_id`, `event_type` | Successful webhook deliveries |
| `webhook.failed` | Count | `org_id`, `webhook_id`, `event_type`, `status_code` | Failed webhook deliveries (after all retries) |
| `webhook.latency` | Milliseconds | `org_id`, `webhook_id` | Time from event to successful delivery |
| `webhook.retry_count` | Count | `org_id`, `webhook_id` | Number of retries before success or failure |
| `webhook.endpoint_health` | Percent | `org_id`, `webhook_id` | Success rate over last 100 deliveries |
| `webhook.queue_depth` | Count | `org_id` | Pending webhook deliveries in SQS |

### WebSocket Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `websocket.connections` | Count | `org_id` | Active WebSocket connections (gauge) |
| `websocket.messages_sent` | Count | `org_id`, `event_type` | Messages pushed to WebSocket clients |
| `websocket.connect` | Count | `org_id` | New WebSocket connections established |
| `websocket.disconnect` | Count | `org_id`, `reason` | WebSocket disconnections |
| `websocket.errors` | Count | `org_id`, `error_type` | WebSocket delivery errors (stale connection, etc.) |

### SES Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `ses.bounce_rate` | Percent | `configuration_set`, `org_id` | Bounce rate (SES threshold: 5%) |
| `ses.complaint_rate` | Percent | `configuration_set`, `org_id` | Complaint rate (SES threshold: 0.1%) |
| `ses.send_quota_used` | Percent | `region` | Percentage of SES daily sending quota consumed |
| `ses.send_rate` | Count/Second | `region` | Current sending rate vs. maximum |
| `ses.reputation_score` | None | `configuration_set` | SES VDM reputation score (0-100) |

### DynamoDB Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `dynamodb.consumed_read_capacity` | Count | `table`, `gsi_name` | Consumed RCUs (per table and per GSI) |
| `dynamodb.consumed_write_capacity` | Count | `table`, `gsi_name` | Consumed WCUs (per table and per GSI) |
| `dynamodb.throttled_requests` | Count | `table`, `gsi_name`, `operation` | Throttled read/write requests |
| `dynamodb.system_errors` | Count | `table` | DynamoDB internal errors |
| `dynamodb.successful_request_latency` | Milliseconds | `table`, `operation` | DynamoDB operation latency |
| `dynamodb.item_count` | Count | `table` | Total items in table (from describe) |
| `dynamodb.table_size` | Bytes | `table` | Total table size |

### Lambda Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `lambda.invocations` | Count | `function_name` | Total invocations |
| `lambda.errors` | Count | `function_name`, `error_type` | Failed invocations |
| `lambda.duration` | Milliseconds | `function_name` | Execution duration |
| `lambda.throttles` | Count | `function_name` | Throttled invocations (concurrency limit) |
| `lambda.concurrent_executions` | Count | `function_name` | Current concurrent executions (gauge) |
| `lambda.cold_starts` | Count | `function_name` | Cold start invocations (custom metric) |
| `lambda.cold_start_duration` | Milliseconds | `function_name` | Init duration for cold starts |
| `lambda.memory_used` | Megabytes | `function_name` | Max memory used per invocation |

### Kinesis Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `kinesis.iterator_age` | Milliseconds | `stream_name`, `shard_id` | Age of oldest unprocessed record |
| `kinesis.put_records_success` | Count | `stream_name` | Successful PutRecords calls |
| `kinesis.put_records_failed` | Count | `stream_name` | Failed PutRecords calls |
| `kinesis.read_throughput_exceeded` | Count | `stream_name`, `shard_id` | Read throttles |
| `kinesis.write_throughput_exceeded` | Count | `stream_name`, `shard_id` | Write throttles |
| `kinesis.records_per_shard` | Count/Second | `stream_name`, `shard_id` | Record ingestion rate |

### AI Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `ai.embeddings_generated` | Count | `org_id`, `model` | Embedding vectors generated |
| `ai.embeddings_latency` | Milliseconds | `org_id`, `model` | Embedding generation time |
| `ai.categorizations` | Count | `org_id`, `model`, `category` | Email categorizations performed |
| `ai.categorization_latency` | Milliseconds | `org_id`, `model` | Categorization time |
| `ai.extractions` | Count | `org_id`, `model` | Data extractions performed |
| `ai.extraction_latency` | Milliseconds | `org_id`, `model` | Extraction time |
| `ai.search_queries` | Count | `org_id` | Semantic search queries |
| `ai.search_latency` | Milliseconds | `org_id` | Semantic search response time |
| `ai.search_results` | Count | `org_id` | Search results returned per query (average) |
| `ai.bedrock_tokens_input` | Count | `org_id`, `model` | Bedrock input tokens consumed |
| `ai.bedrock_tokens_output` | Count | `org_id`, `model` | Bedrock output tokens consumed |
| `ai.bedrock_errors` | Count | `org_id`, `model`, `error_type` | Bedrock API errors |

### Marketplace Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `marketplace.metering_submissions` | Count | - | Successful BatchMeterUsage calls |
| `marketplace.metering_failures` | Count | `error_type` | Failed BatchMeterUsage calls |
| `marketplace.metering_records` | Count | - | Total usage records submitted per hour |
| `marketplace.metering_latency` | Milliseconds | - | Time to submit metering batch |
| `marketplace.dlq_depth` | Count | - | Messages in metering dead-letter queue |
| `marketplace.dlq_age` | Seconds | - | Age of oldest message in DLQ |
| `marketplace.customer_registrations` | Count | - | New customer registrations (ResolveCustomer) |
| `marketplace.customer_churn` | Count | - | Unsubscribe events |
| `marketplace.entitlement_checks` | Count | `result` (valid/expired/missing) | Entitlement validation results |

### Quota Metrics

| Metric Name | Unit | Dimensions | Description |
|------------|------|-----------|-------------|
| `quota.usage_percentage` | Percent | `org_id`, `quota_type` | Current usage as percentage of quota |
| `quota.inboxes_used` | Count | `org_id` | Current inbox count |
| `quota.inboxes_limit` | Count | `org_id` | Inbox quota limit |
| `quota.messages_sent_today` | Count | `org_id` | Messages sent in current day |
| `quota.messages_limit_daily` | Count | `org_id` | Daily message sending limit |
| `quota.storage_used` | Bytes | `org_id` | Current storage consumption |
| `quota.storage_limit` | Bytes | `org_id` | Storage quota limit |
| `quota.api_calls_minute` | Count | `org_id` | API calls in current minute |
| `quota.api_rate_limit` | Count | `org_id` | API rate limit per minute |

### Metric Publishing

Metrics are published via two mechanisms:

1. **Embedded Metric Format (EMF)**: Lambda functions and ECS containers emit metrics as structured JSON log lines using CloudWatch EMF. CloudWatch automatically extracts metrics from these log lines with zero API calls. This is the primary mechanism for custom metrics.

```json
{
  "_aws": {
    "Timestamp": 1679918625123,
    "CloudWatchMetrics": [
      {
        "Namespace": "AgentMail",
        "Dimensions": [["org_id", "endpoint"], ["org_id"]],
        "Metrics": [
          { "Name": "api.latency", "Unit": "Milliseconds" },
          { "Name": "api.requests", "Unit": "Count" }
        ]
      }
    ]
  },
  "org_id": "org_456",
  "endpoint": "POST /v1/inboxes/{id}/messages",
  "api.latency": 145,
  "api.requests": 1
}
```

2. **CloudWatch PutMetricData**: Used sparingly for aggregate metrics computed by scheduled Lambda functions (e.g., per-org quota percentages, SES reputation scores). These run every 5 minutes and publish batch metrics.

---

## Alarms

Alarms are organized by severity. Each alarm has a defined threshold, evaluation period, and notification channel.

### P0 -- Critical (PagerDuty, Immediate Response Required)

These alarms indicate the platform is broken or at imminent risk of breaking. On-call engineer is paged immediately.

| Alarm Name | Metric | Threshold | Evaluation | Notification |
|-----------|--------|-----------|-----------|--------------|
| `p0-api-error-rate` | `api.errors.5xx / api.requests` | > 5% over 5 minutes | 3 of 5 datapoints | PagerDuty + Slack #incidents |
| `p0-ses-bounce-rate` | `ses.bounce_rate` | > 5% over 15 minutes | 3 of 3 datapoints | PagerDuty + Slack #incidents |
| `p0-ses-complaint-rate` | `ses.complaint_rate` | > 0.08% over 15 minutes | 3 of 3 datapoints | PagerDuty + Slack #incidents |
| `p0-lambda-concurrency` | `lambda.concurrent_executions` | > 80% of reserved concurrency | 3 of 5 datapoints (1 min) | PagerDuty + Slack #incidents |
| `p0-metering-dlq-age` | `marketplace.dlq_age` | > 4 hours (14400 seconds) | 1 of 1 datapoint | PagerDuty + Slack #incidents |
| `p0-dynamodb-system-errors` | `dynamodb.system_errors` | > 10 in 5 minutes | 2 of 3 datapoints | PagerDuty + Slack #incidents |
| `p0-api-gateway-5xx` | AWS/ApiGateway `5XXError` | > 50 in 5 minutes | 2 of 3 datapoints | PagerDuty + Slack #incidents |
| `p0-ses-send-quota-critical` | `ses.send_quota_used` | > 90% | 1 of 1 datapoint (5 min) | PagerDuty + Slack #incidents |

### P1 -- Warning (Slack, Response Within 1 Hour)

These alarms indicate degraded performance or a trend toward failure. Engineering team is notified via Slack.

| Alarm Name | Metric | Threshold | Evaluation | Notification |
|-----------|--------|-----------|-----------|--------------|
| `p1-api-latency-p99` | `api.latency` P99 | > 2000 ms over 10 minutes | 3 of 5 datapoints | Slack #alerts |
| `p1-api-latency-p95` | `api.latency` P95 | > 1000 ms over 10 minutes | 3 of 5 datapoints | Slack #alerts |
| `p1-sqs-depth` | SQS `ApproximateNumberOfMessagesVisible` | > 10,000 for any queue | 3 of 5 datapoints (1 min) | Slack #alerts |
| `p1-webhook-failure-rate` | `webhook.failed / (webhook.delivered + webhook.failed)` | > 20% over 15 minutes | 3 of 3 datapoints | Slack #alerts |
| `p1-kinesis-iterator-age` | `kinesis.iterator_age` | > 30,000 ms (30 seconds) | 3 of 5 datapoints (1 min) | Slack #alerts |
| `p1-lambda-errors` | `lambda.errors` | > 5% of invocations for any function | 3 of 5 datapoints (1 min) | Slack #alerts |
| `p1-lambda-throttles` | `lambda.throttles` | > 0 for 5 minutes | 5 of 5 datapoints (1 min) | Slack #alerts |
| `p1-ses-bounce-rate-warning` | `ses.bounce_rate` | > 2% over 15 minutes | 3 of 3 datapoints | Slack #alerts |
| `p1-ses-send-quota-warning` | `ses.send_quota_used` | > 70% | 1 of 1 datapoint (5 min) | Slack #alerts |
| `p1-redis-cpu` | ElastiCache `EngineCPUUtilization` | > 70% over 10 minutes | 3 of 5 datapoints | Slack #alerts |
| `p1-redis-memory` | ElastiCache `DatabaseMemoryUsagePercentage` | > 80% | 3 of 5 datapoints (5 min) | Slack #alerts |
| `p1-opensearch-status` | OpenSearch `ClusterStatus.red` | > 0 for 5 minutes | 1 of 1 datapoint | Slack #alerts |
| `p1-metering-dlq-depth` | `marketplace.dlq_depth` | > 0 | 1 of 1 datapoint (5 min) | Slack #alerts |
| `p1-inbound-processing-latency` | `email.inbound_processing_latency` P99 | > 5000 ms | 3 of 5 datapoints (1 min) | Slack #alerts |
| `p1-ecs-cpu` | ECS `CPUUtilization` | > 80% for IMAP or SMTP service | 3 of 5 datapoints (1 min) | Slack #alerts |

### P2 -- Informational (Dashboard Only, Review in Next Business Day)

These alarms track trends and potential issues that do not require immediate action.

| Alarm Name | Metric | Threshold | Evaluation | Notification |
|-----------|--------|-----------|-----------|--------------|
| `p2-org-quota-warning` | `quota.usage_percentage` | > 80% for any org + quota type | 1 of 1 datapoint (5 min) | Dashboard + Slack #metrics (daily digest) |
| `p2-dynamodb-throttles` | `dynamodb.throttled_requests` | > 0 for any table/GSI | 1 of 1 datapoint (1 min) | Dashboard |
| `p2-cold-start-rate` | `lambda.cold_starts / lambda.invocations` | > 10% for any function | 3 of 5 datapoints (5 min) | Dashboard |
| `p2-auth-failure-spike` | `api.auth.failure` | > 100 in 5 minutes from single IP | 1 of 1 datapoint | Dashboard + Slack #security |
| `p2-s3-storage-growth` | S3 bucket size | > 1 TB for any bucket | Daily metric | Dashboard |
| `p2-opensearch-storage` | OpenSearch `StorageUsed` | > 80% of configured capacity | Daily metric | Dashboard |
| `p2-api-deprecation` | Custom: requests to deprecated endpoints | > 0 | Daily count | Dashboard |
| `p2-ses-reputation-drop` | `ses.reputation_score` | < 80 | 1 of 1 datapoint (hourly) | Dashboard + Slack #alerts |

### Alarm Infrastructure (CDK)

```typescript
// Simplified CDK example for P0 alarms
const apiErrorRateAlarm = new cloudwatch.Alarm(this, 'P0ApiErrorRate', {
  alarmName: 'p0-api-error-rate',
  metric: new cloudwatch.MathExpression({
    expression: '(errors / requests) * 100',
    usingMetrics: {
      errors: apiErrorMetric,
      requests: apiRequestMetric,
    },
    period: Duration.minutes(1),
  }),
  threshold: 5,
  evaluationPeriods: 5,
  datapointsToAlarm: 3,
  comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
  treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
  actionsEnabled: true,
});

apiErrorRateAlarm.addAlarmAction(new cw_actions.SnsAction(pagerDutyTopic));
apiErrorRateAlarm.addAlarmAction(new cw_actions.SnsAction(slackIncidentsTopic));
apiErrorRateAlarm.addOkAction(new cw_actions.SnsAction(slackIncidentsTopic));
```

### Notification Routing

```
P0 Alarms → SNS Topic (p0-critical)
               ├── PagerDuty integration (HTTPS endpoint)
               └── Slack #incidents (Lambda → Slack webhook)

P1 Alarms → SNS Topic (p1-warning)
               └── Slack #alerts (Lambda → Slack webhook)

P2 Alarms → SNS Topic (p2-info)
               └── CloudWatch Dashboard (no active notification)
               └── Slack #metrics (daily digest Lambda, runs at 09:00 UTC)
```

---

## X-Ray Distributed Tracing

### Configuration

X-Ray is enabled on all services to provide end-to-end request tracing across API Gateway, Lambda, DynamoDB, S3, SES, SQS, and Kinesis.

```yaml
# X-Ray configuration per service

API Gateway:
  TracingEnabled: true
  # All requests get a trace ID; sampling determines if recorded

Lambda Functions:
  Tracing: Active
  # Lambda automatically sends trace data to X-Ray
  # Environment: AWS_XRAY_SDK_ENABLED=true

ECS Fargate (IMAP/SMTP):
  # X-Ray daemon sidecar container
  x-ray-daemon:
    image: amazon/aws-xray-daemon:3.x
    port: 2000/udp
    cpu: 32
    memory: 64

DynamoDB:
  # Automatically traced when X-Ray SDK instruments AWS SDK calls
  # No additional configuration needed

S3:
  # Automatically traced when X-Ray SDK instruments AWS SDK calls

SES:
  # Automatically traced when X-Ray SDK instruments AWS SDK calls
```

### Sampling Rules

Full tracing of every request is prohibitively expensive at scale. Sampling rules balance visibility with cost:

| Rule Name | Service | Rate | Fixed Rate | Reservoir | Rationale |
|-----------|---------|------|-----------|-----------|-----------|
| Default | All | 5% | 0.05 | 1/second | Baseline sampling for all traffic |
| Errors | All (status >= 500) | 100% | 1.0 | 10/second | Always trace errors |
| Slow requests | All (duration > 2s) | 100% | 1.0 | 5/second | Always trace slow requests |
| Inbound email | inbound-router | 10% | 0.10 | 2/second | Higher sampling for email pipeline |
| AI operations | ai-* | 20% | 0.20 | 2/second | Higher sampling for expensive operations |
| Marketplace metering | metering-* | 100% | 1.0 | 10/second | Always trace billing operations |
| Health checks | */health | 0% | 0.0 | 0 | Never trace health check endpoints |

### Trace Segments

A typical inbound email trace includes these segments:

```
Trace: 1-65f5a1b0-111222333444555666777888
├── SES Inbound Receipt (origin)
├── S3 PutObject (raw MIME storage)           [23ms]
├── Lambda: inbound-router                    [234ms]
│   ├── DynamoDB GetItem (inbox lookup)       [3ms]
│   ├── MIME parsing (subsegment)             [45ms]
│   ├── DynamoDB PutItem (message metadata)   [8ms]
│   ├── S3 PutObject (parsed body)            [12ms]
│   ├── DynamoDB UpdateItem (thread append)   [5ms]
│   └── Kinesis PutRecord (event)             [15ms]
├── Lambda: webhook-delivery                  [892ms]
│   ├── HTTP POST to customer endpoint        [850ms]
│   └── DynamoDB PutItem (delivery log)       [6ms]
├── Lambda: ai-categorizer                    [1250ms]
│   ├── Bedrock InvokeModel (Haiku)           [1180ms]
│   └── DynamoDB UpdateItem (category)        [8ms]
└── Lambda: embedding-generator               [340ms]
    ├── Bedrock InvokeModel (Titan Embed)     [290ms]
    └── OpenSearch index (vector)             [35ms]
```

### X-Ray Groups

Groups organize traces for focused analysis:

| Group Name | Filter Expression | Purpose |
|------------|------------------|---------|
| `errors` | `service("agentmail") { error = true }` | All error traces |
| `slow-api` | `responsetime > 2` | Slow API responses |
| `inbound-email` | `service("inbound-router")` | Email processing pipeline |
| `outbound-email` | `service("send-worker")` | Email sending pipeline |
| `ai-operations` | `service("ai-categorizer") OR service("ai-extractor") OR service("embedding-generator")` | AI feature traces |
| `marketplace` | `service("metering-submitter") OR service("lifecycle-handler")` | Billing operations |
| `org-specific` | `annotation.org_id = "org_456"` | Per-tenant traces (parameterized) |

### X-Ray Cost Estimate

| Scale | Traces Sampled/Month | Cost |
|-------|---------------------|------|
| Startup (100K msgs/day) | ~300K traces | ~$1.50 |
| Growth (1M msgs/day) | ~3M traces | ~$15 |
| Full (10M msgs/day) | ~30M traces | ~$150 |

At 5% default sampling + 100% error sampling, X-Ray costs are negligible relative to compute and storage.

---

## Per-Tenant Dashboards

### Internal Operations Dashboard

A single CloudWatch dashboard parameterized by `org_id` that the operations team uses to investigate tenant-specific issues:

**Dashboard: AgentMail-Tenant-{org_id}**

```
Row 1: Health Summary
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ API Requests  │ │ Error Rate   │ │ P99 Latency  │ │ Active       │
  │ (24h count)   │ │ (5xx %)      │ │ (ms)         │ │ Inboxes      │
  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘

Row 2: Email Volume
  ┌─────────────────────────────────┐ ┌─────────────────────────────────┐
  │ Messages Sent / Received (24h)  │ │ Bounce Rate + Complaint Rate    │
  │ [time series, 5-min granularity]│ │ [time series, 15-min]           │
  └─────────────────────────────────┘ └─────────────────────────────────┘

Row 3: Webhook Health
  ┌─────────────────────────────────┐ ┌─────────────────────────────────┐
  │ Webhook Delivery Success Rate   │ │ Webhook Latency (P50, P95, P99) │
  │ [time series, 5-min]            │ │ [time series, 5-min]            │
  └─────────────────────────────────┘ └─────────────────────────────────┘

Row 4: AI Feature Usage
  ┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐
  │ Categorizations    │ │ Extractions        │ │ Semantic Searches  │
  │ (24h, by category) │ │ (24h count)        │ │ (24h, avg latency) │
  └────────────────────┘ └────────────────────┘ └────────────────────┘

Row 5: Quota Usage
  ┌─────────────────────────────────┐ ┌─────────────────────────────────┐
  │ Inbox Quota (used / limit)      │ │ Message Quota (used / limit)    │
  │ [gauge]                         │ │ [gauge]                         │
  └─────────────────────────────────┘ └─────────────────────────────────┘

Row 6: Billing
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Metered Usage by Dimension (current billing period)                │
  │ [stacked bar: messages_sent, messages_received, categorizations,   │
  │  extractions, searches, storage]                                   │
  └─────────────────────────────────────────────────────────────────────┘
```

### CloudWatch Dashboard Template (CDK)

```typescript
function createTenantDashboard(scope: Construct, orgId: string): cloudwatch.Dashboard {
  const dashboard = new cloudwatch.Dashboard(scope, `TenantDash-${orgId}`, {
    dashboardName: `AgentMail-Tenant-${orgId}`,
    periodOverride: cloudwatch.PeriodOverride.AUTO,
  });

  // Row 1: Health Summary
  dashboard.addWidgets(
    new cloudwatch.SingleValueWidget({
      title: 'API Requests (24h)',
      metrics: [new cloudwatch.Metric({
        namespace: 'AgentMail',
        metricName: 'api.requests',
        dimensionsMap: { org_id: orgId },
        statistic: 'Sum',
        period: Duration.hours(24),
      })],
      width: 6,
    }),
    new cloudwatch.SingleValueWidget({
      title: 'Error Rate (5xx)',
      metrics: [new cloudwatch.MathExpression({
        expression: '(errors / requests) * 100',
        usingMetrics: {
          errors: new cloudwatch.Metric({
            namespace: 'AgentMail', metricName: 'api.errors.5xx',
            dimensionsMap: { org_id: orgId }, statistic: 'Sum', period: Duration.hours(1),
          }),
          requests: new cloudwatch.Metric({
            namespace: 'AgentMail', metricName: 'api.requests',
            dimensionsMap: { org_id: orgId }, statistic: 'Sum', period: Duration.hours(1),
          }),
        },
      })],
      width: 6,
    }),
    // ... additional widgets
  );

  return dashboard;
}
```

### Customer-Facing Metrics (via API)

Customers access a subset of their own metrics through the REST API. This does **not** expose CloudWatch directly -- a Lambda function queries CloudWatch Metrics on behalf of the customer and returns formatted JSON:

```
GET /v1/metrics?period=24h&granularity=1h

Response:
{
  "org_id": "org_456",
  "period": { "start": "2027-03-14T14:00:00Z", "end": "2027-03-15T14:00:00Z" },
  "granularity": "1h",
  "metrics": {
    "messages_sent": { "total": 12450, "timeseries": [510, 480, ...] },
    "messages_received": { "total": 8320, "timeseries": [340, 355, ...] },
    "bounces": { "total": 12, "rate": 0.096 },
    "complaints": { "total": 0, "rate": 0.0 },
    "api_calls": { "total": 45230 },
    "webhook_deliveries": { "total": 8310, "success_rate": 99.2 },
    "ai_categorizations": { "total": 3100 },
    "ai_extractions": { "total": 890 },
    "semantic_searches": { "total": 1240 },
    "storage_used_bytes": 2147483648,
    "active_inboxes": 4523
  }
}
```

---

## Runbooks

### P0: API Error Rate > 5% (`p0-api-error-rate`)

**Impact**: Customers are experiencing failed API calls. AI agents are unable to send/receive email.

**Diagnosis steps:**
1. Open CloudWatch Logs Insights. Run: `fields @timestamp, service, function, error_code, error_message | filter level = "ERROR" | sort @timestamp desc | limit 50`
2. Check if errors are concentrated on a single endpoint (e.g., `POST /inboxes/{id}/messages`) or spread across all endpoints.
3. Check if errors are concentrated on a single org_id (tenant-specific issue) or all tenants (platform issue).
4. Check downstream service health:
   - DynamoDB: Are there throttles? (`p2-dynamodb-throttles` alarm state)
   - SES: Is SES returning errors? Check SES console dashboard.
   - Lambda: Are functions hitting concurrency limits? (`p0-lambda-concurrency`)
   - Redis: Is Redis reachable? Check ElastiCache metrics.
5. Check recent deployments: `git log --oneline -10` on the deploy branch. If a deployment happened in the last 30 minutes, consider rollback.

**Mitigation:**
- If single-tenant: Throttle the tenant's API keys (update Redis rate limit).
- If DynamoDB throttles: Switch to provisioned capacity with higher limits, or enable auto-scaling burst.
- If Lambda concurrency: Increase reserved concurrency for affected functions.
- If recent deployment: Initiate rollback via CodeDeploy.
- If SES outage: Check AWS Health Dashboard. If regional, fail over to backup region.

---

### P0: SES Bounce Rate > 5% (`p0-ses-bounce-rate`)

**Impact**: SES will suspend sending for the entire account if bounce rate exceeds 10%. At 5% we are halfway to account suspension.

**Diagnosis steps:**
1. Identify which configuration set (org) has the highest bounce rate: `SES Console → Configuration Sets → sort by bounce rate`.
2. Check bounce types. Hard bounces (invalid addresses) vs. soft bounces (mailbox full, temporary).
3. If a single org is responsible: Check their recent sending patterns. Are they sending to a purchased/invalid list?
4. Check suppression list management: Are we correctly suppressing addresses that previously hard-bounced?

**Mitigation:**
- If single-tenant: Immediately pause sending for that org (set `sending_suspended = true` in DynamoDB, clear Redis cache).
- Contact the customer to clean their recipient list.
- Check that SES account-level suppression list is enabled and functioning.
- If platform-wide: Check if a shared IP got blocklisted. Run `mxtoolbox.com` blacklist check on sending IPs.
- File AWS support ticket if bounce rate does not decrease after mitigation (SES may need to clear their internal metrics).

---

### P0: SES Complaint Rate > 0.08% (`p0-ses-complaint-rate`)

**Impact**: SES will suspend sending at 0.1%. At 0.08% we have almost no margin.

**Diagnosis steps:**
1. Check which org has the highest complaint rate via CloudWatch metric `ses.complaint_rate` by `org_id` dimension.
2. Review the actual complaint feedback loop reports: SNS complaints topic → check complaint records.
3. Determine if complaints are from a specific sending pattern (bulk campaigns, marketing emails).

**Mitigation:**
- Immediately pause sending for the offending org.
- Review their email content and sending patterns.
- Ensure unsubscribe headers are present (RFC 8058 List-Unsubscribe).
- Consider moving the org to a dedicated IP pool to isolate their reputation.
- File SES support case if needed.

---

### P0: Lambda Concurrency > 80% (`p0-lambda-concurrency`)

**Impact**: Lambda functions are approaching concurrency limits. Additional invocations will be throttled, causing API errors and delayed email processing.

**Diagnosis steps:**
1. Identify which function(s) are consuming the most concurrency: CloudWatch → Lambda → Concurrent Executions by function.
2. Check if a traffic spike is happening (legitimate) or if a function has a bug causing slow execution (higher concurrency due to longer duration).
3. Check for downstream bottlenecks: If DynamoDB or SES is slow, Lambda functions hold connections longer, consuming more concurrency.

**Mitigation:**
- Increase reserved concurrency for critical functions (authorizer, api-handlers, inbound-router).
- If a single tenant is causing a traffic spike: Apply per-tenant rate limiting at the API Gateway level.
- If functions are slow due to downstream issues: Fix the downstream issue first.
- Request account-level concurrency increase via AWS Support (default 1000, can be raised to 10,000+).

---

### P0: Metering DLQ Age > 4 Hours (`p0-metering-dlq-age`)

**Impact**: Marketplace usage metering is failing. Customers may be using the platform without being billed. AWS Marketplace requires metering within 6 hours of usage or the records are lost permanently.

**Diagnosis steps:**
1. Check the DLQ messages: `aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 10 --attribute-names All`
2. Examine the message bodies for error details.
3. Check the metering Lambda function logs for errors.
4. Verify AWS Marketplace Metering API is healthy (check AWS Health Dashboard).
5. Check if the product code in metering calls matches the registered product.

**Mitigation:**
- If API errors: Check if AWS Marketplace Metering API is experiencing an outage. If so, wait and retry.
- If product code mismatch: Fix the configuration and reprocess DLQ messages.
- If customer registration issue: Check if ResolveCustomer was called for the affected customer IDs.
- Reprocess DLQ: Run the DLQ reprocessor Lambda manually to resubmit failed records.
- **CRITICAL**: Records must be submitted within 6 hours. If the DLQ age approaches 5 hours, escalate to engineering leadership. Lost metering records mean lost revenue.

---

### P0: DynamoDB System Errors > 10 (`p0-dynamodb-system-errors`)

**Impact**: DynamoDB is returning internal server errors. This affects all API operations, email processing, and webhook delivery.

**Diagnosis steps:**
1. Check AWS Health Dashboard for DynamoDB service events in us-east-1.
2. Check if errors are on the main table or a specific GSI.
3. Check if errors correlate with a specific operation type (PutItem, Query, etc.).
4. Review DynamoDB console for any ongoing table operations (GSI creation, backup, etc.).

**Mitigation:**
- DynamoDB system errors are AWS-side. There is no customer-side fix other than retry.
- Ensure all DynamoDB operations have exponential backoff retry (AWS SDK default).
- If errors persist > 15 minutes: File AWS support case at Urgent severity.
- If regional outage: Initiate failover to backup region (if multi-region is deployed).

---

### P0: API Gateway 5XX > 50 (`p0-api-gateway-5xx`)

**Impact**: API Gateway itself is returning 5XX errors, indicating either integration failures (Lambda not responding) or API Gateway service issues.

**Diagnosis steps:**
1. Check API Gateway execution logs (if enabled) for integration error details.
2. Check Lambda function health for all API handler functions.
3. Check if the authorizer Lambda is failing (would cause 500 on all endpoints).
4. Check API Gateway throttling: `429` vs `503` responses.

**Mitigation:**
- If authorizer failure: Check Redis connectivity (authorizer caches keys in Redis). If Redis is down, authorizer falls back to DynamoDB but may be slow.
- If Lambda integration timeout: Increase Lambda timeout or address the root cause of slow execution.
- If API Gateway throttling: Increase API Gateway account-level throttle limits via AWS Support.
- If API Gateway service issue: Check AWS Health Dashboard. Enable API Gateway caching as temporary mitigation.

---

### P0: SES Send Quota > 90% (`p0-ses-send-quota-critical`)

**Impact**: Approaching SES daily sending limit. Once 100% is reached, all outbound email stops.

**Diagnosis steps:**
1. Check current quota and usage: `aws sesv2 get-account` → `SendQuota`.
2. Identify which orgs are consuming the most sending volume today.
3. Determine if this is a legitimate traffic increase or an anomaly.

**Mitigation:**
- Request SES sending limit increase via AWS Support (takes 24-48 hours for approval).
- If a single tenant is responsible: Apply per-tenant sending rate limit.
- If legitimate growth: Request limit increase proactively (should have been done before reaching 70%, which is the P1 alarm).
- Short-term: Enable multi-region SES sending to distribute across regions (each region has independent quotas).
