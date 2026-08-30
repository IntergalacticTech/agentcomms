# Load Testing and Capacity Planning

AgentMail's load testing strategy validates that the platform meets its performance SLOs under realistic traffic patterns, identifies bottlenecks before they affect customers, and provides data for capacity planning decisions. Every service limit, auto-scaling threshold, and performance benchmark is measured -- not assumed.

Load tests run in a dedicated staging environment that mirrors production infrastructure (same CDK stacks, same DynamoDB on-demand tables, same Lambda configurations). The staging environment uses a separate SES configuration set with the SES mailbox simulator to avoid affecting deliverability reputation.

---

## Table of Contents

- [Performance Targets (SLOs)](#performance-targets-slos)
- [Load Testing Framework](#load-testing-framework)
- [Test Scenarios](#test-scenarios)
- [Capacity Planning](#capacity-planning)
- [Performance Benchmarks](#performance-benchmarks)
- [Auto-Scaling Triggers](#auto-scaling-triggers)
- [CI/CD Integration](#cicd-integration)
- [Cost of Load Testing](#cost-of-load-testing)

---

## Performance Targets (SLOs)

These SLOs define the performance contract between AgentMail and its customers. Every load test scenario asserts against these targets. Any SLO violation in staging blocks promotion to production.

| Metric | Target | Measurement | Alert Threshold |
|--------|--------|-------------|-----------------|
| API response time (P50) | <50ms | API Gateway access logs | >75ms for 5 min |
| API response time (P99) | <200ms | API Gateway access logs | >300ms for 5 min |
| Email send latency | <2 seconds (API call to SES accept) | Custom metric `AgentMail/Email/SendLatency` | >3s for 5 min |
| Inbound processing time | <3 seconds (SES receive to DynamoDB write) | Custom metric `AgentMail/Email/InboundProcessingTime` | >5s for 5 min |
| Webhook delivery time | <5 seconds (event to HTTP POST) | Custom metric `AgentMail/Webhooks/DeliveryLatency` | >8s for 5 min |
| WebSocket event delivery | <1 second (event to client push) | Custom metric `AgentMail/WebSocket/EventLatency` | >2s for 5 min |
| Search query time (P99) | <500ms | OpenSearch metrics | >750ms for 5 min |
| AI processing time (P99) | <30 seconds (Step Functions) | Custom metric `AgentMail/AI/ProcessingTime` | >45s for 5 min |
| Uptime | 99.95% (21.9 min downtime/month) | Route 53 health checks | Any health check failure |
| Error rate | <0.1% of requests | API Gateway 5xx metric | >0.5% for 5 min |

### SLO Measurement Implementation

SLOs are tracked via CloudWatch Metrics Insights queries that run every minute. A composite alarm fires when any two SLOs breach simultaneously, escalating to PagerDuty.

```sql
-- CloudWatch Metrics Insights: P99 API latency over 5-minute windows
SELECT AVG(latency) as avg_latency,
       PERCENTILE(latency, 99) as p99_latency
FROM SCHEMA("AWS/ApiGateway", ApiId, Stage)
WHERE ApiId = 'agentmail-rest-api' AND Stage = 'v1'
GROUP BY BIN(5m)
```

---

## Load Testing Framework

### Primary Tool: Artillery (Node.js)

Artillery is the primary load testing tool, chosen for:

- **Native HTTP + WebSocket support** -- AgentMail uses both REST API and WebSocket APIs, and Artillery tests both in a single scenario file
- **YAML config (declarative)** -- Test scenarios are version-controlled alongside CDK infrastructure code, reviewable in PRs
- **Plugin ecosystem** -- `artillery-plugin-publish-metrics` publishes results directly to CloudWatch for unified dashboarding
- **CI/CD integration** -- Exit codes based on threshold assertions, compatible with GitHub Actions
- **AWS Lambda distributed mode** -- `artillery run --platform aws:lambda` distributes load generation across multiple Lambda functions in the target region, eliminating client-side bottlenecks for high-concurrency tests

### Secondary Tool: k6 (for scripted scenarios)

k6 is used for scenarios requiring complex JavaScript logic (conditional flows, response-driven branching, custom protocol handling). The IMAP/SMTP protocol tests use k6 with the `k6/x/net` extension.

### Installation and Setup

```bash
# Install Artillery globally
npm install -g artillery@latest

# Install CloudWatch metrics plugin
npm install -g artillery-plugin-publish-metrics

# Install k6 (macOS)
brew install k6

# Verify installations
artillery version
k6 version
```

### Project Structure

```
load-tests/
  artillery/
    config/
      base.yml              # Shared configuration (target, plugins, phases)
      environments/
        staging.yml          # Staging-specific overrides
        loadtest.yml         # Dedicated load-test env overrides
    scenarios/
      api-baseline.yml       # Scenario 1
      inbox-burst.yml        # Scenario 2
      inbound-storm.yml      # Scenario 3
      websocket-fanout.yml   # Scenario 4
      free-tier-abuse.yml    # Scenario 5
      peak-load.yml          # Scenario 6
    processors/
      auth.js                # API key generation and request signing
      websocket-handler.js   # WebSocket message handling
      metrics-collector.js   # Custom metric collection
    data/
      test-emails.csv        # Sample email data for inbound tests
      user-profiles.csv      # Free/Pro/Business user profiles
  k6/
    imap-smtp-test.js        # IMAP/SMTP protocol tests
  results/
    .gitkeep                 # Results stored in S3, local for development
  package.json
  run-load-tests.sh          # Orchestration script
```

### Base Configuration

```yaml
# load-tests/artillery/config/base.yml
config:
  environments:
    staging:
      target: "https://api.staging.agentmail.aws"
      phases:
        - duration: 60
          arrivalRate: 1
          name: "Warm up"
    loadtest:
      target: "https://api.loadtest.agentmail.aws"
  plugins:
    publish-metrics:
      - type: cloudwatch
        region: "us-east-1"
        namespace: "AgentMail/LoadTests"
        dimensions:
          - name: "Environment"
            value: "{{ $environment }}"
          - name: "Scenario"
            value: "{{ $scenario }}"
  defaults:
    headers:
      Content-Type: "application/json"
      User-Agent: "AgentMail-LoadTest/1.0"
  processor: "../processors/auth.js"
```

### Auth Processor

```javascript
// load-tests/artillery/processors/auth.js
'use strict';

const crypto = require('crypto');

// API keys for load test accounts (stored in SSM Parameter Store, injected via env)
const API_KEYS = {
  free: process.env.LOADTEST_FREE_API_KEY,
  pro: process.env.LOADTEST_PRO_API_KEY,
  business: process.env.LOADTEST_BUSINESS_API_KEY,
  scale: process.env.LOADTEST_SCALE_API_KEY,
};

const TEST_INBOXES = {};

module.exports = {
  setApiKey,
  setRandomTierApiKey,
  generateInboxName,
  captureInboxId,
  captureMessageId,
};

function setApiKey(requestParams, context, ee, next) {
  const tier = context.vars.tier || 'pro';
  requestParams.headers = requestParams.headers || {};
  requestParams.headers['x-api-key'] = API_KEYS[tier];
  return next();
}

function setRandomTierApiKey(requestParams, context, ee, next) {
  // Weighted random: 60% pro, 25% business, 10% scale, 5% free
  const rand = Math.random();
  let tier;
  if (rand < 0.6) tier = 'pro';
  else if (rand < 0.85) tier = 'business';
  else if (rand < 0.95) tier = 'scale';
  else tier = 'free';

  context.vars.tier = tier;
  requestParams.headers = requestParams.headers || {};
  requestParams.headers['x-api-key'] = API_KEYS[tier];
  return next();
}

function generateInboxName(requestParams, context, ee, next) {
  const id = crypto.randomBytes(8).toString('hex');
  context.vars.inboxName = `loadtest-${id}`;
  context.vars.inboxAddress = `loadtest-${id}@loadtest.agentmail.dev`;
  return next();
}

function captureInboxId(requestParams, response, context, ee, next) {
  if (response.statusCode === 201) {
    const body = JSON.parse(response.body);
    context.vars.inboxId = body.data.id;
    TEST_INBOXES[context.vars.inboxId] = true;
  }
  return next();
}

function captureMessageId(requestParams, response, context, ee, next) {
  if (response.statusCode === 200 || response.statusCode === 201) {
    const body = JSON.parse(response.body);
    if (body.data && body.data.id) {
      context.vars.messageId = body.data.id;
    }
  }
  return next();
}
```

---

## Test Scenarios

### Scenario 1: API Baseline

Validates that the API meets P99 latency and error rate SLOs under normal production-like traffic. This test runs on every staging deploy.

```yaml
# load-tests/artillery/scenarios/api-baseline.yml
config:
  target: "https://api.staging.agentmail.aws"
  phases:
    - duration: 300       # 5 minutes ramp-up
      arrivalRate: 1
      rampTo: 100
      name: "Ramp to 100 VUs"
    - duration: 600       # 10 minutes sustained
      arrivalRate: 100
      name: "Sustain 100 VUs"
    - duration: 120       # 2 minutes cool-down
      arrivalRate: 100
      rampTo: 0
      name: "Cool down"
  processor: "../processors/auth.js"
  plugins:
    publish-metrics:
      - type: cloudwatch
        region: "us-east-1"
        namespace: "AgentMail/LoadTests"
        dimensions:
          - name: "Scenario"
            value: "api-baseline"
  ensure:
    thresholds:
      - http.response_time.p99: 200       # P99 < 200ms
      - http.response_time.p50: 50        # P50 < 50ms
      - http.codes.5xx: 0                 # Zero 5xx errors during test
    conditions:
      - expression: "http.codes.4xx / http.responses < 0.01"
        strict: false                      # 4xx from intentional 404s in mix
  defaults:
    headers:
      Content-Type: "application/json"
  variables:
    tier: "pro"

scenarios:
  # 60% Read operations
  - name: "List inboxes"
    weight: 20
    flow:
      - function: "setApiKey"
      - get:
          url: "/v1/inboxes?limit=20"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"

  - name: "Get inbox details"
    weight: 10
    flow:
      - function: "setApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
      - get:
          url: "/v1/inboxes/{{ inboxId }}"

  - name: "List messages"
    weight: 20
    flow:
      - function: "setApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
      - get:
          url: "/v1/inboxes/{{ inboxId }}/messages?limit=50"

  - name: "Get specific message"
    weight: 10
    flow:
      - function: "setApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
      - get:
          url: "/v1/inboxes/{{ inboxId }}/messages?limit=1"
          capture:
            - json: "$.data[0].id"
              as: "messageId"
      - get:
          url: "/v1/inboxes/{{ inboxId }}/messages/{{ messageId }}"

  # 30% Write operations
  - name: "Send message"
    weight: 20
    flow:
      - function: "setApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
      - post:
          url: "/v1/inboxes/{{ inboxId }}/messages"
          json:
            to: "loadtest-recipient@simulator.amazonses.com"
            subject: "Load test {{ $randomString(10) }}"
            body: "This is a load test message sent at {{ $timestamp }}."
          expect:
            - statusCode: 201

  - name: "Create and delete inbox"
    weight: 5
    flow:
      - function: "setApiKey"
      - function: "generateInboxName"
      - post:
          url: "/v1/inboxes"
          json:
            name: "{{ inboxName }}"
          afterResponse: "captureInboxId"
          expect:
            - statusCode: 201
      - delete:
          url: "/v1/inboxes/{{ inboxId }}"
          expect:
            - statusCode: 204

  - name: "Update inbox settings"
    weight: 5
    flow:
      - function: "setApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
      - patch:
          url: "/v1/inboxes/{{ inboxId }}"
          json:
            autoReply: false
          expect:
            - statusCode: 200

  # 10% Search operations
  - name: "Search messages"
    weight: 10
    flow:
      - function: "setApiKey"
      - post:
          url: "/v1/search"
          json:
            query: "invoice payment"
            limit: 20
          expect:
            - statusCode: 200
```

**Expected results:**

| Metric | Expected | Fail Threshold |
|--------|----------|---------------|
| P50 response time | <40ms | >50ms |
| P99 response time | <150ms | >200ms |
| Throughput | >500 req/sec | <400 req/sec |
| Error rate (5xx) | 0% | >0.1% |
| Success rate | >99.9% | <99.5% |

**What to monitor during test:**

- CloudWatch: API Gateway latency, Lambda duration, Lambda concurrent executions, Lambda errors
- CloudWatch: DynamoDB consumed read/write capacity, throttle events
- CloudWatch: ElastiCache Redis engine CPU, current connections, cache hit rate
- X-Ray: Service map for latency distribution across Lambda -> DynamoDB -> Redis
- Custom dashboard: Per-endpoint latency breakdown

---

### Scenario 2: Inbox Creation Burst

Validates that the platform handles rapid inbox provisioning without DynamoDB throttling or Lambda cold start cascades. This simulates a customer onboarding scenario where an AI agent creates many inboxes programmatically.

```yaml
# load-tests/artillery/scenarios/inbox-burst.yml
config:
  target: "https://api.staging.agentmail.aws"
  phases:
    - duration: 60        # 1000 requests in 60 seconds = ~17/sec
      arrivalRate: 17
      name: "Burst inbox creation"
  processor: "../processors/auth.js"
  plugins:
    publish-metrics:
      - type: cloudwatch
        region: "us-east-1"
        namespace: "AgentMail/LoadTests"
        dimensions:
          - name: "Scenario"
            value: "inbox-burst"
  ensure:
    thresholds:
      - http.response_time.p99: 500       # Allow higher latency during burst
      - http.codes.429: 0                 # No throttling for Scale tier
  defaults:
    headers:
      Content-Type: "application/json"
  variables:
    tier: "scale"

scenarios:
  - name: "Create inbox burst"
    flow:
      - function: "setApiKey"
      - function: "generateInboxName"
      - post:
          url: "/v1/inboxes"
          json:
            name: "{{ inboxName }}"
            forwardTo: "loadtest-collector@simulator.amazonses.com"
            webhookUrl: "https://loadtest-webhook-sink.agentmail.aws/collect"
          afterResponse: "captureInboxId"
          expect:
            - statusCode: 201
      # Verify inbox exists
      - get:
          url: "/v1/inboxes/{{ inboxId }}"
          expect:
            - statusCode: 200
            - hasProperty: "data.id"
      # Clean up
      - think: 2
      - delete:
          url: "/v1/inboxes/{{ inboxId }}"
          expect:
            - statusCode: 204
```

**Expected results:**

| Metric | Expected | Fail Threshold |
|--------|----------|---------------|
| Successful creations | 1000/1000 (100%) | <990 (99%) |
| P99 creation latency | <200ms | >500ms |
| DynamoDB throttle events | 0 | >0 |
| Lambda cold starts | <50 | >100 |
| 429 responses | 0 | >0 (Scale tier should not be throttled) |

**What to monitor during test:**

- CloudWatch: DynamoDB `WriteThrottleEvents` and `ConsumedWriteCapacityUnits` on the main table
- CloudWatch: Lambda `ConcurrentExecutions` and `Init Duration` (cold starts)
- CloudWatch: DynamoDB `SuccessfulRequestLatency` for `PutItem` operations
- X-Ray: Trace waterfall for inbox creation flow (Lambda -> DynamoDB PutItem -> EventBridge PutEvents)

---

### Scenario 3: Inbound Email Storm

Simulates a high volume of inbound emails hitting the SES -> S3 -> Lambda processing pipeline. This tests the entire inbound flow: SES receipt, S3 storage, Lambda MIME parsing, DynamoDB writes, Kinesis event publishing, webhook delivery, and OpenSearch indexing.

Since Artillery cannot directly invoke SES inbound processing, this scenario uses a helper Lambda that writes test emails to the S3 inbound bucket with the correct SES notification format, triggering the same processing pipeline.

```yaml
# load-tests/artillery/scenarios/inbound-storm.yml
config:
  target: "https://api.staging.agentmail.aws"
  phases:
    - duration: 60        # 1 minute warm-up
      arrivalRate: 10
      name: "Warm up"
    - duration: 300       # 5 minutes at ~33/sec = 10,000 emails
      arrivalRate: 33
      name: "Inbound storm"
  processor: "../processors/auth.js"
  plugins:
    publish-metrics:
      - type: cloudwatch
        region: "us-east-1"
        namespace: "AgentMail/LoadTests"
        dimensions:
          - name: "Scenario"
            value: "inbound-storm"
  ensure:
    thresholds:
      - http.response_time.p99: 1000
  defaults:
    headers:
      Content-Type: "application/json"
  variables:
    tier: "scale"

scenarios:
  - name: "Simulate inbound email"
    flow:
      - function: "setApiKey"
      # Use the load test helper endpoint that injects emails into the inbound pipeline
      - post:
          url: "/v1/internal/loadtest/simulate-inbound"
          json:
            from: "sender-{{ $randomString(6) }}@loadtest-external.example.com"
            to: "loadtest-inbox-{{ $randomInt(1, 100) }}@loadtest.agentmail.dev"
            subject: "Inbound storm test {{ $timestamp }}"
            bodyText: "This is a simulated inbound email for load testing. Unique ID: {{ $randomString(20) }}"
            bodyHtml: "<p>This is a simulated inbound email for load testing.</p><p>Unique ID: {{ $randomString(20) }}</p>"
            headers:
              Message-ID: "<loadtest-{{ $randomString(16) }}@loadtest-external.example.com>"
              Date: "{{ $timestamp }}"
          expect:
            - statusCode: 202
```

**Companion verification script:**

```bash
#!/bin/bash
# load-tests/verify-inbound-storm.sh
# Run after the inbound storm scenario completes to verify end-to-end processing

REGION="us-east-1"
NAMESPACE="AgentMail/LoadTests"
START_TIME=$(date -u -v-10M +%Y-%m-%dT%H:%M:%S)  # 10 minutes ago
END_TIME=$(date -u +%Y-%m-%dT%H:%M:%S)

echo "=== Inbound Storm Verification ==="

# 1. Check total emails processed
PROCESSED=$(aws cloudwatch get-metric-statistics \
  --namespace "AgentMail/Email" \
  --metric-name "InboundEmailsProcessed" \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --period 300 \
  --statistics Sum \
  --region "$REGION" \
  --query 'Datapoints[0].Sum' --output text)
echo "Emails processed: $PROCESSED / 10000 expected"

# 2. Check processing latency
P99_LATENCY=$(aws cloudwatch get-metric-statistics \
  --namespace "AgentMail/Email" \
  --metric-name "InboundProcessingTime" \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --period 300 \
  --extended-statistics p99 \
  --region "$REGION" \
  --query 'Datapoints[0].ExtendedStatistics.p99' --output text)
echo "P99 processing latency: ${P99_LATENCY}ms (target: <3000ms)"

# 3. Check webhook deliveries
WEBHOOKS=$(aws cloudwatch get-metric-statistics \
  --namespace "AgentMail/Webhooks" \
  --metric-name "DeliverySuccess" \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --period 300 \
  --statistics Sum \
  --region "$REGION" \
  --query 'Datapoints[0].Sum' --output text)
echo "Webhook deliveries: $WEBHOOKS"

# 4. Check DLQ depth (should be 0)
DLQ_DEPTH=$(aws sqs get-queue-attributes \
  --queue-url "https://sqs.${REGION}.amazonaws.com/ACCOUNT_ID/agentmail-inbound-dlq" \
  --attribute-names ApproximateNumberOfMessagesVisible \
  --region "$REGION" \
  --query 'Attributes.ApproximateNumberOfMessagesVisible' --output text)
echo "DLQ messages: $DLQ_DEPTH (should be 0)"

# 5. Check OpenSearch indexing lag
SEARCH_COUNT=$(curl -s "https://search.staging.agentmail.aws/_count" \
  -H "Content-Type: application/json" \
  -d '{"query":{"range":{"indexed_at":{"gte":"'$START_TIME'"}}}}' | jq '.count')
echo "OpenSearch indexed: $SEARCH_COUNT (should match processed count within 60s)"

# Pass/fail
if [ "$DLQ_DEPTH" -gt 0 ]; then
  echo "FAIL: Messages in DLQ"
  exit 1
fi
echo "PASS: All checks passed"
```

**Expected results:**

| Metric | Expected | Fail Threshold |
|--------|----------|---------------|
| Emails processed | 10,000 (100%) | <9,900 (99%) |
| P99 processing latency | <3s | >5s |
| Webhook deliveries | 10,000 | <9,900 |
| DLQ depth | 0 | >0 |
| OpenSearch indexed (within 60s) | 10,000 | <9,500 |
| Lambda errors | 0 | >10 |
| Kinesis IteratorAge | <5s | >30s |

**What to monitor during test:**

- CloudWatch: Lambda `InboundProcessor` duration, errors, throttles, concurrent executions
- CloudWatch: DynamoDB consumed capacity on message writes
- CloudWatch: Kinesis `GetRecords.IteratorAgeMilliseconds` (processing lag)
- CloudWatch: SQS DLQ `ApproximateNumberOfMessagesVisible`
- CloudWatch: OpenSearch `IndexingRate` and `SearchLatency`
- Custom metric: End-to-end latency from simulated SES notification to DynamoDB write confirmation

---

### Scenario 4: WebSocket Fan-Out

Tests the real-time event delivery path: events published to Kinesis are consumed by the WebSocket fan-out Lambda, which pushes them to all connected clients subscribed to the relevant channel. This scenario measures message delivery latency and loss rate under high connection counts.

```yaml
# load-tests/artillery/scenarios/websocket-fanout.yml
config:
  target: "wss://ws.staging.agentmail.aws/v1"
  phases:
    - duration: 60        # Establish connections over 60 seconds
      arrivalRate: 17     # ~1000 connections over 60s
      name: "Connect clients"
    - duration: 300       # Hold connections for 5 minutes
      arrivalRate: 0      # No new connections, just keep existing ones alive
      name: "Sustain and measure"
  processor: "../processors/websocket-handler.js"
  plugins:
    publish-metrics:
      - type: cloudwatch
        region: "us-east-1"
        namespace: "AgentMail/LoadTests"
        dimensions:
          - name: "Scenario"
            value: "websocket-fanout"
  ws:
    # Send ping every 30 seconds to keep connections alive
    pingInterval: 30
  ensure:
    thresholds:
      - websocket.messages_received: 1    # At least some messages received
  defaults:
    headers:
      x-api-key: "{{ $processEnvironment.LOADTEST_SCALE_API_KEY }}"

scenarios:
  - name: "WebSocket subscriber"
    engine: ws
    flow:
      # Connect and authenticate
      - send:
          channel: "message"
          payload:
            action: "subscribe"
            channels:
              - "inbox:loadtest-inbox-{{ $loopIndex % 100 }}"
      # Wait for subscription confirmation
      - think: 2
      # Listen for events for the duration of the test
      # The websocket-handler.js processor tracks received messages
      # and calculates delivery latency
      - think: 300
      # Unsubscribe before disconnect
      - send:
          channel: "message"
          payload:
            action: "unsubscribe"
            channels:
              - "inbox:loadtest-inbox-{{ $loopIndex % 100 }}"
```

**WebSocket handler processor:**

```javascript
// load-tests/artillery/processors/websocket-handler.js
'use strict';

const receivedMessages = new Map();
const deliveryLatencies = [];

module.exports = {
  trackMessage,
  reportMetrics,
};

function trackMessage(context, ee, next) {
  // Override the WebSocket message handler to track delivery latency
  const originalOnMessage = context.ws.onmessage;
  context.ws.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'event' && data.payload) {
        const eventTimestamp = new Date(data.payload.timestamp).getTime();
        const receiveTimestamp = Date.now();
        const latency = receiveTimestamp - eventTimestamp;

        deliveryLatencies.push(latency);

        // Track unique message IDs for loss calculation
        if (data.payload.eventId) {
          receivedMessages.set(data.payload.eventId, true);
        }

        // Emit custom metric
        ee.emit('customStat', {
          stat: 'websocket.delivery_latency_ms',
          value: latency,
        });
      }
    } catch (e) {
      // Ignore non-JSON messages (pings, etc.)
    }

    if (originalOnMessage) {
      originalOnMessage.call(this, event);
    }
  };
  return next();
}

function reportMetrics(context, ee, next) {
  if (deliveryLatencies.length > 0) {
    deliveryLatencies.sort((a, b) => a - b);
    const p50 = deliveryLatencies[Math.floor(deliveryLatencies.length * 0.5)];
    const p99 = deliveryLatencies[Math.floor(deliveryLatencies.length * 0.99)];
    console.log(`WebSocket delivery latency - P50: ${p50}ms, P99: ${p99}ms`);
    console.log(`Total messages received: ${receivedMessages.size}`);
  }
  return next();
}
```

**Companion event generator:**

The WebSocket fan-out test requires a separate process that publishes events to Kinesis at the target rate. This runs alongside the Artillery scenario.

```bash
#!/bin/bash
# load-tests/generate-kinesis-events.sh
# Publishes 100 events/second to Kinesis for the WebSocket fan-out test

STREAM_NAME="agentmail-events-staging"
REGION="us-east-1"
EVENTS_PER_SECOND=100
DURATION_SECONDS=300

echo "Publishing $EVENTS_PER_SECOND events/sec for ${DURATION_SECONDS}s to $STREAM_NAME"

for i in $(seq 1 $DURATION_SECONDS); do
  # Generate batch of events
  RECORDS="["
  for j in $(seq 1 $EVENTS_PER_SECOND); do
    INBOX_INDEX=$((RANDOM % 100))
    EVENT_ID="evt_loadtest_${i}_${j}"
    TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)
    DATA=$(echo -n "{\"eventId\":\"$EVENT_ID\",\"type\":\"message.received\",\"timestamp\":\"$TIMESTAMP\",\"inboxId\":\"loadtest-inbox-$INBOX_INDEX\",\"orgId\":\"org_loadtest\"}" | base64)
    
    if [ "$j" -gt 1 ]; then RECORDS="$RECORDS,"; fi
    RECORDS="$RECORDS{\"Data\":\"$DATA\",\"PartitionKey\":\"loadtest-inbox-$INBOX_INDEX\"}"
  done
  RECORDS="$RECORDS]"

  aws kinesis put-records \
    --stream-name "$STREAM_NAME" \
    --records "$RECORDS" \
    --region "$REGION" \
    --no-cli-pager &

  sleep 1
done

wait
echo "Event generation complete"
```

**Expected results:**

| Metric | Expected | Fail Threshold |
|--------|----------|---------------|
| Concurrent connections established | 1,000 | <950 |
| Event delivery latency (P50) | <300ms | >500ms |
| Event delivery latency (P99) | <800ms | >1,000ms |
| Message loss rate | <0.1% | >1% |
| Connection drop rate | <1% | >5% |
| WebSocket fan-out Lambda errors | 0 | >10 |

**What to monitor during test:**

- CloudWatch: API Gateway WebSocket `ConnectionCount`, `MessageCount`
- CloudWatch: Lambda `ws-fanout` concurrent executions, duration, errors
- CloudWatch: Kinesis `GetRecords.IteratorAgeMilliseconds`
- CloudWatch: Redis `CurrConnections`, `EngineCPUUtilization` (used for connection-to-channel mapping)
- Custom metric: `AgentMail/WebSocket/DeliveryLatency` P50/P99

---

### Scenario 5: Free Tier Abuse Simulation

Validates that rate limiting works correctly under pressure: free tier users hitting limits should receive fast 429 responses without impacting paid tier users. This tests the three-tier rate limiting architecture (WAF -> API Gateway Usage Plans -> Redis sliding window).

```yaml
# load-tests/artillery/scenarios/free-tier-abuse.yml
config:
  target: "https://api.staging.agentmail.aws"
  phases:
    - duration: 300       # 5 minutes
      arrivalRate: 100    # 100 concurrent users
      name: "Sustained abuse + paid traffic"
  processor: "../processors/auth.js"
  plugins:
    publish-metrics:
      - type: cloudwatch
        region: "us-east-1"
        namespace: "AgentMail/LoadTests"
        dimensions:
          - name: "Scenario"
            value: "free-tier-abuse"
  defaults:
    headers:
      Content-Type: "application/json"

scenarios:
  # 50% free tier users hammering the API beyond their limits
  - name: "Free tier abuse - rapid reads"
    weight: 30
    flow:
      - loop:
          - function: "setApiKey"
          - get:
              url: "/v1/inboxes?limit=50"
          - think: 0.1    # 10 requests/second per user (exceeds free tier 5 rps)
        count: 100
    beforeScenario:
      - function: "setFreeTier"

  - name: "Free tier abuse - rapid sends"
    weight: 20
    flow:
      - loop:
          - function: "setApiKey"
          - post:
              url: "/v1/inboxes/loadtest-free-inbox/messages"
              json:
                to: "nobody@simulator.amazonses.com"
                subject: "Spam {{ $randomString(5) }}"
                body: "Free tier abuse test"
          - think: 0.05   # 20 requests/second (far exceeds free tier 10/min send limit)
        count: 50
    beforeScenario:
      - function: "setFreeTier"

  # 50% paid tier users running normally -- these must not be impacted
  - name: "Pro tier normal reads"
    weight: 25
    flow:
      - function: "setApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
          expect:
            - statusCode: 200
      - get:
          url: "/v1/inboxes/{{ inboxId }}/messages?limit=20"
          expect:
            - statusCode: 200

  - name: "Business tier normal operations"
    weight: 25
    flow:
      - function: "setApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
          expect:
            - statusCode: 200
      - post:
          url: "/v1/inboxes/{{ inboxId }}/messages"
          json:
            to: "loadtest-recipient@simulator.amazonses.com"
            subject: "Business normal {{ $randomString(5) }}"
            body: "Normal paid tier traffic during abuse test."
          expect:
            - statusCode: 201
    beforeScenario:
      - function: "setBusinessTier"
```

**Additional processor functions:**

```javascript
// Added to load-tests/artillery/processors/auth.js

function setFreeTier(context, ee, next) {
  context.vars.tier = 'free';
  return next();
}

function setBusinessTier(context, ee, next) {
  context.vars.tier = 'business';
  return next();
}
```

**Expected results:**

| Metric | Expected | Fail Threshold |
|--------|----------|---------------|
| Free tier 429 response time | <10ms | >50ms |
| Free tier 429 count | >80% of free tier requests | <50% |
| Pro tier success rate | 100% | <99.9% |
| Business tier success rate | 100% | <99.9% |
| Pro tier P99 latency | <200ms (same as baseline) | >250ms |
| Business tier P99 latency | <200ms (same as baseline) | >250ms |
| Lambda invocations from free tier (after API GW throttle) | <20% of free requests | >50% |

**What to monitor during test:**

- CloudWatch: API Gateway `429Count` split by usage plan (free vs pro vs business)
- CloudWatch: API Gateway latency split by usage plan
- CloudWatch: WAF `BlockedRequests` (should block IPs if free tier users also exceed WAF limits)
- CloudWatch: Redis `RateLimitHits` metric, split by tier and endpoint group
- CloudWatch: Lambda concurrent executions (should NOT spike -- most free tier abuse caught at API Gateway before Lambda invocation)
- Custom dashboard: Side-by-side latency comparison of free vs paid tiers

---

### Scenario 6: Peak Load

Simulates the full-scale production target: 10M messages/day (~115 messages/second sustained). This is the most demanding test and runs in a dedicated load-test environment, not staging, to avoid cost contamination. Uses Artillery's distributed mode across multiple Lambda workers.

```yaml
# load-tests/artillery/scenarios/peak-load.yml
config:
  target: "https://api.loadtest.agentmail.aws"
  phases:
    - duration: 300       # 5 minute ramp
      arrivalRate: 10
      rampTo: 500
      name: "Ramp to peak"
    - duration: 1800      # 30 minutes sustained peak
      arrivalRate: 500    # 500 VUs generating ~115 msg/sec + reads + searches
      name: "Sustained peak load"
    - duration: 300       # 5 minute cool-down
      arrivalRate: 500
      rampTo: 0
      name: "Cool down"
  processor: "../processors/auth.js"
  plugins:
    publish-metrics:
      - type: cloudwatch
        region: "us-east-1"
        namespace: "AgentMail/LoadTests"
        dimensions:
          - name: "Scenario"
            value: "peak-load"
  ensure:
    thresholds:
      - http.response_time.p99: 500       # Relaxed for peak: 500ms P99
      - http.response_time.p50: 100       # Relaxed for peak: 100ms P50
  defaults:
    headers:
      Content-Type: "application/json"

scenarios:
  # Traffic mix models production: 40% reads, 25% sends, 15% inbox management, 10% search, 10% webhooks
  - name: "Read messages (hot path)"
    weight: 40
    flow:
      - function: "setRandomTierApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[{{ $randomInt(0, 4) }}].id"
              as: "inboxId"
      - get:
          url: "/v1/inboxes/{{ inboxId }}/messages?limit=20"
          capture:
            - json: "$.data[0].id"
              as: "messageId"
      - get:
          url: "/v1/inboxes/{{ inboxId }}/messages/{{ messageId }}"

  - name: "Send messages"
    weight: 25
    flow:
      - function: "setRandomTierApiKey"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
      - post:
          url: "/v1/inboxes/{{ inboxId }}/messages"
          json:
            to: "loadtest-{{ $randomString(6) }}@simulator.amazonses.com"
            subject: "Peak load test {{ $timestamp }}"
            body: "Peak load test message. Unique: {{ $randomString(20) }}"
          expect:
            - statusCode: 201

  - name: "Inbox management"
    weight: 15
    flow:
      - function: "setRandomTierApiKey"
      - function: "generateInboxName"
      - post:
          url: "/v1/inboxes"
          json:
            name: "{{ inboxName }}"
          afterResponse: "captureInboxId"
      - get:
          url: "/v1/inboxes/{{ inboxId }}"
      - patch:
          url: "/v1/inboxes/{{ inboxId }}"
          json:
            autoReply: true
            autoReplyMessage: "Thank you for your message."
      - think: 5
      - delete:
          url: "/v1/inboxes/{{ inboxId }}"

  - name: "Search queries"
    weight: 10
    flow:
      - function: "setRandomTierApiKey"
      - post:
          url: "/v1/search"
          json:
            query: "{{ $randomString(8) }} invoice payment receipt"
            limit: 20
          expect:
            - statusCode: 200

  - name: "Webhook management + message reads"
    weight: 10
    flow:
      - function: "setRandomTierApiKey"
      - get:
          url: "/v1/webhooks"
      - get:
          url: "/v1/inboxes"
          capture:
            - json: "$.data[0].id"
              as: "inboxId"
      - get:
          url: "/v1/inboxes/{{ inboxId }}/messages?limit=50"
```

**Run command (distributed mode):**

```bash
# Run peak load test using distributed Artillery workers on AWS Lambda
artillery run \
  --platform aws:lambda \
  --platform-opt region=us-east-1 \
  --platform-opt memory-size=4096 \
  --platform-opt count=20 \
  --config config/environments/loadtest.yml \
  scenarios/peak-load.yml \
  --output results/peak-load-$(date +%Y%m%d-%H%M%S).json
```

**Expected results:**

| Metric | Expected | Fail Threshold |
|--------|----------|---------------|
| Sustained throughput | >115 messages/sec | <100 messages/sec |
| Total requests (30 min) | >900,000 | N/A |
| P50 response time | <75ms | >100ms |
| P99 response time | <400ms | >500ms |
| Error rate (5xx) | <0.05% | >0.1% |
| DynamoDB throttle events | 0 | >10 |
| Lambda concurrent executions | <800 | >1000 (hitting limit) |
| Kinesis IteratorAge | <10s | >60s |
| OpenSearch indexing rate | >115 docs/sec | <100 docs/sec |

**What to monitor during test:**

- CloudWatch: Every Lambda function's duration, errors, throttles, concurrent executions
- CloudWatch: DynamoDB table-level consumed capacity, throttle events, adaptive capacity
- CloudWatch: Kinesis all shard metrics (IteratorAge, WriteProvisionedThroughputExceeded, ReadProvisionedThroughputExceeded)
- CloudWatch: OpenSearch `IndexingRate`, `SearchRate`, `SearchLatency`, `2xx`/`4xx`/`5xx`
- CloudWatch: SES `Send`, `Bounce`, `Complaint` rates, sending quota utilization
- CloudWatch: ElastiCache `EngineCPUUtilization`, `DatabaseMemoryUsagePercentage`, `CurrConnections`
- CloudWatch: API Gateway `5XXError`, `4XXError`, `Latency`, `Count`, `IntegrationLatency`
- X-Ray: Full service map with latency percentiles at every hop
- Custom dashboard: Real-time throughput graph overlaid with error rate

---

## Capacity Planning

### AWS Service Limits and Scale Tiers

AgentMail defines three scale tiers based on message volume. Capacity planning determines when to request service limit increases and how to configure auto-scaling at each tier.

| Scale Tier | Daily Messages | Monthly API Requests | Concurrent Users | Target Customers |
|-----------|---------------|---------------------|-----------------|-----------------|
| Startup | <100K/day | <5M | <500 | MVP, early adopters |
| Growth | 100K - 1M/day | 5M - 50M | 500 - 5,000 | Product-market fit |
| Full | 1M - 10M/day | 50M - 500M | 5,000 - 50,000 | Scale operations |

### Service Limit Matrix

| Service | Default Limit | At Startup (<100K/day) | At Growth (1M/day) | At Full (10M/day) | Action Needed |
|---------|--------------|----------------------|-------------------|-------------------|---------------|
| Lambda concurrent executions | 1,000 | ~100 | ~500 | ~2,000 | Request increase to 3,000 at Growth |
| Lambda burst concurrency | 3,000 (initial) | OK | OK | May hit | Request increase at Full |
| API Gateway REST requests/sec | 10,000 | ~200 | ~2,000 | ~20,000 | Request increase to 30,000 at Full |
| API Gateway WebSocket connections | 500 new connections/sec | ~10/sec | ~100/sec | ~1,000/sec | Request increase to 2,000 at Full |
| API Gateway WebSocket message rate | 32,000/sec (per route) | ~100/sec | ~5,000/sec | ~50,000/sec | Request increase at Full |
| SES sending rate | 14 emails/sec (sandbox: 1/sec) | ~2/sec | ~12/sec | ~120/sec | Request production access; request increase to 200/sec at Growth |
| SES daily sending quota | 50,000/day (production) | OK | OK | Request 15M/day at Full | Monitor utilization weekly |
| DynamoDB on-demand RCU | Auto-scales (starts 4,000 RCU/sec) | Auto | Auto | Auto | Monitor `ConsumedReadCapacityUnits` and adaptive capacity warnings |
| DynamoDB on-demand WCU | Auto-scales (starts 4,000 WCU/sec) | Auto | Auto | Auto | Monitor `ConsumedWriteCapacityUnits`; if sustained >4,000 WCU/sec, pre-warm via support |
| DynamoDB table size | Unlimited | OK | OK | OK | Monitor partition heat via CloudWatch Contributor Insights |
| Kinesis Data Streams (on-demand) | Auto-scales | ~2 shards | ~8 shards | ~20 shards | Monitor `IteratorAge` and `WriteProvisionedThroughputExceeded` |
| SQS message rate | Unlimited (standard queues) | OK | OK | OK | Monitor `ApproximateNumberOfMessagesVisible` for DLQ depth |
| OpenSearch Serverless OCUs | 20 OCU max (per collection) | 2 OCU | 4-6 OCU | 10-16 OCU | Request increase to 30 OCU at Full |
| ElastiCache node type | r7g.large (default deployment) | 1 node | 2 nodes (replica) | Cluster mode, 2-4 shards | Scale node type at Growth, enable cluster mode at Full |
| S3 request rate | 5,500 GET/sec, 3,500 PUT/sec per prefix | OK | OK | Partition prefixes if single-prefix PUT >3,500/sec | Use date-based or hash-based prefixes for email storage |
| Step Functions executions | 2,000 starts/sec (standard) | ~10/sec | ~50/sec | ~200/sec | OK with default limits |
| EventBridge PutEvents | 10,000 entries/sec (per region) | ~50/sec | ~500/sec | ~5,000/sec | OK with default limits |
| Bedrock Claude Haiku RPM | Varies by region | ~100/min | ~1,000/min | ~10,000/min | Request quota increase at Growth |
| Bedrock Titan Embeddings RPM | Varies by region | ~100/min | ~1,000/min | ~10,000/min | Request quota increase at Growth |

### Checking Current Limits

```bash
#!/bin/bash
# scripts/check-service-limits.sh
# Queries AWS Service Quotas API for all AgentMail-relevant limits

REGION="us-east-1"

echo "=== AgentMail Service Limits Report ==="
echo "Region: $REGION"
echo "Date: $(date -u)"
echo ""

# Lambda concurrent executions
echo "--- Lambda ---"
aws service-quotas get-service-quota \
  --service-code lambda \
  --quota-code L-B99A9384 \
  --region "$REGION" \
  --query '{Limit: Quota.Value, Name: Quota.QuotaName}' \
  --output table

# API Gateway REST API requests/sec
echo "--- API Gateway ---"
aws service-quotas get-service-quota \
  --service-code apigateway \
  --quota-code L-8A5B8E43 \
  --region "$REGION" \
  --query '{Limit: Quota.Value, Name: Quota.QuotaName}' \
  --output table

# SES sending rate
echo "--- SES ---"
aws sesv2 get-account \
  --region "$REGION" \
  --query '{SendingEnabled: SendingEnabled, MaxSendRate: SendQuota.MaxSendRate, Max24HourSend: SendQuota.Max24HourSend, SentLast24Hours: SendQuota.SentLast24Hours}'

# DynamoDB (on-demand has no explicit limit to query, but check table metrics)
echo "--- DynamoDB ---"
aws dynamodb describe-table \
  --table-name agentmail \
  --region "$REGION" \
  --query '{BillingMode: Table.BillingModeSummary.BillingMode, ItemCount: Table.ItemCount, TableSizeBytes: Table.TableSizeBytes}'

# Kinesis
echo "--- Kinesis ---"
aws kinesis describe-stream-summary \
  --stream-name agentmail-events \
  --region "$REGION" \
  --query '{StreamMode: StreamDescriptionSummary.StreamModeDetails.StreamMode, OpenShardCount: StreamDescriptionSummary.OpenShardCount}'

# OpenSearch Serverless
echo "--- OpenSearch Serverless ---"
aws opensearchserverless list-collections \
  --region "$REGION" \
  --query 'collectionSummaries[?name==`agentmail`]'

# ElastiCache
echo "--- ElastiCache ---"
aws elasticache describe-replication-groups \
  --replication-group-id agentmail-redis \
  --region "$REGION" \
  --query '{NodeType: ReplicationGroups[0].CacheNodeType, NumNodeGroups: ReplicationGroups[0].NodeGroups | length(@), ClusterEnabled: ReplicationGroups[0].ClusterEnabled}'

echo ""
echo "=== End of Report ==="
```

### When to Request Limit Increases

| Trigger | Action | Lead Time |
|---------|--------|-----------|
| Lambda concurrent executions >60% of limit sustained for 1 hour | Request 2x current limit | 1-3 business days |
| SES sending rate >70% of limit | Request 2x current limit | 1-5 business days (may require review) |
| API Gateway requests >50% of limit | Request 2x current limit | 1-3 business days |
| OpenSearch OCU >80% of max | Request higher max OCU | 1-3 business days |
| DynamoDB sustained >3,000 WCU/sec for a single table | Contact AWS support for pre-warming | Schedule 24-48 hours ahead |
| Kinesis on-demand hitting throughput limits | Increase provisioned mode if latency-sensitive | Immediate (provisioned mode switch) |

### Proactive Limit Monitoring (CDK)

```typescript
// lib/stacks/observability-stack.ts (limit monitoring alarms)
import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatch_actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';

interface LimitMonitoringProps {
  alarmTopic: sns.ITopic;
}

export class LimitMonitoringConstruct extends Construct {
  constructor(scope: Construct, id: string, props: LimitMonitoringProps) {
    super(scope, id);

    // Lambda concurrent executions alarm (80% of 1000 limit)
    const lambdaConcurrencyAlarm = new cloudwatch.Alarm(this, 'LambdaConcurrencyAlarm', {
      alarmName: 'agentmail-lambda-concurrency-high',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/Lambda',
        metricName: 'ConcurrentExecutions',
        statistic: 'Maximum',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 800,   // 80% of 1000 default limit
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Lambda concurrent executions approaching account limit. Request increase via Service Quotas.',
    });
    lambdaConcurrencyAlarm.addAlarmAction(new cloudwatch_actions.SnsAction(props.alarmTopic));

    // SES sending rate alarm (70% of current limit)
    const sesSendRateAlarm = new cloudwatch.Alarm(this, 'SESSendRateAlarm', {
      alarmName: 'agentmail-ses-send-rate-high',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/SES',
        metricName: 'Send',
        statistic: 'Sum',
        period: cdk.Duration.minutes(1),
      }),
      threshold: 600,    // 10/sec * 60sec * 0.7 = 420 (for 14/sec limit); adjust per current limit
      evaluationPeriods: 5,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'SES sending rate approaching account limit. Request increase via SES console.',
    });
    sesSendRateAlarm.addAlarmAction(new cloudwatch_actions.SnsAction(props.alarmTopic));

    // API Gateway 5xx rate alarm
    const apiGateway5xxAlarm = new cloudwatch.Alarm(this, 'ApiGateway5xxAlarm', {
      alarmName: 'agentmail-api-5xx-rate',
      metric: new cloudwatch.MathExpression({
        expression: 'errors / total * 100',
        usingMetrics: {
          errors: new cloudwatch.Metric({
            namespace: 'AWS/ApiGateway',
            metricName: '5XXError',
            dimensionsMap: { ApiName: 'agentmail-rest-api' },
            statistic: 'Sum',
            period: cdk.Duration.minutes(5),
          }),
          total: new cloudwatch.Metric({
            namespace: 'AWS/ApiGateway',
            metricName: 'Count',
            dimensionsMap: { ApiName: 'agentmail-rest-api' },
            statistic: 'Sum',
            period: cdk.Duration.minutes(5),
          }),
        },
      }),
      threshold: 0.1,    // 0.1% error rate
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'API error rate exceeding 0.1% SLO.',
    });
    apiGateway5xxAlarm.addAlarmAction(new cloudwatch_actions.SnsAction(props.alarmTopic));

    // DynamoDB throttle alarm
    const dynamoThrottleAlarm = new cloudwatch.Alarm(this, 'DynamoThrottleAlarm', {
      alarmName: 'agentmail-dynamodb-throttle',
      metric: new cloudwatch.MathExpression({
        expression: 'readThrottle + writeThrottle',
        usingMetrics: {
          readThrottle: new cloudwatch.Metric({
            namespace: 'AWS/DynamoDB',
            metricName: 'ReadThrottleEvents',
            dimensionsMap: { TableName: 'agentmail' },
            statistic: 'Sum',
            period: cdk.Duration.minutes(5),
          }),
          writeThrottle: new cloudwatch.Metric({
            namespace: 'AWS/DynamoDB',
            metricName: 'WriteThrottleEvents',
            dimensionsMap: { TableName: 'agentmail' },
            statistic: 'Sum',
            period: cdk.Duration.minutes(5),
          }),
        },
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'DynamoDB throttle events detected. Check partition key distribution and consider pre-warming.',
    });
    dynamoThrottleAlarm.addAlarmAction(new cloudwatch_actions.SnsAction(props.alarmTopic));

    // Kinesis iterator age alarm
    const kinesisIteratorAgeAlarm = new cloudwatch.Alarm(this, 'KinesisIteratorAgeAlarm', {
      alarmName: 'agentmail-kinesis-iterator-age',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/Kinesis',
        metricName: 'GetRecords.IteratorAgeMilliseconds',
        dimensionsMap: { StreamName: 'agentmail-events' },
        statistic: 'Maximum',
        period: cdk.Duration.minutes(1),
      }),
      threshold: 30000,   // 30 seconds
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Kinesis consumer falling behind. Check Lambda consumer errors and concurrency.',
    });
    kinesisIteratorAgeAlarm.addAlarmAction(new cloudwatch_actions.SnsAction(props.alarmTopic));

    // OpenSearch indexing latency alarm
    const opensearchIndexingAlarm = new cloudwatch.Alarm(this, 'OpenSearchIndexingAlarm', {
      alarmName: 'agentmail-opensearch-indexing-latency',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/AOSS',
        metricName: 'IndexingOCU',
        dimensionsMap: { CollectionName: 'agentmail' },
        statistic: 'Average',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 16,      // OCU approaching max
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'OpenSearch indexing OCU approaching max. Request limit increase.',
    });
    opensearchIndexingAlarm.addAlarmAction(new cloudwatch_actions.SnsAction(props.alarmTopic));
  }
}
```

---

## Performance Benchmarks

Baseline benchmarks are recorded during initial deployment and updated quarterly. CI/CD compares every staging deploy against these benchmarks and blocks promotion if any metric regresses beyond the allowed threshold.

### Baseline Benchmark Table

| Operation | P50 | P99 | Throughput | Measured At | Regression Threshold |
|-----------|-----|-----|-----------|-------------|---------------------|
| Create inbox | 15ms | 45ms | 500/sec | Startup | +20% P99 |
| Send message | 120ms | 350ms | 200/sec | Startup | +20% P99 |
| List messages | 8ms | 25ms | 2,000/sec | Startup | +20% P99 |
| Get message | 5ms | 15ms | 3,000/sec | Startup | +20% P99 |
| Delete message | 6ms | 18ms | 2,500/sec | Startup | +20% P99 |
| Semantic search | 150ms | 400ms | 100/sec | Startup | +25% P99 |
| Full-text search | 50ms | 150ms | 300/sec | Startup | +25% P99 |
| Webhook delivery (end-to-end) | 800ms | 2,500ms | 1,000/sec | Startup | +30% P99 |
| WebSocket event delivery | 200ms | 500ms | 5,000/sec | Startup | +30% P99 |
| Inbound email processing | 1,200ms | 2,800ms | 500/sec | Startup | +30% P99 |
| AI categorization (Step Functions) | 3,000ms | 15,000ms | 50/sec | Startup | +50% P99 |
| AI data extraction (Step Functions) | 5,000ms | 25,000ms | 30/sec | Startup | +50% P99 |

### Benchmark Storage and Comparison

Benchmarks are stored as JSON in S3 and compared using a custom Lambda function triggered by CodePipeline.

```json
{
  "benchmarks": {
    "create_inbox": { "p50_ms": 15, "p99_ms": 45, "throughput_per_sec": 500 },
    "send_message": { "p50_ms": 120, "p99_ms": 350, "throughput_per_sec": 200 },
    "list_messages": { "p50_ms": 8, "p99_ms": 25, "throughput_per_sec": 2000 },
    "get_message": { "p50_ms": 5, "p99_ms": 15, "throughput_per_sec": 3000 },
    "semantic_search": { "p50_ms": 150, "p99_ms": 400, "throughput_per_sec": 100 },
    "webhook_delivery": { "p50_ms": 800, "p99_ms": 2500, "throughput_per_sec": 1000 },
    "websocket_event": { "p50_ms": 200, "p99_ms": 500, "throughput_per_sec": 5000 }
  },
  "measured_at": "2026-04-10T00:00:00Z",
  "environment": "staging",
  "git_sha": "abc123"
}
```

**Benchmark comparison script:**

```bash
#!/bin/bash
# scripts/compare-benchmarks.sh
# Compares load test results against stored baselines
# Exit code 1 if any metric regresses beyond threshold

REGION="us-east-1"
BUCKET="agentmail-loadtest-results"
BASELINE_KEY="benchmarks/baseline.json"
RESULTS_FILE="$1"

if [ -z "$RESULTS_FILE" ]; then
  echo "Usage: compare-benchmarks.sh <results-file>"
  exit 1
fi

# Download baseline
aws s3 cp "s3://${BUCKET}/${BASELINE_KEY}" /tmp/baseline.json --region "$REGION"

# Compare using jq
REGRESSION_FOUND=false

for operation in create_inbox send_message list_messages get_message semantic_search webhook_delivery websocket_event; do
  BASELINE_P99=$(jq -r ".benchmarks.${operation}.p99_ms" /tmp/baseline.json)
  CURRENT_P99=$(jq -r ".benchmarks.${operation}.p99_ms" "$RESULTS_FILE")
  THRESHOLD=$(echo "$BASELINE_P99 * 1.2" | bc)  # 20% regression threshold

  if (( $(echo "$CURRENT_P99 > $THRESHOLD" | bc -l) )); then
    echo "REGRESSION: ${operation} P99 regressed from ${BASELINE_P99}ms to ${CURRENT_P99}ms (threshold: ${THRESHOLD}ms)"
    REGRESSION_FOUND=true
  else
    echo "OK: ${operation} P99 = ${CURRENT_P99}ms (baseline: ${BASELINE_P99}ms, threshold: ${THRESHOLD}ms)"
  fi
done

if [ "$REGRESSION_FOUND" = true ]; then
  echo ""
  echo "FAIL: Performance regression detected. Deploy blocked."
  exit 1
fi

echo ""
echo "PASS: All benchmarks within acceptable range."
exit 0
```

---

## Auto-Scaling Triggers

### Auto-Scaling Configuration

| Component | Metric | Scale-Up Threshold | Scale-Down Threshold | Min | Max | Cooldown |
|-----------|--------|-------------------|---------------------|-----|-----|----------|
| Lambda (API handlers) | ConcurrentExecutions | >80% reserved concurrency | <20% reserved concurrency | N/A | 1,000 | N/A (managed) |
| Lambda (provisioned concurrency) | ProvisionedConcurrencyUtilization | >70% | <30% | 10 | 200 | 5 min |
| ECS Fargate (webhook delivery) | SQS ApproximateNumberOfMessagesVisible | >1,000 messages | <100 messages | 2 tasks | 50 tasks | 3 min |
| ECS Fargate (IMAP server) | CPU Utilization | >70% | <30% | 2 tasks | 20 tasks | 5 min |
| ECS Fargate (SMTP server) | CPU Utilization | >70% | <30% | 2 tasks | 20 tasks | 5 min |
| Kinesis Data Streams (on-demand) | WriteProvisionedThroughputExceeded | >0 (auto-scales) | N/A | Auto | Auto | N/A (managed) |
| ElastiCache Redis | EngineCPUUtilization | >65% | <25% | 2 shards | 8 shards | 15 min |
| OpenSearch Serverless | Auto-managed OCU | N/A (auto-scales) | N/A | 2 OCU | 20 OCU | N/A (managed) |

### CDK Auto-Scaling Configuration

```typescript
// lib/stacks/compute-stack.ts (auto-scaling configuration)
import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as appscaling from 'aws-cdk-lib/aws-applicationautoscaling';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';

interface AutoScalingProps {
  apiFunction: lambda.Function;
  webhookService: ecs.FargateService;
  imapService: ecs.FargateService;
  smtpService: ecs.FargateService;
  webhookQueue: sqs.Queue;
}

export class AutoScalingConstruct extends Construct {
  constructor(scope: Construct, id: string, props: AutoScalingProps) {
    super(scope, id);

    // --- Lambda Provisioned Concurrency Auto-Scaling ---
    const alias = props.apiFunction.addAlias('live');

    const pcTarget = new appscaling.ScalableTarget(this, 'ApiLambdaPC', {
      serviceNamespace: appscaling.ServiceNamespace.LAMBDA,
      minCapacity: 10,
      maxCapacity: 200,
      resourceId: `function:${props.apiFunction.functionName}:live`,
      scalableDimension: 'lambda:function:ProvisionedConcurrency',
    });

    pcTarget.scaleToTrackMetric('ApiLambdaPCTracking', {
      targetValue: 0.7,    // Scale when utilization hits 70%
      predefinedMetric: appscaling.PredefinedMetric.LAMBDA_PROVISIONED_CONCURRENCY_UTILIZATION,
      scaleInCooldown: cdk.Duration.minutes(5),
      scaleOutCooldown: cdk.Duration.minutes(2),
    });

    // --- ECS Webhook Service Auto-Scaling (SQS-based) ---
    const webhookScaling = props.webhookService.autoScaleTaskCount({
      minCapacity: 2,
      maxCapacity: 50,
    });

    // Scale based on SQS queue depth
    webhookScaling.scaleOnMetric('WebhookQueueDepthScaling', {
      metric: props.webhookQueue.metricApproximateNumberOfMessagesVisible({
        period: cdk.Duration.minutes(1),
        statistic: 'Average',
      }),
      scalingSteps: [
        { upper: 100, change: -1 },     // Below 100 msgs: scale in
        { lower: 1000, change: +2 },    // Above 1000 msgs: add 2 tasks
        { lower: 5000, change: +5 },    // Above 5000 msgs: add 5 tasks
        { lower: 10000, change: +10 },  // Above 10000 msgs: add 10 tasks
      ],
      adjustmentType: appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
      cooldown: cdk.Duration.minutes(3),
    });

    // --- ECS IMAP Service Auto-Scaling (CPU-based) ---
    const imapScaling = props.imapService.autoScaleTaskCount({
      minCapacity: 2,
      maxCapacity: 20,
    });

    imapScaling.scaleOnCpuUtilization('ImapCpuScaling', {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.minutes(10),
      scaleOutCooldown: cdk.Duration.minutes(5),
    });

    // --- ECS SMTP Service Auto-Scaling (CPU-based) ---
    const smtpScaling = props.smtpService.autoScaleTaskCount({
      minCapacity: 2,
      maxCapacity: 20,
    });

    smtpScaling.scaleOnCpuUtilization('SmtpCpuScaling', {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.minutes(10),
      scaleOutCooldown: cdk.Duration.minutes(5),
    });

    // --- Scheduled Scaling for Known Traffic Patterns ---
    // If traffic analysis shows predictable patterns (e.g., business hours),
    // add scheduled scaling actions.
    webhookScaling.scaleOnSchedule('WebhookBusinessHoursScaleUp', {
      schedule: appscaling.Schedule.cron({
        hour: '13',    // 9 AM ET = 13 UTC
        minute: '0',
        weekDay: 'MON-FRI',
      }),
      minCapacity: 5,  // Pre-scale for business hours
    });

    webhookScaling.scaleOnSchedule('WebhookNightScaleDown', {
      schedule: appscaling.Schedule.cron({
        hour: '3',     // 11 PM ET = 3 UTC
        minute: '0',
        weekDay: 'MON-FRI',
      }),
      minCapacity: 2,  // Scale down for off-hours
    });
  }
}
```

### ElastiCache Redis Scaling Strategy

ElastiCache does not support native auto-scaling for cluster-mode shards. Scaling is triggered by a CloudWatch alarm that invokes a Step Functions workflow.

```typescript
// lib/constructs/redis-scaling.ts
import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatch_actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as sns_subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';

interface RedisScalingProps {
  replicationGroupId: string;
  alarmTopic: sns.ITopic;
}

export class RedisScalingConstruct extends Construct {
  constructor(scope: Construct, id: string, props: RedisScalingProps) {
    super(scope, id);

    // Alarm: Redis CPU > 65% for 15 minutes
    const cpuHighAlarm = new cloudwatch.Alarm(this, 'RedisCpuHighAlarm', {
      alarmName: 'agentmail-redis-cpu-high',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/ElastiCache',
        metricName: 'EngineCPUUtilization',
        dimensionsMap: { ReplicationGroupId: props.replicationGroupId },
        statistic: 'Average',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 65,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'Redis CPU high. Trigger scaling evaluation.',
    });
    cpuHighAlarm.addAlarmAction(new cloudwatch_actions.SnsAction(props.alarmTopic));

    // Alarm: Redis memory > 80%
    const memoryHighAlarm = new cloudwatch.Alarm(this, 'RedisMemoryHighAlarm', {
      alarmName: 'agentmail-redis-memory-high',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/ElastiCache',
        metricName: 'DatabaseMemoryUsagePercentage',
        dimensionsMap: { ReplicationGroupId: props.replicationGroupId },
        statistic: 'Average',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 80,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'Redis memory high. Consider scaling node type or adding shards.',
    });
    memoryHighAlarm.addAlarmAction(new cloudwatch_actions.SnsAction(props.alarmTopic));
  }
}
```

---

## CI/CD Integration

### Load Test Pipeline

```yaml
# .github/workflows/load-test.yml
name: Load Tests

on:
  # Run API baseline on every staging deploy
  workflow_run:
    workflows: ["Deploy to Staging"]
    types: [completed]
    branches: [main]

  # Run full suite weekly (Sunday midnight UTC)
  schedule:
    - cron: '0 0 * * 0'

  # Manual trigger for any scenario
  workflow_dispatch:
    inputs:
      scenario:
        description: 'Scenario to run'
        required: true
        default: 'api-baseline'
        type: choice
        options:
          - api-baseline
          - inbox-burst
          - inbound-storm
          - websocket-fanout
          - free-tier-abuse
          - peak-load
          - all
      environment:
        description: 'Target environment'
        required: true
        default: 'staging'
        type: choice
        options:
          - staging
          - loadtest

env:
  AWS_REGION: us-east-1
  RESULTS_BUCKET: agentmail-loadtest-results

jobs:
  # Gate: only run if staging deploy succeeded
  check-trigger:
    runs-on: ubuntu-latest
    outputs:
      should_run: ${{ steps.check.outputs.should_run }}
      scenario: ${{ steps.check.outputs.scenario }}
      environment: ${{ steps.check.outputs.environment }}
    steps:
      - id: check
        run: |
          if [ "${{ github.event_name }}" = "workflow_run" ]; then
            echo "should_run=${{ github.event.workflow_run.conclusion == 'success' }}" >> $GITHUB_OUTPUT
            echo "scenario=api-baseline" >> $GITHUB_OUTPUT
            echo "environment=staging" >> $GITHUB_OUTPUT
          elif [ "${{ github.event_name }}" = "schedule" ]; then
            echo "should_run=true" >> $GITHUB_OUTPUT
            echo "scenario=all" >> $GITHUB_OUTPUT
            echo "environment=staging" >> $GITHUB_OUTPUT
          else
            echo "should_run=true" >> $GITHUB_OUTPUT
            echo "scenario=${{ github.event.inputs.scenario }}" >> $GITHUB_OUTPUT
            echo "environment=${{ github.event.inputs.environment }}" >> $GITHUB_OUTPUT
          fi

  load-test:
    needs: check-trigger
    if: needs.check-trigger.outputs.should_run == 'true'
    runs-on: ubuntu-latest
    environment: ${{ needs.check-trigger.outputs.environment }}
    permissions:
      id-token: write    # OIDC for AWS auth
      contents: read

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install Artillery
        run: |
          npm install -g artillery@latest
          npm install -g artillery-plugin-publish-metrics

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_LOADTEST_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Fetch load test API keys from SSM
        run: |
          echo "LOADTEST_FREE_API_KEY=$(aws ssm get-parameter --name /agentmail/${{ needs.check-trigger.outputs.environment }}/loadtest/free-api-key --with-decryption --query Parameter.Value --output text)" >> $GITHUB_ENV
          echo "LOADTEST_PRO_API_KEY=$(aws ssm get-parameter --name /agentmail/${{ needs.check-trigger.outputs.environment }}/loadtest/pro-api-key --with-decryption --query Parameter.Value --output text)" >> $GITHUB_ENV
          echo "LOADTEST_BUSINESS_API_KEY=$(aws ssm get-parameter --name /agentmail/${{ needs.check-trigger.outputs.environment }}/loadtest/business-api-key --with-decryption --query Parameter.Value --output text)" >> $GITHUB_ENV
          echo "LOADTEST_SCALE_API_KEY=$(aws ssm get-parameter --name /agentmail/${{ needs.check-trigger.outputs.environment }}/loadtest/scale-api-key --with-decryption --query Parameter.Value --output text)" >> $GITHUB_ENV

      - name: Run load test scenario
        working-directory: load-tests/artillery
        run: |
          SCENARIO="${{ needs.check-trigger.outputs.scenario }}"
          ENV="${{ needs.check-trigger.outputs.environment }}"
          TIMESTAMP=$(date +%Y%m%d-%H%M%S)

          if [ "$SCENARIO" = "all" ]; then
            SCENARIOS="api-baseline inbox-burst inbound-storm websocket-fanout free-tier-abuse"
          elif [ "$SCENARIO" = "peak-load" ]; then
            # Peak load uses distributed mode
            artillery run \
              --platform aws:lambda \
              --platform-opt region=${{ env.AWS_REGION }} \
              --platform-opt memory-size=4096 \
              --platform-opt count=20 \
              --config config/environments/${ENV}.yml \
              scenarios/peak-load.yml \
              --output ../../results/peak-load-${TIMESTAMP}.json
            SCENARIOS=""
          else
            SCENARIOS="$SCENARIO"
          fi

          for s in $SCENARIOS; do
            echo "=== Running scenario: $s ==="
            artillery run \
              --config config/environments/${ENV}.yml \
              scenarios/${s}.yml \
              --output ../../results/${s}-${TIMESTAMP}.json \
              || true  # Continue even if assertions fail (we report later)
          done

      - name: Upload results to S3
        if: always()
        run: |
          TIMESTAMP=$(date +%Y%m%d-%H%M%S)
          aws s3 sync results/ \
            s3://${{ env.RESULTS_BUCKET }}/runs/${{ github.run_id }}/ \
            --region ${{ env.AWS_REGION }}

      - name: Compare against benchmarks
        run: |
          for result_file in results/*.json; do
            if [ -f "$result_file" ]; then
              echo "Comparing: $result_file"
              bash scripts/compare-benchmarks.sh "$result_file"
            fi
          done

      - name: Post results to Slack
        if: always()
        uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {
              "text": "Load Test Results: ${{ needs.check-trigger.outputs.scenario }} on ${{ needs.check-trigger.outputs.environment }}",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Load Test Complete*\nScenario: `${{ needs.check-trigger.outputs.scenario }}`\nEnvironment: `${{ needs.check-trigger.outputs.environment }}`\nStatus: `${{ job.status }}`\nRun: <${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}|View Results>"
                  }
                }
              ]
            }
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_LOADTEST_WEBHOOK }}

  # Monthly peak load test (separate job with approval gate)
  peak-load-monthly:
    if: github.event_name == 'schedule' && github.event.schedule == '0 0 1 * *'
    runs-on: ubuntu-latest
    environment:
      name: loadtest
      # Requires manual approval before running (expensive)
    steps:
      - uses: actions/checkout@v4
      - name: Run peak load
        run: echo "Peak load test requires manual approval. Trigger via workflow_dispatch with scenario=peak-load."
```

### Test Execution Schedule

| Scenario | Trigger | Environment | Frequency |
|----------|---------|-------------|-----------|
| API Baseline | Every staging deploy | Staging | ~5-10x/week |
| Inbox Burst | Weekly (Sunday) | Staging | Weekly |
| Inbound Storm | Weekly (Sunday) | Staging | Weekly |
| WebSocket Fan-Out | Weekly (Sunday) | Staging | Weekly |
| Free Tier Abuse | Weekly (Sunday) | Staging | Weekly |
| Peak Load | Manual trigger (with approval) | Load-test | Monthly |

### Deploy Gate Logic

The API Baseline test (Scenario 1) runs after every staging deploy. If any of these conditions are met, the deploy is blocked from promoting to production:

1. P99 latency regresses more than 20% from baseline
2. Error rate exceeds 0.5%
3. Any SLO is violated during the test
4. DynamoDB throttle events > 0

The deploy gate is implemented as a CodePipeline approval action that is automatically approved or rejected based on load test results.

---

## Cost of Load Testing

Load testing consumes real AWS resources. These estimates help budget for test runs and avoid surprise bills.

### Per-Scenario Cost Estimates

| Scenario | Duration | Estimated AWS Cost | Primary Cost Drivers |
|----------|----------|-------------------|---------------------|
| **1. API Baseline** | ~17 min | **$2 - $5** | Lambda invocations (~600K), DynamoDB reads/writes, API Gateway requests |
| **2. Inbox Burst** | ~2 min | **$0.50 - $1** | Lambda invocations (~3K), DynamoDB writes |
| **3. Inbound Storm** | ~7 min | **$5 - $10** | Lambda invocations (~20K), DynamoDB writes (~10K), S3 PUTs (~10K), Kinesis PUTs, OpenSearch indexing |
| **4. WebSocket Fan-Out** | ~6 min | **$3 - $7** | API Gateway WebSocket messages (~300K), Lambda invocations, Kinesis PUTs (~30K), Redis connections |
| **5. Free Tier Abuse** | ~5 min | **$1 - $3** | API Gateway requests (~150K), Lambda invocations (subset -- most blocked at API GW), Redis operations |
| **6. Peak Load** | ~40 min | **$50 - $100** | Lambda invocations (~1M+), DynamoDB reads/writes (~500K+), SES sends (~200K), S3, Kinesis, OpenSearch, Artillery Lambda workers (20x 4GB x 40min) |

### Monthly Testing Budget

| Activity | Frequency | Monthly Cost |
|----------|-----------|-------------|
| API Baseline (per deploy) | ~30 runs/month | $60 - $150 |
| Weekly full suite | 4 runs/month | $44 - $100 |
| Monthly peak load | 1 run/month | $50 - $100 |
| Ad-hoc testing | ~5 runs/month | $10 - $25 |
| **Total** | | **$164 - $375/month** |

### Cost Optimization Strategies

1. **Use SES mailbox simulator addresses** (`success@simulator.amazonses.com`) for all outbound sends -- these do not count against SES sending quota and are free.

2. **Clean up test data immediately** after each run. The Artillery `afterScenario` hook deletes inboxes created during tests, preventing DynamoDB storage accumulation.

3. **Use on-demand DynamoDB** for the load-test environment. On-demand pricing only charges for actual reads/writes, making it cheaper than provisioned capacity for intermittent test workloads.

4. **Run Artillery distributed mode only for Scenario 6.** Scenarios 1-5 generate sufficient load from a single machine (or GitHub Actions runner). The 20-Lambda distributed mode for peak load costs ~$15-20 just for the Artillery workers.

5. **Tag all load-test resources** with `Environment: loadtest` and `Purpose: load-testing` for cost allocation tracking.

```bash
# View load testing costs for the current month
aws ce get-cost-and-usage \
  --time-period Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
  --granularity MONTHLY \
  --filter '{
    "Tags": {
      "Key": "Purpose",
      "Values": ["load-testing"]
    }
  }' \
  --metrics "UnblendedCost" \
  --region us-east-1
```
