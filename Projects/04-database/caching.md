# Caching Architecture

Complete caching architecture using Amazon ElastiCache for Redis, covering configuration, cache use cases, key patterns, TTLs, invalidation strategy, Redis vs DAX analysis, and high availability.

---

## ElastiCache Redis Configuration

### Cluster Specification

| Property | Value |
|----------|-------|
| Engine | Redis 7.x (OSS) |
| Mode | Cluster mode enabled |
| Shards | 2 (scales to 8) |
| Replicas per shard | 2 (1 primary + 2 replicas) |
| Total nodes | 6 (2 primary + 4 replica) |
| Instance type | cache.r7g.large (6.38 GB RAM, 2 vCPU) |
| Total memory | ~38 GB (6 nodes x 6.38 GB) |
| Usable memory | ~30 GB (after Redis overhead) |
| Encryption in transit | Enabled (TLS) |
| Encryption at rest | Enabled (AWS-managed key) |
| Auth | Redis AUTH token (stored in Secrets Manager) |
| Multi-AZ | Enabled (replicas in different AZs) |
| Auto-failover | Enabled |
| Backup | Daily snapshot, 7-day retention |
| Maintenance window | Sun 03:00-05:00 UTC |
| Parameter group | Custom (see below) |

### CloudFormation

```yaml
Resources:
  RedisSubnetGroup:
    Type: AWS::ElastiCache::SubnetGroup
    Properties:
      Description: AgentMail Redis subnet group
      SubnetIds:
        - !Ref PrivateSubnet1
        - !Ref PrivateSubnet2
        - !Ref PrivateSubnet3

  RedisSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: AgentMail Redis security group
      VpcId: !Ref VPC
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 6379
          ToPort: 6379
          SourceSecurityGroupId: !Ref LambdaSecurityGroup

  RedisParameterGroup:
    Type: AWS::ElastiCache::ParameterGroup
    Properties:
      CacheParameterGroupFamily: redis7
      Description: AgentMail Redis parameters
      Properties:
        maxmemory-policy: volatile-lru
        notify-keyspace-events: Ex
        tcp-keepalive: 60
        timeout: 300
        hz: 100
        lfu-log-factor: 10

  RedisReplicationGroup:
    Type: AWS::ElastiCache::ReplicationGroup
    Properties:
      ReplicationGroupDescription: AgentMail Redis cluster
      ReplicationGroupId: agentmail-redis
      Engine: redis
      EngineVersion: "7.1"
      CacheNodeType: cache.r7g.large
      NumNodeGroups: 2           # 2 shards
      ReplicasPerNodeGroup: 2    # 2 replicas per shard
      CacheSubnetGroupName: !Ref RedisSubnetGroup
      SecurityGroupIds:
        - !Ref RedisSecurityGroup
      CacheParameterGroupName: !Ref RedisParameterGroup
      AutomaticFailoverEnabled: true
      MultiAZEnabled: true
      TransitEncryptionEnabled: true
      AtRestEncryptionEnabled: true
      AuthToken: !Sub "{{resolve:secretsmanager:agentmail/redis-auth:SecretString:token}}"
      SnapshotRetentionLimit: 7
      SnapshotWindow: "02:00-03:00"
      PreferredMaintenanceWindow: "sun:03:00-sun:05:00"
      Port: 6379
```

### Memory Policy

`volatile-lru` evicts the least-recently-used key among those with a TTL set. This ensures:

- Keys with TTLs (all cache entries) are evicted under memory pressure.
- Keys without TTLs (none in our design) are never evicted.
- LRU approximation keeps the most frequently accessed items in cache.

---

## Cache Use Cases

### 1. API Key Authentication

**Purpose:** Avoid a DynamoDB query on every API request.

| Property | Value |
|----------|-------|
| Key pattern | `auth:{key_hash}` |
| Value | JSON auth context |
| TTL | 300 seconds (5 minutes) |
| Write trigger | Cache miss during Lambda authorizer |
| Invalidation | Explicit delete on key revocation |

