# EventBridge Integration Patterns

Kinesis Data Streams is the primary event bus for AgentMail -- it handles high-volume email events with per-inbox ordering and 7-day replay. EventBridge serves a complementary role: scheduled tasks, operational lifecycle events, cross-service orchestration, and reactions to AWS service state changes. This document covers every EventBridge pattern in the AgentMail platform.

---

## 1. EventBridge vs Kinesis: When to Use Which

### Decision Matrix

| Criterion | Kinesis Data Streams | EventBridge |
|-----------|---------------------|-------------|
| **Volume** | High (100K+ events/min) | Low-to-medium (< 1K events/min) |
| **Ordering** | Per-shard (partition on inboxId) | No ordering guarantees |
| **Replay** | 7-day retention, per-consumer seek | Archive replay (all-or-nothing) |
| **Latency** | ~70ms (enhanced fan-out push) | ~500ms typical |
| **Scheduling** | Not supported | Native cron and rate expressions |
| **Pattern matching** | Consumer-side filtering | Server-side content-based routing |
| **AWS service integration** | Manual (poll/subscribe) | Native (200+ event sources) |
| **Cost model** | Per-shard-hour + per-GB | Per-event ($1/million) |
| **Payload size** | 1 MB | 256 KB |
| **Fan-out** | Enhanced fan-out (dedicated throughput) | Up to 5 targets per rule (more via SQS/SNS) |

### When to Use Kinesis

- Email lifecycle events: `message.received`, `message.sent`, `message.bounced`, `message.ai_processed`
- Any event requiring per-inbox ordering
- Events that consumers need to replay on reconnect
- High-throughput streams where per-consumer isolation matters

### When to Use EventBridge

- Scheduled/cron tasks (domain verification polling, metering aggregation, cleanup jobs)
- Operational lifecycle events (org created, tier changed, account disabled)
- Reactions to AWS service events (SES reputation, CloudWatch alarms, S3 uploads)
- Cross-service orchestration that does not require ordering
- Low-volume events where content-based routing simplifies consumer logic

### Events That Flow Through Both

Some events originate from EventBridge-triggered Lambdas but are then normalized and written to Kinesis for downstream consumers. For example, the `domain-verification-poller` Lambda is triggered by an EventBridge schedule, but when a domain's verification status changes, it writes a `domain.verified` event to Kinesis so that webhook and WebSocket consumers can notify customers.

---

## 2. Scheduled Rules (EventBridge Scheduler)

All scheduled tasks use EventBridge Scheduler (not the legacy EventBridge Rules cron). Scheduler provides one-time and recurring schedules with built-in retry, dead-letter queues, and timezone support.

### Schedule Summary

| Schedule | Target Lambda | Purpose |
|----------|--------------|---------|
| Every 5 minutes | `domain-verification-poller` | Poll SES for pending domain verification status |
| Every 1 hour | `metering-aggregator` | Aggregate usage counters, submit BatchMeterUsage |
| Every 1 hour | `quota-reset-checker` | Check for orgs needing monthly quota resets |
| Every 30 seconds | `websocket-heartbeat` | Send pings to all WebSocket connections |
| Every 6 hours | `webhook-health-checker` | Check disabled webhooks, send re-enable notifications |
| Every 24 hours | `retention-cleanup` | Delete expired messages per org retention policy |
| Every 24 hours | `abuse-detector` | Scan for abuse patterns (spam, squatting, high bounce) |
| Every 24 hours | `ses-reputation-reporter` | Compile per-org SES reputation metrics |
| Weekly (Sun 2:00 UTC) | `storage-recalculator` | Recalculate per-org storage usage from S3 |
| Every 5 minutes | `ip-warming-manager` | Manage dedicated IP warming schedules |

---

### 2.1 Domain Verification Poller

**Schedule:** Every 5 minutes
**Purpose:** Polls SES `GetIdentityVerificationAttributes` for domains in `pending_verification` status. When a domain's DKIM/SPF records are confirmed, updates the domain record in DynamoDB and emits a `domain.verified` event to Kinesis. If a domain has been pending for more than 72 hours, publishes a `domain.verification_timeout` event to the `agentmail-ops` EventBridge bus.

**Scheduler Definition (CDK):**

```typescript
const domainVerificationSchedule = new scheduler.CfnSchedule(this, 'DomainVerificationSchedule', {
  name: 'agentmail-domain-verification-poller',
  description: 'Poll SES for pending domain verification status',
  scheduleExpression: 'rate(5 minutes)',
  flexibleTimeWindow: { mode: 'OFF' },
  target: {
    arn: domainVerificationPollerFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 2,
      maximumEventAgeInSeconds: 300,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-domain-verification-poller",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 256,
  "Timeout": 120,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "KINESIS_STREAM_NAME": "agentmail-events",
      "OPS_EVENT_BUS_NAME": "agentmail-ops",
      "VERIFICATION_TIMEOUT_HOURS": "72"
    }
  }
}
```

**Error Handling:**
- Scheduler retries up to 2 times on Lambda failure (invocation error or timeout)
- Failed invocations after retries are sent to the scheduler DLQ (`agentmail-scheduler-dlq`)
- Lambda itself handles partial failures: if SES API call fails for one domain, it continues processing others and logs the failure
- CloudWatch alarm on `Errors` metric for this function (threshold: > 0 for 3 consecutive 5-minute periods)

---

### 2.2 Metering Aggregator

**Schedule:** Every 1 hour
**Purpose:** Reads per-org usage counters from DynamoDB (messages sent, messages received, API calls, storage bytes), aggregates them into hourly buckets, and submits `BatchMeterUsage` to AWS Marketplace Metering Service for Marketplace customers. For non-Marketplace customers, writes aggregated usage to the `billing-usage` DynamoDB table for Stripe-based billing.

**Scheduler Definition (CDK):**

```typescript
const meteringSchedule = new scheduler.CfnSchedule(this, 'MeteringAggregatorSchedule', {
  name: 'agentmail-metering-aggregator',
  description: 'Aggregate usage counters and submit BatchMeterUsage',
  scheduleExpression: 'rate(1 hour)',
  flexibleTimeWindow: { mode: 'FLEXIBLE', maximumWindowInMinutes: 5 },
  target: {
    arn: meteringAggregatorFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 3,
      maximumEventAgeInSeconds: 3600,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-metering-aggregator",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 512,
  "Timeout": 300,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "MARKETPLACE_PRODUCT_CODE": "agentmail-saas",
      "BILLING_TABLE_NAME": "agentmail-billing-usage"
    }
  }
}
```

**Error Handling:**
- Flexible time window of 5 minutes to reduce thundering-herd on the hour
- 3 retries with maximum event age of 1 hour (never processes stale invocations)
- Idempotent: uses hourly timestamp as deduplication key in BatchMeterUsage
- If Marketplace API returns `DuplicateRequest`, the Lambda treats it as success
- Alarm: if `agentmail-metering-aggregator` has zero invocations for 2 consecutive hours

---

### 2.3 Quota Reset Checker

**Schedule:** Every 1 hour
**Purpose:** Queries DynamoDB for organizations whose monthly quota reset date has passed. Resets usage counters (messages sent, API calls, etc.) to zero for the new billing period. Emits a `tenant.quota_reset` event to the ops bus.

**Scheduler Definition (CDK):**

```typescript
const quotaResetSchedule = new scheduler.CfnSchedule(this, 'QuotaResetCheckerSchedule', {
  name: 'agentmail-quota-reset-checker',
  description: 'Check for orgs needing monthly quota resets',
  scheduleExpression: 'rate(1 hour)',
  flexibleTimeWindow: { mode: 'FLEXIBLE', maximumWindowInMinutes: 10 },
  target: {
    arn: quotaResetCheckerFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 2,
      maximumEventAgeInSeconds: 3600,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-quota-reset-checker",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 256,
  "Timeout": 120,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "OPS_EVENT_BUS_NAME": "agentmail-ops"
    }
  }
}
```

**Error Handling:**
- Idempotent: each reset is conditional on the current billing period not matching the stored `lastResetPeriod`
- Uses DynamoDB conditional writes to prevent double-resets if the Lambda runs twice
- Alarm: CloudWatch metric filter on Lambda logs for `RESET_FAILED` pattern

---

### 2.4 WebSocket Heartbeat

**Schedule:** Every 30 seconds
**Purpose:** Queries the `agentmail-websocket-connections` DynamoDB table for all active connections and sends a WebSocket ping frame via API Gateway `@connections` POST. Stale connections that fail the ping are deleted from DynamoDB, freeing up connection count quota.

**Scheduler Definition (CDK):**

```typescript
const heartbeatSchedule = new scheduler.CfnSchedule(this, 'WebSocketHeartbeatSchedule', {
  name: 'agentmail-websocket-heartbeat',
  description: 'Send pings to all WebSocket connections',
  // EventBridge Scheduler minimum rate is 1 minute; use rate(1 minute) and
  // have the Lambda run two heartbeat passes 30 seconds apart internally.
  scheduleExpression: 'rate(1 minute)',
  flexibleTimeWindow: { mode: 'OFF' },
  target: {
    arn: websocketHeartbeatFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 0,  // No retries -- next heartbeat will come in 1 minute
      maximumEventAgeInSeconds: 60,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-websocket-heartbeat",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 512,
  "Timeout": 55,
  "ReservedConcurrentExecutions": 5,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "WEBSOCKET_API_ENDPOINT": "https://ws.agentmail.to",
      "CONNECTION_TTL_SECONDS": "300"
    }
  }
}
```

