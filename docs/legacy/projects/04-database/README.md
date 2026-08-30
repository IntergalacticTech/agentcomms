# Database & Storage

AgentMail's data layer is built on three AWS services: DynamoDB for metadata and transactional data, S3 for large objects (email bodies, attachments, exports), and ElastiCache Redis for caching and ephemeral state. This combination provides single-digit millisecond reads at any scale, unlimited object storage with lifecycle management, and sub-millisecond cache access for hot paths.

---

## Architecture Summary

```
Lambda Functions
    |
    +--- DynamoDB (single table) ---> DynamoDB Streams ---> OpenSearch indexing
    |                                                   |-> Event sourcing
    |
    +--- S3 (4 buckets) ---> Lifecycle policies ---> Glacier/Delete
    |       raw-email, attachments, bodies, exports
    |
    +--- ElastiCache Redis (cluster mode)
            auth cache, rate limits, routing, quotas
```

---

## Sub-Documents

| Document | Description |
|----------|-------------|
| [DynamoDB Design](./dynamodb-design.md) | Single-table design, complete entity layouts, GSI strategy, access patterns, capacity planning, streams, and backups |
| [S3 Storage](./s3-storage.md) | Bucket structure, key patterns, lifecycle policies, encryption, access control, replication, virus scanning, and cost optimization |
| [Caching](./caching.md) | ElastiCache Redis configuration, cache key patterns, TTLs, invalidation strategy, and high availability |

---

## Key Design Decisions

1. **Single-table DynamoDB over multi-table or Aurora.** A single table with composite keys and GSIs supports all access patterns with predictable performance at any scale. Aurora would add connection pooling complexity and per-hour cost even at zero traffic. Multi-table DynamoDB would lose the ability to do transactional writes across entity types.

2. **S3 for all content larger than 400 KB.** DynamoDB's 400 KB item limit makes it unsuitable for email bodies and attachments. S3 provides unlimited object storage at $0.023/GB with lifecycle transitions to reduce long-term cost.

3. **Redis for all ephemeral state.** API key auth lookups, rate limit counters, inbox routing, and WebSocket connection state all live in Redis. This keeps DynamoDB reserved for durable data and avoids hot-partition issues on high-frequency reads.

4. **DynamoDB Streams for event sourcing.** Every write to DynamoDB produces a stream record that feeds into OpenSearch indexing, webhook delivery, and real-time notifications. This decouples the write path from downstream processing.

5. **On-demand capacity to start, provisioned at scale.** On-demand pricing is simpler and handles unpredictable traffic. Once traffic patterns stabilize, switching to provisioned capacity with auto-scaling can reduce costs by 50-70%.

---

## Data Volume Estimates

| Scale Tier | Inboxes | Messages/Day | DynamoDB Items | S3 Objects/Month | Redis Memory |
|------------|---------|-------------|----------------|------------------|--------------|
| Startup | 100K | 100K | ~10M | ~3M | 2 GB |
| Growth | 1M | 1M | ~100M | ~30M | 8 GB |
| Full Scale | 10M | 10M | ~1B | ~300M | 32 GB |