**Key:**
```
auth:a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456
```

**Value:**
```json
{
  "org_id": "01HXYZ1234567890ABCDEFGHJK",
  "key_id": "01HXYZ1234567890ABCDEFGHJL",
  "scope": "org",
  "scope_resource_id": null,
  "environment": "live",
  "tier": "pro"
}
```

**Flow:**
```python
def get_auth_context(key_hash: str) -> dict | None:
    # Try cache first
    cached = redis_client.get(f"auth:{key_hash}")
    if cached:
        return json.loads(cached)

    # Cache miss: query DynamoDB
    item = query_api_key_by_hash(key_hash)
    if not item or item["status"] != "active":
        return None

    context = build_auth_context(item)

    # Write to cache
    redis_client.setex(
        f"auth:{key_hash}",
        300,  # 5 minute TTL
        json.dumps(context),
    )

    return context
```

**Impact:** Reduces DynamoDB reads by ~95% for authentication (most keys are used repeatedly within 5 minutes).

---

### 2. Rate Limit Counters

**Purpose:** Track per-org, per-endpoint request counts using the sliding window algorithm.

| Property | Value |
|----------|-------|
| Key pattern | `rl:{org_id}:{endpoint_group}:{window_start}` |
| Value | Integer counter |
| TTL | 2x window duration |
| Write trigger | Every API request (via Lua script) |
| Invalidation | Automatic via TTL |

**Key:**
```
rl:01HXYZ1234567890ABCDEFGHJK:read:1712764800
rl:01HXYZ1234567890ABCDEFGHJK:read:1712764860
```

**Value:**
```
47
```

The TTL is set to 2x the window size because the sliding window algorithm needs the previous window's count to calculate the weighted estimate. A 60-second window gets a 120-second TTL.

**Memory estimate:** ~100 bytes per counter. At 10,000 active orgs with 6 endpoint groups and 2 windows each: ~12 MB.

---

### 3. Inbox Routing

**Purpose:** Map email addresses to inbox IDs for inbound email processing without a DynamoDB query.

| Property | Value |
|----------|-------|
| Key pattern | `addr:{email_address}` |
| Value | JSON with inbox_id, org_id, pod_id, status |
| TTL | 600 seconds (10 minutes) |
| Write trigger | Cache miss during inbound email processing |
| Invalidation | Explicit delete on inbox update/delete |

**Key:**
```
addr:agent-47@mail.acme.com
```

**Value:**
```json
{
  "inbox_id": "01HXYZ1234567890ABCDEFGHJA",
  "org_id": "01HXYZ1234567890ABCDEFGHJK",
  "pod_id": "01HXYZ1234567890ABCDEFGHJP",
  "status": "active"
}
```

**Flow:**
```python
def resolve_inbox(email_address: str) -> dict | None:
    # Try cache
    cached = redis_client.get(f"addr:{email_address}")
    if cached:
        data = json.loads(cached)
        if data["status"] != "active":
            return None  # Inbox disabled
        return data

    # Cache miss: query DynamoDB GSI2
    result = table.query(
        IndexName="GSI2",
        KeyConditionExpression="GSI2PK = :pk",
        ExpressionAttributeValues={":pk": f"EMAIL#{email_address}"},
        Limit=1,
    )

    if not result["Items"]:
        return None

    item = result["Items"][0]
    data = {
        "inbox_id": item["id"],
        "org_id": item["org_id"],
        "pod_id": item["pod_id"],
        "status": item["status"],
    }

    redis_client.setex(f"addr:{email_address}", 600, json.dumps(data))
    return data if data["status"] == "active" else None
```

**Impact:** Critical for inbound email latency. Reduces the p99 processing time from ~15ms (DynamoDB GSI2 query) to ~1ms (Redis GET) for known addresses.

---

### 4. Organization Settings

**Purpose:** Cache org-level settings (quotas, tier, feature flags) to avoid repeated DynamoDB reads.