**Note:** EventBridge Scheduler's minimum rate is 1 minute, not 30 seconds. The Lambda internally performs two heartbeat passes: one immediately upon invocation and another after a 30-second `asyncio.sleep`. This achieves the effective 30-second heartbeat interval within a single 1-minute schedule.

**Error Handling:**
- No retries (stale heartbeat data is worse than a skipped heartbeat)
- If a `@connections` POST returns `GoneException` (410), the connection record is deleted from DynamoDB
- Connections that have not received a successful heartbeat in 5 minutes are force-disconnected
- Metric: `WebSocketStaleConnections` emitted per heartbeat cycle

---

### 2.5 Webhook Health Checker

**Schedule:** Every 6 hours
**Purpose:** Queries DynamoDB for webhook endpoints with `status: "disabled"`. For each, checks if the endpoint is reachable (sends a lightweight health check POST). If reachable, sends a notification email to the org admin with a link to re-enable the endpoint. Does not auto-re-enable -- that requires explicit customer action via the API.

**Scheduler Definition (CDK):**

```typescript
const webhookHealthSchedule = new scheduler.CfnSchedule(this, 'WebhookHealthCheckerSchedule', {
  name: 'agentmail-webhook-health-checker',
  description: 'Check disabled webhooks and send re-enable notifications',
  scheduleExpression: 'rate(6 hours)',
  flexibleTimeWindow: { mode: 'FLEXIBLE', maximumWindowInMinutes: 15 },
  target: {
    arn: webhookHealthCheckerFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 2,
      maximumEventAgeInSeconds: 21600,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-webhook-health-checker",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 256,
  "Timeout": 120,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "SES_FROM_ADDRESS": "notifications@agentmail.to",
      "DASHBOARD_URL": "https://dashboard.agentmail.to"
    }
  }
}
```

**Error Handling:**
- Health check uses a 5-second timeout per endpoint
- Sends at most one re-enable notification per endpoint per 24 hours (tracked via `lastNotificationAt` attribute)
- If SES `send_email` fails, logs the error and continues to next endpoint

---

### 2.6 Retention Cleanup

**Schedule:** Every 24 hours (at 03:00 UTC)
**Purpose:** Scans each organization's retention policy (e.g., "delete messages older than 30 days"). Queries DynamoDB for messages past their retention date, deletes the message records and their S3 attachments. Operates in batches to avoid Lambda timeout.

**Scheduler Definition (CDK):**

```typescript
const retentionCleanupSchedule = new scheduler.CfnSchedule(this, 'RetentionCleanupSchedule', {
  name: 'agentmail-retention-cleanup',
  description: 'Delete expired messages per org retention policy',
  scheduleExpression: 'cron(0 3 * * ? *)',
  scheduleExpressionTimezone: 'UTC',
  flexibleTimeWindow: { mode: 'FLEXIBLE', maximumWindowInMinutes: 30 },
  target: {
    arn: retentionCleanupFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 2,
      maximumEventAgeInSeconds: 86400,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-retention-cleanup",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 1024,
  "Timeout": 900,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "ATTACHMENTS_BUCKET": "agentmail-attachments",
      "BATCH_SIZE": "100"
    }
  }
}
```

**Error Handling:**
- Processes orgs in batches; if Lambda times out, the next daily run picks up where it left off (queries by `retentionDeletedBefore` timestamp)
- S3 deletions use `delete_objects` batch API (up to 1,000 keys per call)
- Emits `retention.cleanup_completed` metric with count of deleted messages per org
- If a single org's cleanup fails, the Lambda logs the error and continues to the next org

---

### 2.7 Abuse Detector

**Schedule:** Every 24 hours (at 04:00 UTC)
**Purpose:** Scans for abuse patterns across all organizations: high outbound volume from free-tier accounts, inbox name squatting (registering common names like `admin@`, `support@` across many domains), elevated bounce rates, and spam complaint signals from SES feedback. Flagged organizations are placed into a `review_required` state and an alert is sent to the AgentMail ops team via SNS.

**Scheduler Definition (CDK):**

```typescript
const abuseDetectorSchedule = new scheduler.CfnSchedule(this, 'AbuseDetectorSchedule', {
  name: 'agentmail-abuse-detector',
  description: 'Scan for abuse patterns (spam, squatting, high bounce)',
  scheduleExpression: 'cron(0 4 * * ? *)',
  scheduleExpressionTimezone: 'UTC',
  flexibleTimeWindow: { mode: 'FLEXIBLE', maximumWindowInMinutes: 30 },
  target: {
    arn: abuseDetectorFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 2,
      maximumEventAgeInSeconds: 86400,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-abuse-detector",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 1024,
  "Timeout": 900,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "OPS_SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:ACCOUNT:agentmail-ops-alerts",
      "BOUNCE_RATE_THRESHOLD": "0.05",
      "COMPLAINT_RATE_THRESHOLD": "0.001",
      "FREE_TIER_DAILY_SEND_LIMIT": "100"
    }
  }
}
```

**Error Handling:**
- Non-critical: if the detector fails, the ops team is alerted via the scheduler DLQ alarm, and the next daily run will catch accumulated patterns
- Each abuse check (bounce rate, squatting, volume) runs independently; one failure does not block others

---

### 2.8 SES Reputation Reporter

**Schedule:** Every 24 hours (at 05:00 UTC)
**Purpose:** Calls SES `GetAccountSendingStatistics` and `GetSendQuota`, then breaks down reputation metrics per organization by correlating SES message tags with org IDs. Writes a daily reputation report to DynamoDB and S3. Publishes a `ses.reputation_alert` event to the ops bus if any org exceeds safe thresholds (bounce rate > 5%, complaint rate > 0.1%).

**Scheduler Definition (CDK):**

```typescript
const reputationReporterSchedule = new scheduler.CfnSchedule(this, 'SESReputationReporterSchedule', {
  name: 'agentmail-ses-reputation-reporter',
  description: 'Compile per-org SES reputation metrics',
  scheduleExpression: 'cron(0 5 * * ? *)',
  scheduleExpressionTimezone: 'UTC',
  flexibleTimeWindow: { mode: 'FLEXIBLE', maximumWindowInMinutes: 15 },
  target: {
    arn: sesReputationReporterFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 2,
      maximumEventAgeInSeconds: 86400,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-ses-reputation-reporter",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 512,
  "Timeout": 300,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "REPORTS_BUCKET": "agentmail-reports",
      "OPS_EVENT_BUS_NAME": "agentmail-ops",
      "BOUNCE_RATE_ALERT_THRESHOLD": "0.05",
      "COMPLAINT_RATE_ALERT_THRESHOLD": "0.001"
    }
  }
}
```

**Error Handling:**
- If SES API is throttled, uses exponential backoff with jitter (up to 3 retries internal to the Lambda)
- Reports are idempotent: keyed by `{orgId}#REPORT#{date}` in DynamoDB with conditional write

---

### 2.9 Storage Recalculator

**Schedule:** Weekly (Sunday at 02:00 UTC)
**Purpose:** Recalculates per-org storage usage by listing S3 objects under each org's prefix in the attachments bucket. This corrects any drift between the real-time usage counters (incremented on upload, decremented on delete) and actual S3 storage. Writes the authoritative storage figure to the org record in DynamoDB.

**Scheduler Definition (CDK):**

```typescript
const storageRecalcSchedule = new scheduler.CfnSchedule(this, 'StorageRecalculatorSchedule', {
  name: 'agentmail-storage-recalculator',
  description: 'Recalculate per-org storage usage from S3',
  scheduleExpression: 'cron(0 2 ? * SUN *)',
  scheduleExpressionTimezone: 'UTC',
  flexibleTimeWindow: { mode: 'FLEXIBLE', maximumWindowInMinutes: 60 },
  target: {
    arn: storageRecalculatorFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 2,
      maximumEventAgeInSeconds: 86400,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-storage-recalculator",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 1024,
  "Timeout": 900,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "ATTACHMENTS_BUCKET": "agentmail-attachments"
    }
  }
}
```

**Error Handling:**
- Uses S3 `list_objects_v2` with pagination; if Lambda times out mid-org, it stores a continuation token in DynamoDB and picks up on the next weekly run
- Large orgs (> 1M objects) are processed using S3 Inventory reports instead of listing
- Flexible time window of 60 minutes to avoid competing with retention cleanup (runs at 03:00)

---

### 2.10 IP Warming Manager

**Schedule:** Every 5 minutes
**Purpose:** Manages dedicated IP warming schedules for organizations using dedicated SES IP addresses. Reads the warming schedule (day number, daily volume target, percentage allocation per IP) from DynamoDB and adjusts SES sending rate configuration. Redistributes sending across IPs as they warm up, gradually shifting traffic from shared IPs to dedicated IPs.

**Scheduler Definition (CDK):**

```typescript
const ipWarmingSchedule = new scheduler.CfnSchedule(this, 'IPWarmingManagerSchedule', {
  name: 'agentmail-ip-warming-manager',
  description: 'Manage dedicated IP warming schedules',
  scheduleExpression: 'rate(5 minutes)',
  flexibleTimeWindow: { mode: 'OFF' },
  target: {
    arn: ipWarmingManagerFn.functionArn,
    roleArn: schedulerRole.roleArn,
    retryPolicy: {
      maximumRetryAttempts: 2,
      maximumEventAgeInSeconds: 300,
    },
    deadLetterConfig: {
      arn: schedulerDlq.queueArn,
    },
  },
  state: 'ENABLED',
});
```

