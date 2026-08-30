# Real-Time Event System

AgentMail's real-time event system provides millisecond-latency delivery of platform events to customer endpoints via webhooks, WebSocket connections, and internal consumers. Every meaningful state change -- an inbound email, a bounce notification, a completed AI processing run, a domain verification -- flows through a central Kinesis Data Streams event bus and fans out to all interested consumers with guaranteed per-inbox ordering and 7-day replay capability.

The event system is the connective tissue between the email transport layer and the outside world. Without it, customers would need to poll the API to detect new messages. With it, AI agents can react to incoming email in under two seconds.

---

## Architecture

```
                          ┌──────────────────────────────────────────────┐
                          │              EVENT SOURCES                   │
                          │                                              │
                          │  SES Notifications ──→ SNS ──→ SQS          │
                          │  API Mutations (send, delete, etc.)          │
                          │  Domain Verification Poller                  │
                          │  AI Processing Pipeline (Step Functions)     │
                          └──────────────────┬───────────────────────────┘
                                             │
                                             ▼
                                   ┌──────────────────┐
                                   │  Lambda           │
                                   │  Event Normalizer │
                                   │  (maps → unified  │
                                   │   event schema)   │
                                   └────────┬─────────┘
                                            │
                                            ▼
                               ┌────────────────────────┐
                               │   Kinesis Data Streams  │
                               │   agentmail-events      │
                               │                         │
                               │   4 shards (auto-scale) │
                               │   Partition: inboxId    │
                               │   Retention: 7 days     │
                               │   Encryption: KMS       │
                               └────────────┬────────────┘
                                            │
                     ┌──────────────────────┬┼──────────────────────┐
                     │                      ││                      │
                     ▼                      ▼│                      ▼
          ┌──────────────────┐  ┌───────────▼────────┐  ┌──────────────────┐
          │ Enhanced Fan-Out │  │ Enhanced Fan-Out   │  │ Enhanced Fan-Out │
          │ Consumer:        │  │ Consumer:          │  │ Consumer:        │
          │ webhook-pipeline │  │ websocket-pipeline │  │ analytics        │
          └────────┬─────────┘  └────────┬───────────┘  └────────┬─────────┘
                   │                     │                        │
                   ▼                     ▼                        ▼
          ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
          │ SQS Queue    │    │ DynamoDB Lookup   │    │ Kinesis Firehose │
          │ per endpoint │    │ (subscriptions)   │    │ → S3 (archive)   │
          │      │       │    │      │            │    └──────────────────┘
          │      ▼       │    │      ▼            │
          │ Lambda       │    │ API GW WebSocket  │
          │ webhook-send │    │ @connections POST │
          │      │       │    └──────────────────┘
          │      ▼       │
          │ Customer URL │
          └──────────────┘

          ┌──────────────────┐
          │ Enhanced Fan-Out │
          │ Consumer:        │
          │ event-archive    │────→ Kinesis Firehose ────→ S3 (parquet)
          └──────────────────┘
```

---

## Sub-Documents

| Document | Description |
|----------|-------------|
| [Event Bus](./event-bus.md) | Central Kinesis Data Streams architecture: stream configuration, event schema, all event types, partition strategy, ingestion pipeline, replay, archival, and scaling |
| [Webhooks](./webhooks.md) | Webhook delivery system: data model, fan-out algorithm, HMAC signing, retry strategy, endpoint validation, dead letter handling, delivery logging, and performance budget |
| [WebSockets](./websockets.md) | WebSocket system: API Gateway WebSocket API, connection lifecycle, subscription model, event routing, heartbeat, reconnection/replay, scaling, and failure modes |

---

## Key Design Decisions

1. **Kinesis Data Streams over EventBridge and SNS.** The event bus must guarantee per-inbox ordering (EventBridge does not order), support 7-day replay for reconnecting clients (SNS does not persist), and deliver dedicated per-consumer throughput via enhanced fan-out (both SNS and EventBridge hit throughput limits at 100K events/minute). Kinesis is the only AWS service that satisfies all three.

2. **Unified event schema for all event types.** Every event -- whether it originates from SES, the API, or the AI pipeline -- is normalized into a single JSON schema before entering Kinesis. Consumers never need to understand SES notification formats, DynamoDB stream shapes, or Step Functions output. They see one schema.

3. **Enhanced fan-out for consumer isolation.** Each consumer (webhooks, WebSockets, analytics, archive) gets a dedicated 2 MB/sec read throughput via Kinesis enhanced fan-out. A slow webhook consumer cannot block WebSocket delivery. A backlogged analytics pipeline cannot delay customer-facing events.

4. **SQS buffering between dispatch and delivery.** Webhook and WebSocket dispatchers write to SQS queues rather than calling customer endpoints directly. This decouples dispatch latency from delivery latency, enables per-endpoint retry with exponential backoff, and prevents a single slow customer endpoint from blocking event processing for everyone.

5. **DynamoDB for connection and subscription state.** WebSocket connection records and subscription mappings live in DynamoDB, not Redis. While Redis would be faster, DynamoDB provides durability across Lambda invocations without managing connection pools, and the access patterns (point reads by connection ID, queries by subscription channel) fit DynamoDB's model perfectly.

---

## Performance Targets

| Metric | Target | Typical |
|--------|--------|---------|
| Event ingestion to Kinesis | < 500ms | ~300ms |
| Kinesis to webhook delivery | < 5s | ~1.2s |
| Kinesis to WebSocket push | < 2s | ~500ms |
| End-to-end (SES notification to webhook) | < 6s | ~1.5s |
| End-to-end (SES notification to WebSocket) | < 3s | ~800ms |
| Event replay start (reconnecting client) | < 2s | ~1s |

---

## Cost Summary

| Service | Monthly Cost (100K events/min) |
|---------|-------------------------------|
| Kinesis (4 shards, enhanced fan-out, 7-day retention) | ~$200 |
| Lambda (normalizers + dispatchers + senders) | ~$1,500 |
| DynamoDB (endpoints + connections + delivery logs) | ~$400 |
| SQS (webhook queues + DLQs) | ~$120 |
| API Gateway WebSocket (100K concurrent connections) | ~$600 |
| Kinesis Firehose (archive to S3) | ~$180 |
| **Total** | **~$3,000/mo** |