| Property | Value |
|----------|-------|
| Key pattern | `org:{org_id}:settings` |
| Value | JSON with settings, quotas, tier |
| TTL | 300 seconds (5 minutes) |
| Write trigger | Cache miss in Lambda handlers |
| Invalidation | Explicit delete on org settings update |

**Key:**
```
org:01HXYZ1234567890ABCDEFGHJK:settings
```

**Value:**
```json
{
  "tier": "pro",
  "settings": {
    "default_domain": "mail.acme.com",
    "retention_days": 365,
    "ai_categorization_enabled": true,
    "max_attachment_size_mb": 25
  },
  "quotas": {
    "max_inboxes": 100000,
    "max_messages_per_day": 100000,
    "max_api_keys": 50,
    "max_pods": 100
  }
}
```

---

### 5. Quota Counters

**Purpose:** Track daily message send/receive counts for quota enforcement without aggregating DynamoDB records.

| Property | Value |
|----------|-------|
| Key pattern | `quota:{org_id}:msgs:{date}` |
| Value | Integer counter |
| TTL | 172800 seconds (48 hours) |
| Write trigger | INCR on every message send/receive |
| Invalidation | Automatic via TTL |

**Key:**
```
quota:01HXYZ1234567890ABCDEFGHJK:msgs:2026-04-10
```

**Value:**
```
8432
```

**Flow:**
```python
def check_and_increment_quota(org_id: str, max_daily: int) -> bool:
    """
    Check if the org is under quota and increment the counter.
    Returns True if allowed, False if quota exceeded.
    """
    date = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"quota:{org_id}:msgs:{date}"

    # Atomic increment + check
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, 172800)  # 48h TTL (covers timezone edge cases)
    results = pipe.execute()

    current_count = results[0]

    if current_count > max_daily:
        # Over quota: decrement back (or just let it be, since we check > not >=)
        redis_client.decr(key)
        return False

    return True
```

**Durability consideration:** If Redis loses this counter (failover, restart), the org temporarily loses quota tracking. This is acceptable because:
- Quotas are soft limits (a few extra messages above quota are tolerable).
- The counter recovers naturally as new messages increment it.
- DynamoDB can be queried as a fallback for exact counts if needed.

---

### 6. WebSocket Connection Registry

**Purpose:** Track which WebSocket connections are subscribed to which channels for real-time event fan-out.

| Property | Value |
|----------|-------|
| Key pattern | `ws:conn:{connection_id}` (connection metadata), `ws:channel:{channel}` (set of connection IDs) |
| Value | JSON / Redis SET |
| TTL | 3600 seconds (1 hour), refreshed on each ping |
| Write trigger | WebSocket connect/subscribe/disconnect |
| Invalidation | Explicit on disconnect + TTL fallback |

```python
def subscribe(connection_id: str, channels: list[str], org_id: str):
    pipe = redis_client.pipeline()

    # Store connection metadata
    pipe.setex(
        f"ws:conn:{connection_id}",
        3600,
        json.dumps({"org_id": org_id, "channels": channels}),
    )

    # Add to each channel's subscriber set
    for channel in channels:
        pipe.sadd(f"ws:channel:{channel}", connection_id)
        pipe.expire(f"ws:channel:{channel}", 3600)

    pipe.execute()


def fan_out(channel: str, event: dict):
    """Send an event to all connections subscribed to a channel."""
    connection_ids = redis_client.smembers(f"ws:channel:{channel}")

    api_gw = boto3.client("apigatewaymanagementapi", endpoint_url=WS_ENDPOINT)

    for conn_id in connection_ids:
        try:
            api_gw.post_to_connection(
                ConnectionId=conn_id,
                Data=json.dumps(event).encode(),
            )
        except api_gw.exceptions.GoneException:
            # Connection is stale, clean up
            unsubscribe(conn_id)
```

---

## Cache Key Summary