**Lambda Function:**

```json
{
  "FunctionName": "agentmail-ip-warming-manager",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 256,
  "Timeout": 120,
  "ReservedConcurrentExecutions": 1,
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "SES_CONFIGURATION_SET": "agentmail-dedicated"
    }
  }
}
```

**Error Handling:**
- Read-only check when no warming schedules are active (exits early, sub-second execution)
- If SES rate limit update fails, retries on next 5-minute cycle
- Alarm: if warming schedule falls behind target volume by > 20% for 2 consecutive hours

---

## 3. Operational Event Patterns

Operational lifecycle events are published to a custom EventBridge bus (`agentmail-ops`). These are low-volume, high-importance events that drive cross-service workflows: provisioning, billing, account lifecycle, and platform health.

### Custom Event Bus

```json
{
  "Name": "agentmail-ops",
  "Description": "Operational lifecycle events for cross-service orchestration",
  "Tags": [
    { "Key": "Service", "Value": "agentmail" },
    { "Key": "Component", "Value": "ops-events" }
  ]
}
```

### Event Catalog

---

### 3.1 org.created

**Source:** `agentmail.saas-platform`
**Detail Type:** `OrganizationCreated`
**Trigger:** New customer signs up (via direct signup or Marketplace)

**Event JSON:**