| Use Case | Key Pattern | Value Type | TTL | Size Estimate |
|----------|-------------|-----------|-----|---------------|
| API key auth | `auth:{key_hash}` | JSON | 5 min | ~200 bytes |
| Rate limit | `rl:{org_id}:{group}:{window}` | integer | 2x window | ~50 bytes |
| Inbox routing | `addr:{email}` | JSON | 10 min | ~150 bytes |
| Org settings | `org:{org_id}:settings` | JSON | 5 min | ~500 bytes |
| Quota counter | `quota:{org_id}:msgs:{date}` | integer | 48 hours | ~50 bytes |
| WS connection | `ws:conn:{conn_id}` | JSON | 1 hour | ~200 bytes |
| WS channel | `ws:channel:{channel}` | SET | 1 hour | ~50 bytes per member |

### Memory Estimates by Scale

| Scale | Auth Keys | Rate Limits | Routing | Org Settings | Quotas | WebSocket | Total |
|-------|-----------|------------|---------|-------------|--------|-----------|-------|
| Startup | 5 MB | 12 MB | 50 MB | 1 MB | 1 MB | 5 MB | ~74 MB |
| Growth | 20 MB | 60 MB | 200 MB | 5 MB | 5 MB | 20 MB | ~310 MB |
| Full Scale | 100 MB | 300 MB | 1 GB | 20 MB | 20 MB | 100 MB | ~1.5 GB |

Plenty of headroom with 30 GB usable memory. The remaining capacity is available for future cache use cases (e.g., hot message body caching).

---

## Cache Invalidation Strategy

### Write-Through Invalidation

When data is modified, the corresponding cache entry is explicitly deleted (not updated). The next read repopulates the cache from DynamoDB.

```python
def update_inbox(org_id: str, inbox_id: str, updates: dict):
    # 1. Update DynamoDB
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"INBOX#{inbox_id}"},
        # ... update expression
    )

    # 2. Invalidate cache
    inbox = get_inbox_from_db(inbox_id)
    redis_client.delete(f"addr:{inbox['email']}")

    # Don't bother updating the cache -- let the next read repopulate it.
```

### Why Delete Instead of Update

1. **Simplicity.** Deleting is a single operation. Updating requires re-serializing the full value.
2. **Consistency.** If the DynamoDB write succeeds but the cache update fails, the cache is stale. With delete, a failed delete just means the cache returns slightly stale data that will expire via TTL.
3. **Race conditions.** Two concurrent updates could result in the cache reflecting the wrong final state. Delete-and-repopulate avoids this.

### Invalidation Triggers

| Event | Cache Keys Invalidated |
|-------|----------------------|
| API key revoked | `auth:{key_hash}` |
| API key created | None (cache miss populates on first use) |
| Inbox created | None (cache miss populates on first inbound email) |
| Inbox updated | `addr:{inbox_email}` |
| Inbox deleted | `addr:{inbox_email}` |
| Org settings updated | `org:{org_id}:settings` |
| Org tier changed | `org:{org_id}:settings`, all `auth:*` for this org (via key scan) |
| WebSocket disconnect | `ws:conn:{connection_id}`, remove from `ws:channel:*` sets |

### Stale Cache Tolerance

All cache entries have TTLs, so stale data is bounded:

| Cache | Max Stale Duration | Impact of Stale Data |
|-------|-------------------|---------------------|
| API key auth | 5 minutes | Revoked key works for up to 5 min (mitigated by explicit invalidation) |
| Rate limits | N/A | Counters are always current (atomic Lua script) |
| Inbox routing | 10 minutes | Deleted inbox receives email for up to 10 min (mitigated by explicit invalidation) |
| Org settings | 5 minutes | Changed settings take up to 5 min to propagate |
| Quotas | N/A | Counters are always current (atomic INCR) |

---

## Redis vs DAX Analysis