```json
{
  "version": "0",
  "id": "a1b2c3d4-5678-90ab-cdef-111111111111",
  "source": "agentmail.saas-platform",
  "detail-type": "OrganizationCreated",
  "account": "123456789012",
  "time": "2026-04-10T14:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "orgName": "Acme Corp",
    "tier": "free",
    "source": "direct",
    "adminEmail": "admin@acme.com",
    "createdAt": "2026-04-10T14:00:00.000Z"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `org-created-provisioning` | `source: agentmail.saas-platform, detail-type: OrganizationCreated` | Lambda: `org-provisioner` | Create default pod, default inbox, seed DynamoDB records, provision SES sending identity |
| `org-created-welcome` | Same pattern | SQS: `agentmail-email-outbound` | Queue welcome email to org admin |
| `org-created-analytics` | Same pattern | Kinesis Firehose: `agentmail-analytics` | Record signup event in analytics data lake |

**Rule Definition (CDK):**

```typescript
const orgCreatedRule = new events.Rule(this, 'OrgCreatedRule', {
  eventBus: opsBus,
  ruleName: 'org-created-provisioning',
  description: 'Provision new organization resources on signup',
  eventPattern: {
    source: ['agentmail.saas-platform'],
    detailType: ['OrganizationCreated'],
  },
  targets: [
    new targets.LambdaFunction(orgProvisionerFn, {
      deadLetterQueue: opsRuleDlq,
      retryAttempts: 3,
      maxEventAge: cdk.Duration.hours(1),
    }),
    new targets.SqsQueue(emailOutboundQueue, {
      message: events.RuleTargetInput.fromEventPath('$.detail'),
    }),
    new targets.KinesisFirehoseStream(analyticsFirehose),
  ],
});
```

---

### 3.2 org.tier_changed

**Source:** `agentmail.billing-service`
**Detail Type:** `TierChanged`
**Trigger:** Customer upgrades or downgrades their plan

**Event JSON:**

```json
{
  "version": "0",
  "id": "b2c3d4e5-6789-01bc-def0-222222222222",
  "source": "agentmail.billing-service",
  "detail-type": "TierChanged",
  "account": "123456789012",
  "time": "2026-04-10T15:30:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "previousTier": "free",
    "newTier": "pro",
    "effectiveAt": "2026-04-10T15:30:00.000Z",
    "reason": "customer_upgrade",
    "stripeSubscriptionId": "sub_1234567890"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `tier-changed-quota-update` | `detail-type: TierChanged` | Lambda: `quota-updater` | Update org's rate limits, storage quota, inbox limits per new tier |
| `tier-changed-feature-toggle` | Same | Lambda: `feature-toggler` | Enable/disable tier-gated features (AI processing, custom domains, dedicated IPs) |
| `tier-changed-notification` | Same, filter: `detail.reason: ["customer_upgrade"]` | SQS: `agentmail-email-outbound` | Send upgrade confirmation email |

---

### 3.3 org.disabled

**Source:** `agentmail.lifecycle-service`
**Detail Type:** `OrganizationDisabled`
**Trigger:** Account deactivation (voluntary cancellation, payment failure after grace period, or abuse suspension)

**Event JSON:**

```json
{
  "version": "0",
  "id": "c3d4e5f6-7890-12cd-ef01-333333333333",
  "source": "agentmail.lifecycle-service",
  "detail-type": "OrganizationDisabled",
  "account": "123456789012",
  "time": "2026-04-10T16:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "reason": "payment_failure_grace_expired",
    "disabledAt": "2026-04-10T16:00:00.000Z",
    "gracePeriodDays": 30,
    "scheduledDeletionAt": "2026-05-10T16:00:00.000Z"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `org-disabled-suspend` | `detail-type: OrganizationDisabled` | Lambda: `org-suspender` | Disable all inbound email processing, reject API calls, pause SES sending |
| `org-disabled-notify` | Same | SQS: `agentmail-email-outbound` | Send account disabled notification with reactivation instructions |
| `org-disabled-schedule-delete` | Same | EventBridge Scheduler (one-time) | Schedule an `org.deleted` event 30 days in the future |

---

### 3.4 org.deleted

**Source:** `agentmail.lifecycle-service`
**Detail Type:** `OrganizationDeleted`
**Trigger:** Final data cleanup after the grace period expires (30 days post-disable)

**Event JSON:**

```json
{
  "version": "0",
  "id": "d4e5f6a7-8901-23de-f012-444444444444",
  "source": "agentmail.lifecycle-service",
  "detail-type": "OrganizationDeleted",
  "account": "123456789012",
  "time": "2026-05-10T16:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "deletedAt": "2026-05-10T16:00:00.000Z",
    "dataRetentionCompliance": "gdpr"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `org-deleted-cleanup` | `detail-type: OrganizationDeleted` | Step Functions: `org-data-cleanup` | Orchestrate deletion of all org data: DynamoDB records, S3 objects, SES identities, API keys |
| `org-deleted-audit` | Same | Kinesis Firehose: `agentmail-audit-log` | Record deletion event for compliance audit trail |

The Step Functions workflow for `org-data-cleanup` runs parallel deletion tasks:
1. Delete all DynamoDB items with `PK: ORG#{orgId}` (paginated scan + batch delete)
2. Delete S3 prefix `s3://agentmail-attachments/{orgId}/` (S3 batch delete)
3. Delete SES domain identities associated with the org
4. Revoke all API keys
5. Delete webhook endpoints and delivery logs
6. Write a final audit record confirming deletion

---

### 3.5 domain.verification_timeout

**Source:** `agentmail.domain-poller`
**Detail Type:** `DomainVerificationTimeout`
**Trigger:** A custom domain has been in `pending_verification` status for more than 72 hours

**Event JSON:**

```json
{
  "version": "0",
  "id": "e5f6a7b8-9012-34ef-0123-555555555555",
  "source": "agentmail.domain-poller",
  "detail-type": "DomainVerificationTimeout",
  "account": "123456789012",
  "time": "2026-04-13T14:05:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "domainId": "dom_01JRWXABC123DEF456GHI789JK",
    "domain": "mail.acme.com",
    "submittedAt": "2026-04-10T14:00:00.000Z",
    "timeoutAt": "2026-04-13T14:05:00.000Z",
    "missingRecords": ["DKIM CNAME 1", "DKIM CNAME 2", "MX record"]
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `domain-timeout-notify` | `detail-type: DomainVerificationTimeout` | Lambda: `domain-timeout-notifier` | Send email to org admin with DNS configuration instructions and troubleshooting link |
| `domain-timeout-status` | Same | Lambda: `domain-status-updater` | Update domain status to `verification_failed` in DynamoDB |

---

### 3.6 tenant.quota_warning

**Source:** `agentmail.quota-service`
**Detail Type:** `QuotaWarning`
**Trigger:** Organization usage reaches 80% of any quota limit (messages, API calls, storage, inboxes)

**Event JSON:**

```json
{
  "version": "0",
  "id": "f6a7b8c9-0123-45f0-1234-666666666666",
  "source": "agentmail.quota-service",
  "detail-type": "QuotaWarning",
  "account": "123456789012",
  "time": "2026-04-10T18:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "quotaType": "messages_sent",
    "currentUsage": 8000,
    "limit": 10000,
    "usagePercent": 80,
    "tier": "pro",
    "billingPeriodEnd": "2026-04-30T23:59:59.000Z"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `quota-warning-notify` | `detail-type: QuotaWarning` | Lambda: `quota-notification-sender` | Send in-app notification and email to org admin about approaching quota |
| `quota-warning-kinesis` | Same | Kinesis: `agentmail-events` (via Lambda) | Emit `tenant.quota_warning` event on Kinesis for webhook/WebSocket delivery to customers |

---

### 3.7 tenant.quota_exceeded

**Source:** `agentmail.quota-service`
**Detail Type:** `QuotaExceeded`
**Trigger:** Organization hits a hard quota limit

**Event JSON:**

```json
{
  "version": "0",
  "id": "a7b8c9d0-1234-56a1-2345-777777777777",
  "source": "agentmail.quota-service",
  "detail-type": "QuotaExceeded",
  "account": "123456789012",
  "time": "2026-04-10T20:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "quotaType": "messages_sent",
    "currentUsage": 10000,
    "limit": 10000,
    "tier": "pro",
    "action": "reject_sends",
    "billingPeriodEnd": "2026-04-30T23:59:59.000Z"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `quota-exceeded-enforce` | `detail-type: QuotaExceeded` | Lambda: `quota-enforcer` | Set org-level rate limit to zero for the exceeded resource, reject API calls for that action |
| `quota-exceeded-notify` | Same | Lambda: `quota-notification-sender` | Send urgent email with upgrade CTA |
| `quota-exceeded-ops` | Same, filter: `detail.tier: ["enterprise"]` | SNS: `agentmail-ops-alerts` | Alert ops team when enterprise customers hit limits (potential churn risk) |

---

### 3.8 marketplace.customer_subscribed

**Source:** `agentmail.marketplace-handler`
**Detail Type:** `CustomerSubscribed`
**Trigger:** New customer subscribes via AWS Marketplace

**Event JSON:**

```json
{
  "version": "0",
  "id": "b8c9d0e1-2345-67b2-3456-888888888888",
  "source": "agentmail.marketplace-handler",
  "detail-type": "CustomerSubscribed",
  "account": "123456789012",
  "time": "2026-04-10T12:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRWX123NEW456ORG789ABC",
    "marketplaceCustomerId": "mkt_cust_abc123",
    "productCode": "agentmail-saas",
    "dimension": "pro",
    "awsAccountId": "987654321098",
    "registrationToken": "tok_...",
    "subscribedAt": "2026-04-10T12:00:00.000Z"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `marketplace-subscribed-provision` | `detail-type: CustomerSubscribed` | Lambda: `marketplace-provisioner` | Resolve registration token, create org, link Marketplace customer ID to org |
| `marketplace-subscribed-welcome` | Same | SQS: `agentmail-email-outbound` | Send Marketplace-specific welcome email with setup instructions |

---

### 3.9 marketplace.customer_unsubscribed

**Source:** `agentmail.marketplace-handler`
**Detail Type:** `CustomerUnsubscribed`
**Trigger:** Customer cancels their AWS Marketplace subscription

**Event JSON:**

```json
{
  "version": "0",
  "id": "c9d0e1f2-3456-78c3-4567-999999999999",
  "source": "agentmail.marketplace-handler",
  "detail-type": "CustomerUnsubscribed",
  "account": "123456789012",
  "time": "2026-04-10T22:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "marketplaceCustomerId": "mkt_cust_abc123",
    "productCode": "agentmail-saas",
    "cancelledAt": "2026-04-10T22:00:00.000Z",
    "effectiveAt": "2026-04-30T23:59:59.000Z"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `marketplace-unsubscribed-lifecycle` | `detail-type: CustomerUnsubscribed` | Lambda: `org-lifecycle-manager` | Schedule org disablement at `effectiveAt` date, stop metering |
| `marketplace-unsubscribed-notify` | Same | SQS: `agentmail-email-outbound` | Send cancellation confirmation with data export instructions |

---

### 3.10 billing.payment_failed

**Source:** `agentmail.stripe-webhook`
**Detail Type:** `PaymentFailed`
**Trigger:** Stripe webhook reports a failed payment (`invoice.payment_failed`)

**Event JSON:**

```json
{
  "version": "0",
  "id": "d0e1f2a3-4567-89d4-5678-aaaaaaaaaaaa",
  "source": "agentmail.stripe-webhook",
  "detail-type": "PaymentFailed",
  "account": "123456789012",
  "time": "2026-04-10T10:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "stripeCustomerId": "cus_abc123",
    "stripeInvoiceId": "in_xyz789",
    "amountDue": 4900,
    "currency": "usd",
    "attemptCount": 1,
    "nextRetryAt": "2026-04-13T10:00:00.000Z",
    "failureReason": "card_declined"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `payment-failed-notify` | `detail-type: PaymentFailed` | Lambda: `payment-failure-notifier` | Send dunning email to org admin with payment update link |
| `payment-failed-grace` | Same, filter: `detail.attemptCount: [3]` | Lambda: `org-lifecycle-manager` | After 3rd failed attempt, start grace period countdown |
| `payment-failed-ops` | Same, filter: `detail.amountDue: [{ "numeric": [">", 50000] }]` | SNS: `agentmail-ops-alerts` | Alert ops for high-value failed payments (> $500) |

---

### 3.11 ses.reputation_alert

**Source:** `agentmail.reputation-monitor`
**Detail Type:** `ReputationAlert`
**Trigger:** Per-org bounce rate exceeds 5% or complaint rate exceeds 0.1%

**Event JSON:**

```json
{
  "version": "0",
  "id": "e1f2a3b4-5678-90e5-6789-bbbbbbbbbbbb",
  "source": "agentmail.reputation-monitor",
  "detail-type": "ReputationAlert",
  "account": "123456789012",
  "time": "2026-04-10T05:15:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
    "alertType": "high_bounce_rate",
    "bounceRate": 0.072,
    "complaintRate": 0.0005,
    "sendVolume24h": 15000,
    "threshold": 0.05,
    "severity": "warning",
    "recommendation": "Review recipient list quality and remove invalid addresses"
  }
}
```

**Matching Rules and Targets:**

| Rule Name | Pattern | Target | Purpose |
|-----------|---------|--------|---------|
| `reputation-alert-throttle` | `detail-type: ReputationAlert` | Lambda: `ses-throttler` | Reduce org's sending rate to protect platform-wide SES reputation |
| `reputation-alert-notify-customer` | Same | Lambda: `reputation-alert-notifier` | Notify org admin about reputation issue with remediation steps |
| `reputation-alert-ops` | Same, filter: `detail.severity: ["critical"]` | SNS: `agentmail-ops-alerts` | Page ops team for critical reputation events |

---

## 4. AWS Service Integration Patterns

EventBridge rules that react to native AWS service events, using the default event bus.

### 4.1 SES Sending Events via CloudWatch

SES publishes sending events (bounces, complaints, deliveries, rejects) to CloudWatch via configuration sets. These are captured by EventBridge rules on the default bus.

**Rule: SES Bounce Rate Alarm**

```typescript
const sesBounceRule = new events.Rule(this, 'SESBounceAlarmRule', {
  ruleName: 'ses-bounce-alarm-handler',
  description: 'Handle CloudWatch alarm state changes for SES bounce rate',
  eventPattern: {
    source: ['aws.cloudwatch'],
    detailType: ['CloudWatch Alarm State Change'],
    detail: {
      alarmName: [{ prefix: 'agentmail-ses-bounce-rate' }],
      state: { value: ['ALARM'] },
    },
  },
  targets: [
    new targets.LambdaFunction(sesBounceAlarmHandlerFn, {
      deadLetterQueue: defaultBusDlq,
      retryAttempts: 3,
    }),
    new targets.SnsTopic(opsAlertsTopic, {
      message: events.RuleTargetInput.fromText(
        `SES bounce rate alarm triggered: ${events.EventField.fromPath('$.detail.alarmName')}`
      ),
    }),
  ],
});
```

**Event Flow:**

```
SES Configuration Set
  → CloudWatch Metric: ses:Bounce (per-org via message tags)
  → CloudWatch Alarm: agentmail-ses-bounce-rate-{orgId}
  → EventBridge (default bus): CloudWatch Alarm State Change
  → Lambda: ses-bounce-alarm-handler (throttle org, notify)
  → SNS: agentmail-ops-alerts (page ops if critical)
```

### 4.2 S3 Event Notifications via EventBridge

S3 publishes object-created events to EventBridge (enabled per bucket). Used to trigger virus scanning on uploaded attachments.

**Rule: Attachment Virus Scan**

```typescript
const s3VirusScanRule = new events.Rule(this, 'S3VirusScanRule', {
  ruleName: 'attachment-virus-scan-trigger',
  description: 'Trigger virus scanning when attachments are uploaded',
  eventPattern: {
    source: ['aws.s3'],
    detailType: ['Object Created'],
    detail: {
      bucket: { name: ['agentmail-attachments'] },
      object: { key: [{ prefix: 'uploads/' }] },
    },
  },
  targets: [
    new targets.LambdaFunction(virusScannerFn, {
      deadLetterQueue: defaultBusDlq,
      retryAttempts: 2,
      maxEventAge: cdk.Duration.minutes(30),
    }),
  ],
});
```

**Lambda: virus-scanner**

```json
{
  "FunctionName": "agentmail-virus-scanner",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 1024,
  "Timeout": 120,
  "Environment": {
    "Variables": {
      "QUARANTINE_BUCKET": "agentmail-quarantine",
      "TABLE_NAME": "agentmail",
      "CLAM_AV_LAYER_ARN": "arn:aws:lambda:us-east-1:ACCOUNT:layer:clamav:3"
    }
  }
}
```

**Behavior:**
1. Download the uploaded object from S3
2. Scan with ClamAV (Lambda layer)
3. If clean: move from `uploads/` to `attachments/{orgId}/{inboxId}/` prefix, update DynamoDB record
4. If infected: move to quarantine bucket, delete original, update DynamoDB record with `status: quarantined`, emit `attachment.quarantined` event to Kinesis

### 4.3 DynamoDB Streams via EventBridge (CloudTrail Data Events)

For audit-critical operations (API key creation, role changes, org settings updates), DynamoDB data-plane events captured via CloudTrail are routed through EventBridge.

**Rule: Audit-Critical Data Changes**

```typescript
const auditRule = new events.Rule(this, 'AuditCriticalChangesRule', {
  ruleName: 'audit-critical-data-changes',
  description: 'Capture audit-critical DynamoDB mutations via CloudTrail',
  eventPattern: {
    source: ['aws.dynamodb'],
    detailType: ['AWS API Call via CloudTrail'],
    detail: {
      eventName: ['PutItem', 'UpdateItem', 'DeleteItem'],
      requestParameters: {
        tableName: ['agentmail'],
      },
    },
  },
  targets: [
    new targets.KinesisFirehoseStream(auditLogFirehose),
  ],
});
```

### 4.4 CloudWatch Alarm State Changes to PagerDuty/Slack

All production CloudWatch alarms route through EventBridge to SNS topics that fan out to PagerDuty and Slack.

**Rule: Production Alarm Router**

```typescript
const alarmRouterRule = new events.Rule(this, 'ProductionAlarmRouterRule', {
  ruleName: 'production-alarm-router',
  description: 'Route all agentmail CloudWatch alarms to ops channels',
  eventPattern: {
    source: ['aws.cloudwatch'],
    detailType: ['CloudWatch Alarm State Change'],
    detail: {
      alarmName: [{ prefix: 'agentmail-' }],
      state: { value: ['ALARM'] },
    },
  },
  targets: [
    new targets.SnsTopic(pagerDutyTopic, {
      message: events.RuleTargetInput.fromObject({
        alarmName: events.EventField.fromPath('$.detail.alarmName'),
        state: events.EventField.fromPath('$.detail.state.value'),
        reason: events.EventField.fromPath('$.detail.state.reason'),
        timestamp: events.EventField.fromPath('$.time'),
      }),
    }),
    new targets.SnsTopic(slackAlertsTopic),
  ],
});
```

**SNS Subscriptions:**

| Topic | Subscriber | Protocol |
|-------|-----------|----------|
| `agentmail-pagerduty` | PagerDuty Events API v2 | HTTPS |
| `agentmail-slack-alerts` | Slack incoming webhook via Lambda | Lambda |

**Alarm Categories and Severity Mapping:**

| Alarm Prefix | Severity | PagerDuty Priority |
|-------------|----------|-------------------|
| `agentmail-ses-` | P1 (SES reputation affects all customers) | Critical |
| `agentmail-kinesis-` | P1 (event bus down = no deliveries) | Critical |
| `agentmail-api-5xx-` | P2 | High |
| `agentmail-lambda-errors-` | P3 | Low |
| `agentmail-dlq-depth-` | P3 | Low |
| `agentmail-websocket-` | P3 | Low |

---

## 5. EventBridge Pipes

EventBridge Pipes connect sources to targets with optional filtering, enrichment, and transformation -- without writing Lambda glue code.

### 5.1 DynamoDB Streams to OpenSearch (Search Indexing)

A Pipe reads from the DynamoDB stream on the `agentmail` table, filters for message and inbox record changes, enriches with org metadata, and writes to OpenSearch for full-text search.

**Pipe Configuration:**

```typescript
const searchIndexPipe = new pipes.CfnPipe(this, 'SearchIndexPipe', {
  name: 'agentmail-search-index-pipe',
  description: 'Index message and inbox changes from DynamoDB to OpenSearch',
  roleArn: searchIndexPipeRole.roleArn,

  source: dynamoDbTable.tableStreamArn!,
  sourceParameters: {
    dynamoDbStreamParameters: {
      startingPosition: 'LATEST',
      batchSize: 50,
      maximumBatchingWindowInSeconds: 5,
      maximumRetryAttempts: 3,
      deadLetterConfig: {
        arn: pipesDlq.queueArn,
      },
      parallelizationFactor: 4,
    },
    filterCriteria: {
      filters: [
        {
          pattern: JSON.stringify({
            eventName: ['INSERT', 'MODIFY'],
            dynamodb: {
              NewImage: {
                PK: { S: [{ prefix: 'ORG#' }] },
                SK: { S: [{ prefix: 'MSG#' }, { prefix: 'INBOX#' }] },
              },
            },
          }),
        },
      ],
    },
  },

  enrichment: searchEnrichmentFn.functionArn,
  enrichmentParameters: {
    inputTemplate: JSON.stringify({
      eventName: '<$.eventName>',
      newImage: '<$.dynamodb.NewImage>',
      oldImage: '<$.dynamodb.OldImage>',
    }),
  },

  target: openSearchPipelineArn,
  targetParameters: {
    httpParameters: {
      pathParameterValues: ['/agentmail-messages/_doc/${body.messageId}'],
      headerParameters: { 'Content-Type': 'application/json' },
    },
  },
});
```

**Enrichment Lambda:**

The enrichment Lambda (`agentmail-search-enrichment`) transforms DynamoDB's JSON format into OpenSearch-compatible documents:

```python
def handler(events, context):
    """Transform DynamoDB stream records into OpenSearch documents."""
    enriched = []
    for event in events:
        new_image = event["newImage"]
        sk = new_image["SK"]["S"]
        
        if sk.startswith("MSG#"):
            enriched.append({
                "messageId": new_image["messageId"]["S"],
                "inboxId": new_image["inboxId"]["S"],
                "orgId": new_image["orgId"]["S"],
                "subject": new_image.get("subject", {}).get("S", ""),
                "bodyText": new_image.get("bodyText", {}).get("S", "")[:10000],
                "from": new_image.get("from", {}).get("S", ""),
                "to": new_image.get("to", {}).get("L", []),
                "receivedAt": new_image.get("receivedAt", {}).get("S", ""),
                "direction": new_image.get("direction", {}).get("S", ""),
                "_index": "agentmail-messages",
                "_action": "index",
            })
        elif sk.startswith("INBOX#"):
            enriched.append({
                "inboxId": new_image["inboxId"]["S"],
                "orgId": new_image["orgId"]["S"],
                "address": new_image.get("address", {}).get("S", ""),
                "displayName": new_image.get("displayName", {}).get("S", ""),
                "status": new_image.get("status", {}).get("S", ""),
                "_index": "agentmail-inboxes",
                "_action": "index",
            })
    
    return enriched
```

### 5.2 SQS to Step Functions (AI Processing Orchestration)

A Pipe reads from the AI processing request queue, filters for supported content types, and starts a Step Functions execution for each request.

**Pipe Configuration:**

```typescript
const aiProcessingPipe = new pipes.CfnPipe(this, 'AIProcessingPipe', {
  name: 'agentmail-ai-processing-pipe',
  description: 'Route AI processing requests from SQS to Step Functions',
  roleArn: aiProcessingPipeRole.roleArn,

  source: aiProcessingQueue.queueArn,
  sourceParameters: {
    sqsQueueParameters: {
      batchSize: 1,
      maximumBatchingWindowInSeconds: 0,
    },
    filterCriteria: {
      filters: [
        {
          pattern: JSON.stringify({
            body: {
              contentType: ['text/plain', 'text/html', 'application/pdf'],
              processingType: ['summarize', 'classify', 'extract', 'auto-reply'],
            },
          }),
        },
      ],
    },
  },

  target: aiProcessingStateMachine.stateMachineArn,
  targetParameters: {
    stepFunctionStateMachineParameters: {
      invocationType: 'FIRE_AND_FORGET',
    },
    inputTemplate: JSON.stringify({
      messageId: '<$.body.messageId>',
      inboxId: '<$.body.inboxId>',
      orgId: '<$.body.orgId>',
      processingType: '<$.body.processingType>',
      contentType: '<$.body.contentType>',
      s3Key: '<$.body.s3Key>',
    }),
  },
});
```

**Behavior:**
1. AI processing requests arrive on SQS from the Kinesis consumer (when an inbox has AI rules configured)
2. The Pipe filters for supported content types (ignores image-only messages for now)
3. Each matching message starts a Step Functions execution that orchestrates: content extraction, Bedrock inference, result storage, and event emission
4. Unsupported content types remain in the queue and are consumed by a fallback Lambda that marks them as `processing_skipped`

---

## 6. Dead Letter Queues and Error Handling

Every EventBridge rule and Scheduler schedule has a dead letter queue. Failed events are never silently dropped.

### 6.1 DLQ Architecture

```
EventBridge Rules (agentmail-ops bus)
    │
    │  On target invocation failure (after retries)
    │
    ▼
SQS: agentmail-ops-rules-dlq
    │
    ▼
Lambda: ops-dlq-processor
    ├── Log to CloudWatch (structured JSON)
    ├── Archive to S3: s3://agentmail-dlq-archive/ops-rules/{date}/{eventId}.json
    └── Increment CloudWatch metric: OpsRuleDLQDepth


EventBridge Scheduler (all schedules)
    │
    │  On target invocation failure (after retries)
    │
    ▼
SQS: agentmail-scheduler-dlq
    │
    ▼
Lambda: scheduler-dlq-processor
    ├── Log to CloudWatch (structured JSON)
    ├── Archive to S3: s3://agentmail-dlq-archive/scheduler/{date}/{scheduleName}.json
    └── Increment CloudWatch metric: SchedulerDLQDepth


EventBridge Pipes (all pipes)
    │
    │  On processing failure (after retries)
    │
    ▼
SQS: agentmail-pipes-dlq
    │
    ▼
Lambda: pipes-dlq-processor
    ├── Log to CloudWatch (structured JSON)
    ├── Archive to S3: s3://agentmail-dlq-archive/pipes/{date}/{pipeId}.json
    └── Increment CloudWatch metric: PipesDLQDepth
```

### 6.2 Retry Policies

| Component | Max Retry Attempts | Max Event Age | Rationale |
|-----------|-------------------|---------------|-----------|
| Scheduled rules (critical: metering, quota) | 3 | 1 hour | Must succeed within the schedule interval |
| Scheduled rules (non-critical: heartbeat) | 0 | 1 minute | Stale heartbeats are useless |
| Scheduled rules (daily: cleanup, abuse) | 2 | 24 hours | Long window; next daily run is fallback |
| Ops bus rules (provisioning) | 3 | 1 hour | New org must be provisioned promptly |
| Ops bus rules (notifications) | 2 | 6 hours | Notifications can be delayed but should arrive |
| Ops bus rules (analytics) | 1 | 24 hours | Analytics can tolerate delay |
| Pipes (search indexing) | 3 | N/A (source-based) | Search index can rebuild from DynamoDB |
| Pipes (AI processing) | 0 | N/A (source-based) | Retry handled by SQS redrive policy |

### 6.3 Monitoring and Alarms

**CloudWatch Alarms:**

```typescript
// DLQ depth alarms
const dlqAlarms = [
  { name: 'agentmail-ops-rules-dlq', threshold: 10, period: 300 },
  { name: 'agentmail-scheduler-dlq', threshold: 5, period: 300 },
  { name: 'agentmail-pipes-dlq', threshold: 20, period: 300 },
];

for (const dlq of dlqAlarms) {
  new cloudwatch.Alarm(this, `${dlq.name}-depth-alarm`, {
    alarmName: `agentmail-dlq-depth-${dlq.name}`,
    metric: new cloudwatch.Metric({
      namespace: 'AWS/SQS',
      metricName: 'ApproximateNumberOfMessagesVisible',
      dimensionsMap: { QueueName: dlq.name },
      statistic: 'Maximum',
      period: cdk.Duration.seconds(dlq.period),
    }),
    threshold: dlq.threshold,
    evaluationPeriods: 2,
    comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
    treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    actionsEnabled: true,
    alarmActions: [opsAlertsTopic],
  });
}
```

**EventBridge FailedInvocations Metric:**

```typescript
// Monitor EventBridge rule invocation failures
const failedInvocationsAlarm = new cloudwatch.Alarm(this, 'OpsRuleFailedInvocations', {
  alarmName: 'agentmail-ops-bus-failed-invocations',
  metric: new cloudwatch.Metric({
    namespace: 'AWS/Events',
    metricName: 'FailedInvocations',
    dimensionsMap: { EventBusName: 'agentmail-ops' },
    statistic: 'Sum',
    period: cdk.Duration.minutes(5),
  }),
  threshold: 0,
  evaluationPeriods: 1,
  comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
  treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
  alarmActions: [opsAlertsTopic],
});
```

**Dashboard Widgets:**

| Widget | Type | Source |
|--------|------|--------|
| Scheduler Invocations (success/fail) | Stacked area | `AWS/Scheduler` `InvocationCount`, `TargetErrorCount` |
| Ops Bus Event Volume | Line | `AWS/Events` `Invocations` by rule |
| Ops Bus Failed Invocations | Number (alarm) | `AWS/Events` `FailedInvocations` |
| DLQ Depths | Multi-number | `AWS/SQS` `ApproximateNumberOfMessagesVisible` per DLQ |
| Pipe Records Processed | Line | `AWS/EventBridge/Pipes` `ExecutionCount` |
| Pipe Failures | Number (alarm) | `AWS/EventBridge/Pipes` `ExecutionFailed` |

---

## 7. CDK Configuration

Complete CDK stack for the EventBridge infrastructure. This stack creates the custom event bus, all rules, all Scheduler schedules, DLQs, IAM roles, and Pipes.

### 7.1 Event Bus and DLQs

```typescript
import * as cdk from 'aws-cdk-lib';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as pipes from 'aws-cdk-lib/aws-pipes';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';

export interface EventBridgeStackProps extends cdk.StackProps {
  domainVerificationPollerFn: cdk.aws_lambda.IFunction;
  meteringAggregatorFn: cdk.aws_lambda.IFunction;
  quotaResetCheckerFn: cdk.aws_lambda.IFunction;
  websocketHeartbeatFn: cdk.aws_lambda.IFunction;
  webhookHealthCheckerFn: cdk.aws_lambda.IFunction;
  retentionCleanupFn: cdk.aws_lambda.IFunction;
  abuseDetectorFn: cdk.aws_lambda.IFunction;
  sesReputationReporterFn: cdk.aws_lambda.IFunction;
  storageRecalculatorFn: cdk.aws_lambda.IFunction;
  ipWarmingManagerFn: cdk.aws_lambda.IFunction;
  orgProvisionerFn: cdk.aws_lambda.IFunction;
  virusScannerFn: cdk.aws_lambda.IFunction;
  searchEnrichmentFn: cdk.aws_lambda.IFunction;
  dynamoDbTable: cdk.aws_dynamodb.ITable;
  opsAlertsTopic: sns.ITopic;
}

export class EventBridgeStack extends cdk.Stack {
  public readonly opsBus: events.EventBus;

  constructor(scope: Construct, id: string, props: EventBridgeStackProps) {
    super(scope, id, props);

    // ─── Custom Event Bus ───────────────────────────────────────────

    this.opsBus = new events.EventBus(this, 'OpsBus', {
      eventBusName: 'agentmail-ops',
      description: 'Operational lifecycle events for cross-service orchestration',
    });

    // Enable archiving for replay capability
    this.opsBus.archive('OpsArchive', {
      archiveName: 'agentmail-ops-archive',
      description: 'Archive of all ops bus events for replay',
      retention: cdk.Duration.days(90),
      eventPattern: {
        source: [{ prefix: 'agentmail.' }] as any[],
      },
    });

    // ─── Dead Letter Queues ─────────────────────────────────────────

    const opsRuleDlq = new sqs.Queue(this, 'OpsRuleDLQ', {
      queueName: 'agentmail-ops-rules-dlq',
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    const schedulerDlq = new sqs.Queue(this, 'SchedulerDLQ', {
      queueName: 'agentmail-scheduler-dlq',
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    const pipesDlq = new sqs.Queue(this, 'PipesDLQ', {
      queueName: 'agentmail-pipes-dlq',
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    // ─── Scheduler IAM Role ────────────────────────────────────────

    const schedulerRole = new iam.Role(this, 'SchedulerRole', {
      roleName: 'agentmail-eventbridge-scheduler-role',
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
      description: 'Role for EventBridge Scheduler to invoke Lambda targets',
    });

    // Grant invoke on all scheduled Lambda targets
    const scheduledFunctions = [
      props.domainVerificationPollerFn,
      props.meteringAggregatorFn,
      props.quotaResetCheckerFn,
      props.websocketHeartbeatFn,
      props.webhookHealthCheckerFn,
      props.retentionCleanupFn,
      props.abuseDetectorFn,
      props.sesReputationReporterFn,
      props.storageRecalculatorFn,
      props.ipWarmingManagerFn,
    ];

    for (const fn of scheduledFunctions) {
      fn.grantInvoke(schedulerRole);
    }

    // Grant DLQ send message
    opsRuleDlq.grantSendMessages(schedulerRole);
    schedulerDlq.grantSendMessages(schedulerRole);

    // ─── EventBridge Rules IAM ──────────────────────────────────────

    // EventBridge service role for invoking targets from rules
    // (Lambda targets are granted automatically by CDK when using
    //  targets.LambdaFunction, but SQS/SNS/Firehose need explicit grants)

    // ─── Ops Bus Rules ──────────────────────────────────────────────

    // org.created → provisioner
    new events.Rule(this, 'OrgCreatedProvisioningRule', {
      eventBus: this.opsBus,
      ruleName: 'org-created-provisioning',
      description: 'Provision new organization resources on signup',
      eventPattern: {
        source: ['agentmail.saas-platform'],
        detailType: ['OrganizationCreated'],
      },
      targets: [
        new targets.LambdaFunction(props.orgProvisionerFn, {
          deadLetterQueue: opsRuleDlq,
          retryAttempts: 3,
          maxEventAge: cdk.Duration.hours(1),
        }),
      ],
    });

    // org.tier_changed → quota updater
    new events.Rule(this, 'TierChangedQuotaRule', {
      eventBus: this.opsBus,
      ruleName: 'tier-changed-quota-update',
      description: 'Update org quotas when tier changes',
      eventPattern: {
        source: ['agentmail.billing-service'],
        detailType: ['TierChanged'],
      },
      targets: [
        new targets.LambdaFunction(props.orgProvisionerFn, {
          deadLetterQueue: opsRuleDlq,
          retryAttempts: 3,
          maxEventAge: cdk.Duration.hours(1),
        }),
      ],
    });

    // org.disabled → suspender
    new events.Rule(this, 'OrgDisabledSuspendRule', {
      eventBus: this.opsBus,
      ruleName: 'org-disabled-suspend',
      description: 'Suspend org resources on account deactivation',
      eventPattern: {
        source: ['agentmail.lifecycle-service'],
        detailType: ['OrganizationDisabled'],
      },
      targets: [
        new targets.LambdaFunction(props.orgProvisionerFn, {
          deadLetterQueue: opsRuleDlq,
          retryAttempts: 3,
          maxEventAge: cdk.Duration.hours(1),
        }),
      ],
    });

    // billing.payment_failed → notifier (high-value alert)
    new events.Rule(this, 'PaymentFailedHighValueRule', {
      eventBus: this.opsBus,
      ruleName: 'payment-failed-high-value-alert',
      description: 'Alert ops for high-value failed payments',
      eventPattern: {
        source: ['agentmail.stripe-webhook'],
        detailType: ['PaymentFailed'],
        detail: {
          amountDue: [{ numeric: ['>', 50000] }],
        },
      },
      targets: [
        new targets.SnsTopic(props.opsAlertsTopic),
      ],
    });

    // ses.reputation_alert (critical) → ops
    new events.Rule(this, 'ReputationAlertCriticalRule', {
      eventBus: this.opsBus,
      ruleName: 'reputation-alert-critical-ops',
      description: 'Page ops for critical SES reputation alerts',
      eventPattern: {
        source: ['agentmail.reputation-monitor'],
        detailType: ['ReputationAlert'],
        detail: {
          severity: ['critical'],
        },
      },
      targets: [
        new targets.SnsTopic(props.opsAlertsTopic),
      ],
    });

    // ─── Default Bus Rules (AWS Service Events) ─────────────────────

    // S3 → virus scanner
    new events.Rule(this, 'S3VirusScanRule', {
      ruleName: 'attachment-virus-scan-trigger',
      description: 'Trigger virus scanning on attachment upload',
      eventPattern: {
        source: ['aws.s3'],
        detailType: ['Object Created'],
        detail: {
          bucket: { name: ['agentmail-attachments'] },
          object: { key: [{ prefix: 'uploads/' }] },
        },
      },
      targets: [
        new targets.LambdaFunction(props.virusScannerFn, {
          deadLetterQueue: opsRuleDlq,
          retryAttempts: 2,
          maxEventAge: cdk.Duration.minutes(30),
        }),
      ],
    });

    // CloudWatch alarm state changes → SNS
    new events.Rule(this, 'AlarmRouterRule', {
      ruleName: 'production-alarm-router',
      description: 'Route agentmail CloudWatch alarms to ops channels',
      eventPattern: {
        source: ['aws.cloudwatch'],
        detailType: ['CloudWatch Alarm State Change'],
        detail: {
          alarmName: [{ prefix: 'agentmail-' }],
          state: { value: ['ALARM'] },
        },
      },
      targets: [
        new targets.SnsTopic(props.opsAlertsTopic),
      ],
    });

    // ─── Scheduler Schedules ────────────────────────────────────────
    // (See Section 2 for individual schedule definitions)
    // Each schedule is created as a scheduler.CfnSchedule with:
    //   - roleArn: schedulerRole.roleArn
    //   - deadLetterConfig: { arn: schedulerDlq.queueArn }
    //   - retryPolicy per schedule (see Section 6.2)

    this.createSchedules(schedulerRole, schedulerDlq, props);

    // ─── Monitoring ─────────────────────────────────────────────────

    this.createAlarms(opsRuleDlq, schedulerDlq, pipesDlq, props.opsAlertsTopic);
  }

  private createSchedules(
    schedulerRole: iam.Role,
    schedulerDlq: sqs.Queue,
    props: EventBridgeStackProps,
  ) {
    const schedules: Array<{
      name: string;
      description: string;
      expression: string;
      timezone?: string;
      flexibleMode: 'OFF' | 'FLEXIBLE';
      flexibleMinutes?: number;
      targetArn: string;
      maxRetries: number;
      maxAgeSeconds: number;
    }> = [
      {
        name: 'agentmail-domain-verification-poller',
        description: 'Poll SES for pending domain verification status',
        expression: 'rate(5 minutes)',
        flexibleMode: 'OFF',
        targetArn: props.domainVerificationPollerFn.functionArn,
        maxRetries: 2,
        maxAgeSeconds: 300,
      },
      {
        name: 'agentmail-metering-aggregator',
        description: 'Aggregate usage counters and submit BatchMeterUsage',
        expression: 'rate(1 hour)',
        flexibleMode: 'FLEXIBLE',
        flexibleMinutes: 5,
        targetArn: props.meteringAggregatorFn.functionArn,
        maxRetries: 3,
        maxAgeSeconds: 3600,
      },
      {
        name: 'agentmail-quota-reset-checker',
        description: 'Check for orgs needing monthly quota resets',
        expression: 'rate(1 hour)',
        flexibleMode: 'FLEXIBLE',
        flexibleMinutes: 10,
        targetArn: props.quotaResetCheckerFn.functionArn,
        maxRetries: 2,
        maxAgeSeconds: 3600,
      },
      {
        name: 'agentmail-websocket-heartbeat',
        description: 'Send pings to all WebSocket connections',
        expression: 'rate(1 minute)',
        flexibleMode: 'OFF',
        targetArn: props.websocketHeartbeatFn.functionArn,
        maxRetries: 0,
        maxAgeSeconds: 60,
      },
      {
        name: 'agentmail-webhook-health-checker',
        description: 'Check disabled webhooks and send re-enable notifications',
        expression: 'rate(6 hours)',
        flexibleMode: 'FLEXIBLE',
        flexibleMinutes: 15,
        targetArn: props.webhookHealthCheckerFn.functionArn,
        maxRetries: 2,
        maxAgeSeconds: 21600,
      },
      {
        name: 'agentmail-retention-cleanup',
        description: 'Delete expired messages per org retention policy',
        expression: 'cron(0 3 * * ? *)',
        timezone: 'UTC',
        flexibleMode: 'FLEXIBLE',
        flexibleMinutes: 30,
        targetArn: props.retentionCleanupFn.functionArn,
        maxRetries: 2,
        maxAgeSeconds: 86400,
      },
      {
        name: 'agentmail-abuse-detector',
        description: 'Scan for abuse patterns',
        expression: 'cron(0 4 * * ? *)',
        timezone: 'UTC',
        flexibleMode: 'FLEXIBLE',
        flexibleMinutes: 30,
        targetArn: props.abuseDetectorFn.functionArn,
        maxRetries: 2,
        maxAgeSeconds: 86400,
      },
      {
        name: 'agentmail-ses-reputation-reporter',
        description: 'Compile per-org SES reputation metrics',
        expression: 'cron(0 5 * * ? *)',
        timezone: 'UTC',
        flexibleMode: 'FLEXIBLE',
        flexibleMinutes: 15,
        targetArn: props.sesReputationReporterFn.functionArn,
        maxRetries: 2,
        maxAgeSeconds: 86400,
      },
      {
        name: 'agentmail-storage-recalculator',
        description: 'Recalculate per-org storage usage from S3',
        expression: 'cron(0 2 ? * SUN *)',
        timezone: 'UTC',
        flexibleMode: 'FLEXIBLE',
        flexibleMinutes: 60,
        targetArn: props.storageRecalculatorFn.functionArn,
        maxRetries: 2,
        maxAgeSeconds: 86400,
      },
      {
        name: 'agentmail-ip-warming-manager',
        description: 'Manage dedicated IP warming schedules',
        expression: 'rate(5 minutes)',
        flexibleMode: 'OFF',
        targetArn: props.ipWarmingManagerFn.functionArn,
        maxRetries: 2,
        maxAgeSeconds: 300,
      },
    ];

    for (const sched of schedules) {
      new scheduler.CfnSchedule(this, sched.name, {
        name: sched.name,
        description: sched.description,
        scheduleExpression: sched.expression,
        scheduleExpressionTimezone: sched.timezone,
        flexibleTimeWindow: {
          mode: sched.flexibleMode,
          ...(sched.flexibleMinutes && {
            maximumWindowInMinutes: sched.flexibleMinutes,
          }),
        },
        target: {
          arn: sched.targetArn,
          roleArn: schedulerRole.roleArn,
          retryPolicy: {
            maximumRetryAttempts: sched.maxRetries,
            maximumEventAgeInSeconds: sched.maxAgeSeconds,
          },
          deadLetterConfig: {
            arn: schedulerDlq.queueArn,
          },
        },
        state: 'ENABLED',
      });
    }
  }

  private createAlarms(
    opsRuleDlq: sqs.Queue,
    schedulerDlq: sqs.Queue,
    pipesDlq: sqs.Queue,
    opsAlertsTopic: sns.ITopic,
  ) {
    const dlqs = [
      { queue: opsRuleDlq, threshold: 10 },
      { queue: schedulerDlq, threshold: 5 },
      { queue: pipesDlq, threshold: 20 },
    ];

    for (const { queue, threshold } of dlqs) {
      new cloudwatch.Alarm(this, `${queue.node.id}DepthAlarm`, {
        alarmName: `agentmail-dlq-depth-${queue.queueName}`,
        metric: queue.metricApproximateNumberOfMessagesVisible({
          statistic: 'Maximum',
          period: cdk.Duration.minutes(5),
        }),
        threshold,
        evaluationPeriods: 2,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        actionsEnabled: true,
      });
    }

    // EventBridge FailedInvocations alarm
    new cloudwatch.Alarm(this, 'OpsBusFailedInvocations', {
      alarmName: 'agentmail-ops-bus-failed-invocations',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/Events',
        metricName: 'FailedInvocations',
        dimensionsMap: { EventBusName: 'agentmail-ops' },
        statistic: 'Sum',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 0,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
  }
}
```

### 7.2 IAM Roles

**EventBridge Scheduler Role:**

```json
{
  "RoleName": "agentmail-eventbridge-scheduler-role",
  "AssumeRolePolicyDocument": {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": { "Service": "scheduler.amazonaws.com" },
        "Action": "sts:AssumeRole"
      }
    ]
  },
  "Policies": [
    {
      "PolicyName": "InvokeLambdaTargets",
      "PolicyDocument": {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": [
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-domain-verification-poller",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-metering-aggregator",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-quota-reset-checker",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-websocket-heartbeat",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-webhook-health-checker",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-retention-cleanup",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-abuse-detector",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-ses-reputation-reporter",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-storage-recalculator",
              "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-ip-warming-manager"
            ]
          },
          {
            "Effect": "Allow",
            "Action": "sqs:SendMessage",
            "Resource": "arn:aws:sqs:us-east-1:ACCOUNT:agentmail-scheduler-dlq"
          }
        ]
      }
    }
  ]
}
```

**EventBridge Pipes Role (Search Indexing):**

```json
{
  "RoleName": "agentmail-search-index-pipe-role",
  "AssumeRolePolicyDocument": {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": { "Service": "pipes.amazonaws.com" },
        "Action": "sts:AssumeRole"
      }
    ]
  },
  "Policies": [
    {
      "PolicyName": "PipeSourceAccess",
      "PolicyDocument": {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": [
              "dynamodb:DescribeStream",
              "dynamodb:GetRecords",
              "dynamodb:GetShardIterator",
              "dynamodb:ListStreams"
            ],
            "Resource": "arn:aws:dynamodb:us-east-1:ACCOUNT:table/agentmail/stream/*"
          }
        ]
      }
    },
    {
      "PolicyName": "PipeEnrichmentAccess",
      "PolicyDocument": {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-search-enrichment"
          }
        ]
      }
    },
    {
      "PolicyName": "PipeTargetAccess",
      "PolicyDocument": {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": "osis:Ingest",
            "Resource": "arn:aws:osis:us-east-1:ACCOUNT:pipeline/agentmail-search-pipeline"
          }
        ]
      }
    },
    {
      "PolicyName": "PipeDLQAccess",
      "PolicyDocument": {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": "sqs:SendMessage",
            "Resource": "arn:aws:sqs:us-east-1:ACCOUNT:agentmail-pipes-dlq"
          }
        ]
      }
    }
  ]
}
```

**EventBridge Rules Role (for non-Lambda targets on ops bus):**

```json
{
  "RoleName": "agentmail-eventbridge-rules-role",
  "AssumeRolePolicyDocument": {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": { "Service": "events.amazonaws.com" },
        "Action": "sts:AssumeRole"
      }
    ]
  },
  "Policies": [
    {
      "PolicyName": "TargetAccess",
      "PolicyDocument": {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": "sqs:SendMessage",
            "Resource": [
              "arn:aws:sqs:us-east-1:ACCOUNT:agentmail-email-outbound",
              "arn:aws:sqs:us-east-1:ACCOUNT:agentmail-ops-rules-dlq"
            ]
          },
          {
            "Effect": "Allow",
            "Action": "sns:Publish",
            "Resource": [
              "arn:aws:sns:us-east-1:ACCOUNT:agentmail-ops-alerts",
              "arn:aws:sns:us-east-1:ACCOUNT:agentmail-pagerduty",
              "arn:aws:sns:us-east-1:ACCOUNT:agentmail-slack-alerts"
            ]
          },
          {
            "Effect": "Allow",
            "Action": "firehose:PutRecord",
            "Resource": [
              "arn:aws:firehose:us-east-1:ACCOUNT:deliverystream/agentmail-analytics",
              "arn:aws:firehose:us-east-1:ACCOUNT:deliverystream/agentmail-audit-log"
            ]
          },
          {
            "Effect": "Allow",
            "Action": "states:StartExecution",
            "Resource": "arn:aws:states:us-east-1:ACCOUNT:stateMachine:agentmail-org-data-cleanup"
          }
        ]
      }
    }
  ]
}
```

---

## Architecture Diagram

```
                    ┌─────────────────────────────────────────────────────┐
                    │              EVENTBRIDGE LAYER                      │
                    │                                                     │
  ┌──────────┐     │  ┌─────────────────┐    ┌──────────────────────┐   │
  │ Scheduler │─────│──│ Scheduled Rules │    │ Custom Bus           │   │
  │           │     │  │                 │    │ (agentmail-ops)      │   │
  │ rate(5m)  │─────│──│→ domain-poller  │    │                      │   │
  │ rate(1h)  │─────│──│→ metering-agg   │    │ ┌──────────────────┐ │   │
  │ rate(1h)  │─────│──│→ quota-reset    │    │ │ org.created      │─│───│──→ Lambda: org-provisioner
  │ rate(1m)  │─────│──│→ ws-heartbeat   │    │ │ org.tier_changed │─│───│──→ Lambda: quota-updater
  │ rate(6h)  │─────│──│→ webhook-health │    │ │ org.disabled     │─│───│──→ Lambda: org-suspender
  │ cron(3am) │─────│──│→ retention      │    │ │ org.deleted      │─│───│──→ Step Functions: cleanup
  │ cron(4am) │─────│──│→ abuse-detect   │    │ │ quota.warning    │─│───│──→ Lambda: notification
  │ cron(5am) │─────│──│→ ses-reputation │    │ │ quota.exceeded   │─│───│──→ Lambda: enforcer
  │ cron(Sun) │─────│──│→ storage-recalc │    │ │ payment.failed   │─│───│──→ Lambda: dunning
  │ rate(5m)  │─────│──│→ ip-warming     │    │ │ ses.reputation   │─│───│──→ Lambda: throttler
  │           │     │  └─────────────────┘    │ │ marketplace.*    │─│───│──→ Lambda: mkt-handler
  └──────────┘     │                          │ └──────────────────┘ │   │
                    │                          └──────────────────────┘   │
                    │                                                     │
                    │  ┌──────────────────────────────────────────────┐   │
                    │  │ Default Bus (AWS Service Events)             │   │
                    │  │                                              │   │
                    │  │ aws.s3 (Object Created) ──→ virus-scanner   │   │
                    │  │ aws.cloudwatch (Alarm) ──→ SNS (PagerDuty)  │   │
                    │  │ aws.dynamodb (CloudTrail) ──→ audit-log     │   │
                    │  └──────────────────────────────────────────────┘   │
                    │                                                     │
                    │  ┌──────────────────────────────────────────────┐   │
                    │  │ EventBridge Pipes                            │   │
                    │  │                                              │   │
                    │  │ DynamoDB Stream ──filter──enrich──→ OpenSearch│   │
                    │  │ SQS (AI queue) ──filter──→ Step Functions    │   │
                    │  └──────────────────────────────────────────────┘   │
                    │                                                     │
                    │  ┌──────────────────────────────────────────────┐   │
                    │  │ Error Handling                               │   │
                    │  │                                              │   │
                    │  │ Rules DLQ ──→ S3 archive + alarm             │   │
                    │  │ Scheduler DLQ ──→ S3 archive + alarm         │   │
                    │  │ Pipes DLQ ──→ S3 archive + alarm             │   │
                    │  └──────────────────────────────────────────────┘   │
                    └─────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────────┐
                    │              KINESIS LAYER (primary event bus)      │
                    │                                                     │
                    │  agentmail-events (4 shards, ON_DEMAND)            │
                    │  ├── webhook-pipeline (enhanced fan-out)           │
                    │  ├── websocket-pipeline (enhanced fan-out)         │
                    │  ├── analytics-pipeline (enhanced fan-out)         │
                    │  └── event-archive (enhanced fan-out → S3)         │
                    └─────────────────────────────────────────────────────┘
```

**Relationship between the two layers:** Kinesis handles the hot path (email events at 100K+/min with ordering and replay). EventBridge handles the control plane (schedules, lifecycle orchestration, AWS service reactions). Some EventBridge-triggered Lambdas write events into Kinesis when the result is customer-facing (e.g., domain verified, quota warning). The two systems are complementary, not competing.

---

## Cost Estimate

| Component | Monthly Cost |
|-----------|-------------|
| EventBridge custom bus events (~500K events/mo) | ~$0.50 |
| EventBridge Scheduler (10 schedules, ~250K invocations/mo) | ~$0.25 |
| EventBridge Pipes (DynamoDB stream processing) | ~$5.00 |
| SQS DLQs (3 queues, minimal traffic) | ~$0.10 |
| Lambda invocations (scheduled + rule targets) | ~$50.00 |
| **Total EventBridge layer** | **~$56/mo** |

The EventBridge layer costs roughly 2% of the Kinesis layer (~$3,000/mo). This confirms the architecture split: EventBridge for low-volume orchestration, Kinesis for high-volume event streaming.