| Criteria | ElastiCache Redis | DynamoDB Accelerator (DAX) |
|----------|------------------|---------------------------|
| Latency | Sub-millisecond | Sub-millisecond |
| Use case fit | Multiple use cases (auth, rate limiting, routing, pub/sub, counters) | DynamoDB read caching only |
| Lua scripting | Yes (sliding window, atomic operations) | No |
| Data structures | Strings, hashes, sets, sorted sets, lists | Key-value only |
| Pub/Sub | Yes (WebSocket fan-out) | No |
| Rate limiting | Native via Lua scripts | Not designed for this |
| Cost (6 nodes, r7g.large) | ~$1,400/month | ~$1,800/month (DAX r-type nodes cost more) |
| Operational control | Full Redis command set | Limited to DynamoDB API subset |
| Cache invalidation | Explicit DELETE, TTL, LRU eviction | Automatic (write-through), TTL |
| Multi-purpose | Yes | No (DynamoDB reads only) |

**Decision: Redis.** DAX excels at transparently caching DynamoDB reads, but AgentMail needs Redis for rate limiting (Lua scripts), WebSocket state (sets + pub/sub), and general-purpose caching. Using DAX for DynamoDB reads and Redis for everything else would double the operational surface area and cost. Redis alone covers all use cases.

---

## Failover and High Availability

### Multi-AZ Deployment

The Redis cluster is deployed across 3 availability zones:

```
AZ-1 (us-east-1a)     AZ-2 (us-east-1b)     AZ-3 (us-east-1c)
+------------------+   +------------------+   +------------------+
| Shard 1 Primary  |   | Shard 1 Replica  |   | Shard 1 Replica  |
| Shard 2 Replica  |   | Shard 2 Primary  |   | Shard 2 Replica  |
+------------------+   +------------------+   +------------------+
```

### Automatic Failover

When a primary node fails:

1. ElastiCache detects the failure (within ~30 seconds).
2. One of the replicas is promoted to primary.
3. A new replica is launched to replace the promoted one.
4. DNS endpoint is updated automatically.
5. The Redis client reconnects transparently.

**Failover time:** 30-60 seconds. During this window:
- Auth cache misses fall back to DynamoDB (adds ~10ms latency).
- Rate limit counters reset (briefly allows burst above limits).
- Quota counters lose partial counts (acceptable -- soft limits).
- WebSocket connections may drop and reconnect.

### Client Resilience

Lambda functions handle Redis failures gracefully:

```python
import redis
from redis.exceptions import ConnectionError, TimeoutError

redis_client = redis.Redis(
    host=os.environ["REDIS_HOST"],
    port=6379,
    ssl=True,
    socket_timeout=1.0,        # 1 second timeout
    socket_connect_timeout=1.0,
    retry_on_timeout=True,
    retry=redis.retry.Retry(
        retries=2,
        backoff=redis.backoff.ExponentialBackoff(base=0.1, cap=1.0),
    ),
    decode_responses=True,
)


def get_with_fallback(cache_key: str, fallback_fn):
    """Try Redis cache, fall back to DynamoDB on failure."""
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except (ConnectionError, TimeoutError):
        # Redis is down -- fall back silently
        pass

    # Fall back to DynamoDB
    result = fallback_fn()

    # Try to populate cache (but don't fail if Redis is still down)
    try:
        redis_client.setex(cache_key, 300, json.dumps(result))
    except (ConnectionError, TimeoutError):
        pass

    return result
```

### Monitoring

| Metric | Alarm Threshold | Action |
|--------|----------------|--------|
| `EngineCPUUtilization` | > 80% for 5 min | Scale up instance type |
| `DatabaseMemoryUsagePercentage` | > 75% | Add shards or scale up |
| `CurrConnections` | > 5000 | Investigate connection leak |
| `CacheHitRate` | < 80% | Review TTLs and access patterns |
| `ReplicationLag` | > 1 second | Investigate network / load issues |
| `Evictions` | > 0 sustained | Scale up memory |
| `FailoverCount` | > 0 | Investigate root cause |
