# WebSocket System

The AgentMail WebSocket system provides real-time event streaming to connected clients via API Gateway WebSocket APIs. AI agents and developer applications establish persistent connections, subscribe to channels at inbox, pod, or organization granularity, and receive events pushed from the Kinesis event bus within milliseconds. The system supports 100K+ concurrent connections, server-initiated heartbeats, and automatic replay of missed events on reconnection.

---

## API Gateway WebSocket API Configuration

```json
{
  "Name": "agentmail-websocket-api",
  "ProtocolType": "WEBSOCKET",
  "RouteSelectionExpression": "$request.body.action",
  "ApiKeySelectionExpression": "$request.header.x-api-key",
  "Tags": {
    "Service": "agentmail",
    "Component": "websocket"
  }
}
```

### Routes

| Route | Integration | Purpose |
|-------|-------------|---------|
| `$connect` | Lambda: `agentmail-ws-connect` | Authentication, connection registration |
| `$default` | Lambda: `agentmail-ws-default` | Subscribe/unsubscribe to channels |
| `$disconnect` | Lambda: `agentmail-ws-disconnect` | Cleanup connection and subscription records |

### Stage Configuration

```json
{
  "StageName": "v1",
  "DefaultRouteSettings": {
    "ThrottlingBurstLimit": 5000,
    "ThrottlingRateLimit": 10000
  },
  "StageVariables": {
    "TABLE_NAME": "agentmail",
    "REDIS_HOST": "agentmail-redis.xxxxx.use1.cache.amazonaws.com"
  }
}
```

WebSocket endpoint: `wss://ws.agentmail.aws/v1`

Management API endpoint: `https://ws-manage.agentmail.aws/v1` (for `@connections` POST)

---

## Connection Flow

### $connect -- Authentication and Registration

```
Client: wss://ws.agentmail.aws/v1?apiKey=ak_01JRWX...&lastEventId=evt_01JRWX...
    │
    ▼
API Gateway: $connect route
    │
    ▼
Lambda Authorizer: agentmail-ws-authorizer
    │
    │  1. Extract apiKey from query string parameter
    │  2. Validate API key against Redis cache (DynamoDB fallback)
    │  3. Resolve org context: orgId, allowed podIds, allowed inboxIds
    │  4. Return IAM policy with orgId in context
    │
    ▼ (authorized)
Lambda: agentmail-ws-connect
    │
    │  1. Extract connectionId from requestContext
    │  2. Extract lastEventId from query parameters (optional)
    │  3. Store connection record in DynamoDB:
    │     PK: CONN#{connectionId}
    │     SK: META
    │     orgId, apiKeyId, connectedAt, lastPingAt, subscriptions: []
    │  4. If lastEventId provided, trigger replay (see Reconnection section)
    │  5. Return { statusCode: 200 }
    │
    ▼
Client: Connection established
```

### Lambda Authorizer

```python
import json
import os
import time

import boto3

redis_client = None
dynamodb = boto3.resource("dynamodb")


def handler(event, context):
    """API Gateway WebSocket Lambda authorizer.
    
    Extracts API key from query string, validates it, and returns
    an IAM policy that gates access to the WebSocket routes.
    """
    # Extract API key from query string
    query_params = event.get("queryStringParameters", {}) or {}
    api_key = query_params.get("apiKey")
    
    if not api_key:
        # Also check headers for API key
        headers = event.get("headers", {}) or {}
        api_key = headers.get("x-api-key") or headers.get("X-Api-Key")
    
    if not api_key:
        raise Exception("Unauthorized")  # Returns 401
    
    # Validate API key
    key_data = _lookup_api_key(api_key)
    if not key_data:
        raise Exception("Unauthorized")
    
    # Check if key is active
    if key_data.get("status") != "active":
        raise Exception("Unauthorized")
    
    # Build IAM policy
    method_arn = event["methodArn"]
    # Allow access to all routes for this WebSocket API
    arn_parts = method_arn.split(":")
    region = arn_parts[3]
    account_id = arn_parts[4]
    api_gateway_arn = arn_parts[5].split("/")
    api_id = api_gateway_arn[0]
    stage = api_gateway_arn[1]
    
    policy = {
        "principalId": key_data["orgId"],
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": "Allow",
                    "Resource": f"arn:aws:execute-api:{region}:{account_id}:{api_id}/{stage}/*",
                }
            ],
        },
        "context": {
            "orgId": key_data["orgId"],
            "apiKeyId": key_data["apiKeyId"],
            "allowedPodIds": json.dumps(key_data.get("podIds", [])),
            "allowedInboxIds": json.dumps(key_data.get("inboxIds", [])),
        },
    }
    
    return policy


def _lookup_api_key(api_key: str) -> dict | None:
    """Look up API key from Redis cache or DynamoDB."""
    cache_key = f"apikey:{api_key}"
    
    # Try Redis
    cached = _redis_get(cache_key)
    if cached:
        return json.loads(cached)
    
    # DynamoDB fallback
    table = dynamodb.Table(os.environ["TABLE_NAME"])
    response = table.query(
        IndexName="GSI-apikey",
        KeyConditionExpression="apiKeyHash = :hash",
        ExpressionAttributeValues={
            ":hash": _hash_api_key(api_key),
        },
        Limit=1,
    )
    
    if not response["Items"]:
        return None
    
    item = response["Items"][0]
    result = {
        "orgId": item["orgId"],
        "apiKeyId": item["apiKeyId"],
        "status": item["status"],
        "podIds": item.get("podIds", []),
        "inboxIds": item.get("inboxIds", []),
    }
    
    # Cache for 5 minutes
    _redis_set(cache_key, json.dumps(result), ex=300)
    return result
```

### $default -- Subscribe and Unsubscribe

Clients send JSON messages to subscribe or unsubscribe from event channels:

```json
// Subscribe to a specific inbox
{ "action": "subscribe", "channel": "inbox:inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y" }

// Subscribe to all events in a pod
{ "action": "subscribe", "channel": "pod:pod_01JRQ4G9N3PYKC7Q4D8E0F1J6X" }

// Subscribe to all events in the organization
{ "action": "subscribe", "channel": "org:org_01JRQ4F8M2NXKB6P3C7D9E0H5W" }

// Unsubscribe
{ "action": "unsubscribe", "channel": "inbox:inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y" }
```

```python
def handle_default(event, context):
    """Handle subscribe/unsubscribe messages on $default route."""
    connection_id = event["requestContext"]["connectionId"]
    org_id = event["requestContext"]["authorizer"]["orgId"]
    
    body = json.loads(event.get("body", "{}"))
    action = body.get("action")
    channel = body.get("channel", "")
    
    if action == "subscribe":
        return handle_subscribe(connection_id, org_id, channel, event)
    elif action == "unsubscribe":
        return handle_unsubscribe(connection_id, org_id, channel)
    elif action == "ping":
        return send_to_connection(connection_id, {"type": "pong", "timestamp": int(time.time())})
    else:
        return send_to_connection(connection_id, {
            "type": "error",
            "message": f"Unknown action: {action}. Valid actions: subscribe, unsubscribe, ping"
        })


def handle_subscribe(connection_id: str, org_id: str, channel: str, event: dict):
    """Subscribe a connection to a channel.
    
    Validates that the connection's API key has access to the requested scope,
    then writes subscription records for bidirectional lookup.
    """
    # Parse channel
    parts = channel.split(":", 1)
    if len(parts) != 2 or parts[0] not in ("inbox", "pod", "org"):
        return send_to_connection(connection_id, {
            "type": "error",
            "message": "Invalid channel format. Use inbox:{id}, pod:{id}, or org:{id}"
        })
    
    scope_type, scope_id = parts
    
    # Authorization: verify the connection's org matches
    if scope_type == "org" and scope_id != org_id:
        return send_to_connection(connection_id, {
            "type": "error", "message": "Unauthorized: org mismatch"
        })
    
    # Check pod/inbox access if scoped API key
    authorizer = event["requestContext"]["authorizer"]
    allowed_pods = json.loads(authorizer.get("allowedPodIds", "[]"))
    allowed_inboxes = json.loads(authorizer.get("allowedInboxIds", "[]"))
    
    if scope_type == "pod" and allowed_pods and scope_id not in allowed_pods:
        return send_to_connection(connection_id, {
            "type": "error", "message": "Unauthorized: pod not in API key scope"
        })
    
    if scope_type == "inbox" and allowed_inboxes and scope_id not in allowed_inboxes:
        return send_to_connection(connection_id, {
            "type": "error", "message": "Unauthorized: inbox not in API key scope"
        })
    
    # Dual write: subscription record + update connection record
    now = datetime.utcnow().isoformat() + "Z"
    
    table.transact_write_items(TransactItems=[
        # Subscription record (for event routing: "find all connections for this inbox")
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": {
                    "PK": f"SUB#{scope_type}#{scope_id}",
                    "SK": f"CONN#{connection_id}",
                    "orgId": org_id,
                    "channel": channel,
                    "connectionId": connection_id,
                    "subscribedAt": now,
                    "ttl": int(time.time()) + 86400,  # 24h TTL as safety net
                },
            }
        },
        # Update connection record (for cleanup: "find all subscriptions for this connection")
        {
            "Update": {
                "TableName": TABLE_NAME,
                "Key": {"PK": f"CONN#{connection_id}", "SK": "META"},
                "UpdateExpression": "ADD subscriptions :channel",
                "ExpressionAttributeValues": {
                    ":channel": {channel},
                },
            }
        },
    ])
    
    return send_to_connection(connection_id, {
        "type": "subscribed",
        "channel": channel,
    })
```

### $disconnect -- Cleanup

```python
def handle_disconnect(event, context):
    """Clean up connection and all subscription records on disconnect."""
    connection_id = event["requestContext"]["connectionId"]
    
    # Step 1: Get connection record to find all subscriptions
    response = table.get_item(
        Key={"PK": f"CONN#{connection_id}", "SK": "META"}
    )
    
    if "Item" not in response:
        return {"statusCode": 200}
    
    connection = response["Item"]
    subscriptions = connection.get("subscriptions", set())
    
    # Step 2: Delete all subscription records
    delete_requests = []
    for channel in subscriptions:
        scope_type, scope_id = channel.split(":", 1)
        delete_requests.append({
            "DeleteRequest": {
                "Key": {
                    "PK": f"SUB#{scope_type}#{scope_id}",
                    "SK": f"CONN#{connection_id}",
                }
            }
        })
    
    # Step 3: Delete connection record
    delete_requests.append({
        "DeleteRequest": {
            "Key": {"PK": f"CONN#{connection_id}", "SK": "META"}
        }
    })
    
    # Batch delete (25 items per batch)
    for i in range(0, len(delete_requests), 25):
        batch = delete_requests[i:i + 25]
        table.meta.client.batch_write_item(
            RequestItems={TABLE_NAME: batch}
        )
    
    return {"statusCode": 200}
```

---

## DynamoDB Connection Store

The connection store uses a dual-write pattern for bidirectional lookup: given a connection ID, find all its subscriptions; given a channel, find all connections subscribed to it.

### Record Types

#### Connection Record

```
PK: CONN#{connectionId}
SK: META

Attributes:
  connectionId:  "abc123def456"
  orgId:         "org_01JRQ4F8M2NXKB6P3C7D9E0H5W"
  apiKeyId:      "ak_01JRQ4E7L1MWJA5O2B6C8D9F4V"
  connectedAt:   "2026-04-10T14:00:00.000Z"
  lastPingAt:    "2026-04-10T14:29:30.000Z"
  subscriptions: {"inbox:inbox_01JRQ4HA04...", "pod:pod_01JRQ4G9N3..."}  (String Set)
  ttl:           1712843600  (24h safety net)
```

Purpose: $disconnect cleanup (find all subscriptions to delete) and heartbeat tracking (update lastPingAt).

#### Subscription Record

```
PK: SUB#inbox#inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y
SK: CONN#abc123def456

Attributes:
  orgId:         "org_01JRQ4F8M2NXKB6P3C7D9E0H5W"
  channel:       "inbox:inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y"
  connectionId:  "abc123def456"
  subscribedAt:  "2026-04-10T14:00:05.000Z"
  ttl:           1712843600
```

Purpose: Event routing (find all connections that need to receive an event for this inbox).

### Query Patterns

| Query | DynamoDB Operation |
|-------|--------------------|
| All connections for an inbox | Query PK = `SUB#inbox#{inboxId}` |
| All connections for a pod | Query PK = `SUB#pod#{podId}` |
| All connections for an org | Query PK = `SUB#org#{orgId}` |
| All subscriptions for a connection | GetItem PK = `CONN#{connId}`, SK = `META` → read `subscriptions` set |
| Connection exists? | GetItem PK = `CONN#{connId}`, SK = `META` |

### Sizing

| Scale | Concurrent Connections | Subscriptions (avg 3/conn) | Storage | Read Capacity |
|-------|----------------------|---------------------------|---------|---------------|
| Startup | 1,000 | 3,000 | ~1 MB | Negligible |
| Growth | 10,000 | 30,000 | ~10 MB | ~50 RCU |
| Full Scale | 100,000 | 300,000 | ~100 MB | ~500 RCU |

---

## Event Routing

The websocket-pipeline enhanced fan-out consumer receives every event from Kinesis and routes it to the appropriate WebSocket connections.

### Routing Flow

```
Kinesis (enhanced fan-out: websocket-pipeline)
    │
    ▼
Lambda: agentmail-ws-event-dispatcher
    │
    │  For each event:
    │  1. Extract orgId, podId, inboxId from event
    │  2. Query DynamoDB for matching connections at all three scope levels:
    │     - Query PK = SUB#inbox#{inboxId}  → inbox-level subscribers
    │     - Query PK = SUB#pod#{podId}      → pod-level subscribers
    │     - Query PK = SUB#org#{orgId}      → org-level subscribers
    │  3. Deduplicate connection IDs (a connection subscribed to both
    │     inbox:X and pod:Y should receive the event only once)
    │  4. For each unique connection:
    │     POST to @connections/{connectionId} with event payload
    │
    ▼
API Gateway Management API: @connections/{connectionId}
    │
    ▼
Client receives event via WebSocket frame
```

### Dispatcher Implementation

```python
import json
import os
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])
api_gw = boto3.client(
    "apigatewaymanagementapi",
    endpoint_url=os.environ["WEBSOCKET_MANAGEMENT_URL"],
)

MAX_WORKERS = 50  # Parallel @connections posts


def handler(event, context):
    """Kinesis enhanced fan-out consumer for WebSocket event routing."""
    for record in event["Records"]:
        # Decode Kinesis record
        payload = json.loads(base64.b64decode(record["kinesis"]["data"]))
        
        org_id = payload["orgId"]
        pod_id = payload["podId"]
        inbox_id = payload["inboxId"]
        
        # Find all matching connections (three scope levels, parallel)
        connection_ids = set()
        
        scope_queries = []
        if inbox_id and inbox_id != "inbox_none":
            scope_queries.append(f"SUB#inbox#{inbox_id}")
        if pod_id and pod_id != "pod_default":
            scope_queries.append(f"SUB#pod#{pod_id}")
        scope_queries.append(f"SUB#org#{org_id}")
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(query_subscriptions, pk): pk
                for pk in scope_queries
            }
            for future in as_completed(futures):
                conn_ids = future.result()
                connection_ids.update(conn_ids)
        
        if not connection_ids:
            continue  # No subscribers for this event
        
        # Prepare the WebSocket message
        ws_message = json.dumps({
            "type": "event",
            "event": payload,
        }).encode("utf-8")
        
        # Fan out to all connections in parallel
        stale_connections = []
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(post_to_connection, conn_id, ws_message): conn_id
                for conn_id in connection_ids
            }
            for future in as_completed(futures):
                conn_id = futures[future]
                try:
                    result = future.result()
                    if result == "gone":
                        stale_connections.append(conn_id)
                except Exception as e:
                    print(f"Error posting to {conn_id}: {e}")
        
        # Clean up stale connections
        for conn_id in stale_connections:
            cleanup_stale_connection(conn_id)


def query_subscriptions(pk: str) -> set:
    """Query all connection IDs subscribed to a given scope."""
    connection_ids = set()
    response = table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": pk},
        ProjectionExpression="connectionId",
    )
    for item in response.get("Items", []):
        connection_ids.add(item["connectionId"])
    
    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": pk},
            ProjectionExpression="connectionId",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        for item in response.get("Items", []):
            connection_ids.add(item["connectionId"])
    
    return connection_ids


def post_to_connection(connection_id: str, data: bytes) -> str:
    """Post a message to a WebSocket connection.
    
    Returns "ok" on success, "gone" if the connection is stale (410).
    """
    try:
        api_gw.post_to_connection(
            ConnectionId=connection_id,
            Data=data,
        )
        return "ok"
    except api_gw.exceptions.GoneException:
        return "gone"
    except Exception as e:
        print(f"Failed to post to connection {connection_id}: {e}")
        raise


def cleanup_stale_connection(connection_id: str):
    """Remove a stale connection and all its subscription records.
    
    Called when @connections POST returns 410 GoneException,
    indicating the client has disconnected but $disconnect
    was not called (e.g., network failure).
    """
    # Get connection record
    response = table.get_item(
        Key={"PK": f"CONN#{connection_id}", "SK": "META"}
    )
    
    if "Item" not in response:
        return
    
    connection = response["Item"]
    subscriptions = connection.get("subscriptions", set())
    
    # Delete subscription records
    with table.batch_writer() as batch:
        for channel in subscriptions:
            scope_type, scope_id = channel.split(":", 1)
            batch.delete_item(Key={
                "PK": f"SUB#{scope_type}#{scope_id}",
                "SK": f"CONN#{connection_id}",
            })
        
        # Delete connection record
        batch.delete_item(Key={
            "PK": f"CONN#{connection_id}",
            "SK": "META",
        })
    
    print(f"Cleaned up stale connection {connection_id} with {len(subscriptions)} subscriptions")
```

### Lambda Configuration

```json
{
  "FunctionName": "agentmail-ws-event-dispatcher",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 1024,
  "Timeout": 60,
  "ReservedConcurrentExecutions": 20,
  "ProvisionedConcurrencyConfig": {
    "ProvisionedConcurrentExecutions": 5
  },
  "Environment": {
    "Variables": {
      "TABLE_NAME": "agentmail",
      "WEBSOCKET_MANAGEMENT_URL": "https://ws-manage.agentmail.aws/v1"
    }
  },
  "VpcConfig": {
    "SubnetIds": ["subnet-private-1", "subnet-private-2"],
    "SecurityGroupIds": ["sg-lambda"]
  }
}
```

---

## Heartbeat

The server sends periodic ping messages to detect dead connections. API Gateway WebSocket connections have a default idle timeout of 10 minutes, but clients can silently disconnect without sending a close frame (e.g., network failure, process crash).

### Heartbeat Schedule

```
CloudWatch Events Rule: agentmail-ws-heartbeat
  Schedule: rate(30 seconds)
  Target: Lambda agentmail-ws-heartbeat
```

### Heartbeat Lambda

```python
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])
api_gw = boto3.client(
    "apigatewaymanagementapi",
    endpoint_url=os.environ["WEBSOCKET_MANAGEMENT_URL"],
)

PING_INTERVAL = 30       # Send ping every 30 seconds
PONG_TIMEOUT = 60        # Terminate after 60 seconds without pong (2 missed pings)
MAX_CONNECTIONS_PER_RUN = 1000  # Process in chunks to avoid Lambda timeout


def handler(event, context):
    """Send heartbeat pings and terminate dead connections."""
    now = int(time.time())
    cutoff = now - PONG_TIMEOUT
    
    # Scan for active connections
    # In production, use a GSI on connection status or a separate "active connections" list
    response = table.scan(
        FilterExpression="begins_with(PK, :prefix) AND SK = :meta",
        ExpressionAttributeValues={
            ":prefix": "CONN#",
            ":meta": "META",
        },
        ProjectionExpression="PK, connectionId, lastPingAt",
        Limit=MAX_CONNECTIONS_PER_RUN,
    )
    
    connections = response.get("Items", [])
    stale = []
    to_ping = []
    
    for conn in connections:
        last_ping = conn.get("lastPingAt", 0)
        if isinstance(last_ping, str):
            # Parse ISO timestamp to epoch
            from datetime import datetime
            last_ping = int(datetime.fromisoformat(last_ping.replace("Z", "+00:00")).timestamp())
        
        if last_ping < cutoff:
            # No response in 60 seconds -- terminate
            stale.append(conn["connectionId"])
        else:
            to_ping.append(conn["connectionId"])
    
    # Send pings in parallel
    ping_message = json.dumps({
        "type": "ping",
        "timestamp": now,
    }).encode("utf-8")
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {
            executor.submit(send_ping, conn_id, ping_message): conn_id
            for conn_id in to_ping
        }
        for future in as_completed(futures):
            conn_id = futures[future]
            try:
                result = future.result()
                if result == "gone":
                    stale.append(conn_id)
            except Exception:
                pass
    
    # Terminate stale connections
    for conn_id in stale:
        try:
            api_gw.delete_connection(ConnectionId=conn_id)
        except Exception:
            pass
        cleanup_stale_connection(conn_id)
    
    print(f"Heartbeat: pinged {len(to_ping)}, terminated {len(stale)} stale connections")


def send_ping(connection_id: str, data: bytes) -> str:
    """Send a ping to a WebSocket connection."""
    try:
        api_gw.post_to_connection(ConnectionId=connection_id, Data=data)
        return "ok"
    except api_gw.exceptions.GoneException:
        return "gone"
```

### Client Pong Handling

When the client receives a ping, it should respond with a pong:

```json
// Client receives:
{ "type": "ping", "timestamp": 1712757030 }

// Client sends:
{ "action": "ping" }
```

The `$default` handler recognizes `action: "ping"` and updates `lastPingAt` on the connection record:

```python
# In handle_default:
elif action == "ping":
    table.update_item(
        Key={"PK": f"CONN#{connection_id}", "SK": "META"},
        UpdateExpression="SET lastPingAt = :now",
        ExpressionAttributeValues={":now": int(time.time())},
    )
    return send_to_connection(connection_id, {"type": "pong", "timestamp": int(time.time())})
```

---

## Reconnection and Replay

When a client reconnects after a disconnection, it can receive all events it missed by providing the `lastEventId` it successfully processed.

### Client Reconnection Flow

```
Client disconnects (network failure, process restart, etc.)
    │
    │  Client remembers last eventId it processed:
    │  "evt_01JRWX6E7MNKD3P4Q8R2S5T9V0"
    │
    ▼
Client reconnects:
  wss://ws.agentmail.aws/v1?apiKey=ak_...&lastEventId=evt_01JRWX6E7MNKD3P4Q8R2S5T9V0
    │
    ▼
Lambda: agentmail-ws-connect
    │
    │  1. Authenticate and register connection (normal flow)
    │  2. Detect lastEventId parameter
    │  3. Invoke replay asynchronously (Lambda.invoke async)
    │
    ▼
Lambda: agentmail-ws-replay (async invocation)
    │
    │  1. Look up eventId → Kinesis sequence number from mapping table
    │  2. Get shard iterator at AFTER_SEQUENCE_NUMBER
    │  3. Read events from Kinesis, filtering for matching subscriptions
    │  4. POST each event to @connections/{connectionId}
    │  5. Send replay-complete marker
    │
    ▼
Client receives:
  { "type": "replay-start", "fromEventId": "evt_01JRWX6E7MNKD3P4Q8R2S5T9V0" }
  { "type": "event", "event": { ... } }  // missed event 1
  { "type": "event", "event": { ... } }  // missed event 2
  { "type": "event", "event": { ... } }  // missed event N
  { "type": "replay-complete", "eventsReplayed": N }
```

### EventId to Sequence Number Mapping

```
DynamoDB Table: agentmail-event-sequence-map

  PK: EVT#{eventId}
  SK: SEQ

  Attributes:
    eventId:         "evt_01JRWX6E7MNKD3P4Q8R2S5T9V0"
    shardId:         "shardId-000000000002"
    sequenceNumber:  "49640912345678901234567890123456789012345678901234567890"
    timestamp:       "2026-04-10T14:30:00.123Z"
    inboxId:         "inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y"
    ttl:             1713361800  (7 days, matching Kinesis retention)
```

This table is populated by the `event-archive` enhanced fan-out consumer for every event. The TTL matches Kinesis retention (7 days) -- there is no point mapping events that have already expired from the stream.

### Replay Lambda

```python
import json
import os
import base64

import boto3

kinesis = boto3.client("kinesis")
dynamodb = boto3.resource("dynamodb")
sequence_table = dynamodb.Table("agentmail-event-sequence-map")
connection_table = dynamodb.Table(os.environ["TABLE_NAME"])
api_gw = boto3.client(
    "apigatewaymanagementapi",
    endpoint_url=os.environ["WEBSOCKET_MANAGEMENT_URL"],
)

STREAM_NAME = os.environ["KINESIS_STREAM_NAME"]
MAX_REPLAY_EVENTS = 1000  # Safety limit


def handler(event, context):
    """Replay missed events to a reconnecting WebSocket client."""
    connection_id = event["connectionId"]
    last_event_id = event["lastEventId"]
    org_id = event["orgId"]
    
    # Step 1: Look up sequence number for lastEventId
    mapping = sequence_table.get_item(
        Key={"PK": f"EVT#{last_event_id}", "SK": "SEQ"}
    )
    
    if "Item" not in mapping:
        # Event expired from Kinesis or never existed
        send_to_client(connection_id, {
            "type": "replay-error",
            "message": "Event not found. It may have expired (>7 days old).",
            "lastEventId": last_event_id,
        })
        return
    
    shard_id = mapping["Item"]["shardId"]
    sequence_number = mapping["Item"]["sequenceNumber"]
    
    # Step 2: Get connection's subscriptions for filtering
    conn_response = connection_table.get_item(
        Key={"PK": f"CONN#{connection_id}", "SK": "META"}
    )
    
    if "Item" not in conn_response:
        return  # Connection gone
    
    subscriptions = conn_response["Item"].get("subscriptions", set())
    
    # Send replay-start marker
    send_to_client(connection_id, {
        "type": "replay-start",
        "fromEventId": last_event_id,
    })
    
    # Step 3: Read events from Kinesis
    iterator_response = kinesis.get_shard_iterator(
        StreamName=STREAM_NAME,
        ShardId=shard_id,
        ShardIteratorType="AFTER_SEQUENCE_NUMBER",
        StartingSequenceNumber=sequence_number,
    )
    
    shard_iterator = iterator_response["ShardIterator"]
    events_replayed = 0
    
    while shard_iterator and events_replayed < MAX_REPLAY_EVENTS:
        records_response = kinesis.get_records(
            ShardIterator=shard_iterator,
            Limit=100,
        )
        
        if not records_response["Records"]:
            break  # Caught up
        
        for record in records_response["Records"]:
            event_data = json.loads(record["Data"])
            
            # Filter: only send events matching the client's subscriptions
            if matches_subscriptions(event_data, subscriptions, org_id):
                try:
                    send_to_client(connection_id, {
                        "type": "event",
                        "event": event_data,
                        "replayed": True,
                    })
                    events_replayed += 1
                except Exception:
                    # Connection closed during replay
                    return
        
        shard_iterator = records_response.get("NextShardIterator")
    
    # Send replay-complete marker
    send_to_client(connection_id, {
        "type": "replay-complete",
        "eventsReplayed": events_replayed,
    })


def matches_subscriptions(event: dict, subscriptions: set, org_id: str) -> bool:
    """Check if an event matches any of the connection's subscriptions."""
    if event.get("orgId") != org_id:
        return False
    
    for channel in subscriptions:
        scope_type, scope_id = channel.split(":", 1)
        if scope_type == "org" and scope_id == org_id:
            return True
        if scope_type == "pod" and scope_id == event.get("podId"):
            return True
        if scope_type == "inbox" and scope_id == event.get("inboxId"):
            return True
    
    return False


def send_to_client(connection_id: str, message: dict):
    """Send a message to a WebSocket client."""
    api_gw.post_to_connection(
        ConnectionId=connection_id,
        Data=json.dumps(message).encode("utf-8"),
    )
```

### Replay Limitations

- **Maximum replay window:** 7 days (Kinesis retention period)
- **Maximum events per replay:** 1,000 (safety limit; client can re-request with new lastEventId)
- **Single-shard replay:** Replay reads from the shard that contained the lastEventId. Events for other inboxes on different shards are not included. This is acceptable because per-inbox ordering means the client's inbox events are all on the same shard.
- **Replay during live events:** Replayed events are interleaved with live events. Clients should use `eventId` for deduplication and `replayed: true` flag to distinguish replayed events.

---

## Scaling

### Concurrent Connection Limits

| Component | Limit | Notes |
|-----------|-------|-------|
| API Gateway WebSocket | 500 new connections/sec | Can be increased via service quota |
| API Gateway concurrent connections | 500,000 | Default quota; sufficient for target |
| @connections POST rate | 10,000 messages/sec | Per-account limit |
| Lambda concurrent executions | 1,000 default | Increase to 5,000 for WebSocket workload |

### Connection Store Sizing

At 100K concurrent connections with an average of 3 subscriptions per connection:

| Metric | Value |
|--------|-------|
| Connection records | 100,000 |
| Subscription records | 300,000 |
| Total DynamoDB items | 400,000 |
| Average item size | 250 bytes |
| Total storage | ~100 MB |
| Read capacity (event routing) | ~500 RCU (on-demand) |
| Write capacity (connect/disconnect) | ~50 WCU (on-demand) |

### Fan-Out Lambda Concurrency

The websocket-pipeline dispatcher must be able to process events and fan them out to all matching connections. The bottleneck is @connections POST calls.

- Each @connections POST takes ~10ms
- With ThreadPoolExecutor(max_workers=50), a single Lambda invocation can deliver to 50 connections in ~10ms
- For an event matching 1,000 connections: 1,000 / 50 = 20 batches x 10ms = ~200ms
- Reserved concurrency of 20 Lambda instances can process 20 events simultaneously

For events with extremely high fan-out (>10,000 connections, e.g., an org-level subscription for a large customer), the dispatcher enqueues to SQS and a separate fan-out Lambda handles delivery in parallel:

```python
HIGH_FANOUT_THRESHOLD = 500

if len(connection_ids) > HIGH_FANOUT_THRESHOLD:
    # Chunk into batches of 100 and enqueue to SQS
    for chunk in chunked(connection_ids, 100):
        sqs.send_message(
            QueueUrl=WS_FANOUT_QUEUE,
            MessageBody=json.dumps({
                "connectionIds": list(chunk),
                "message": ws_message_str,
            }),
        )
else:
    # Direct fan-out (inline)
    ...
```

---

## Backpressure

### API Gateway Buffer

API Gateway maintains a 128 KB send buffer per WebSocket connection. If the client is not reading data fast enough (slow consumer), the buffer fills up.

- **Buffer full behavior:** API Gateway drops the connection (sends a close frame with status 1008).
- **Client impact:** The client must reconnect and provide `lastEventId` to replay missed events.
- **Mitigation:** Events are typically 500 bytes - 2 KB. At 128 KB buffer, approximately 64-256 events can be buffered before the connection is dropped. At 10 events/sec per inbox, this gives the client ~6-25 seconds of grace period.

### Rate Limiting Per Connection

To prevent a single connection from overwhelming the system, we enforce per-connection rate limits:

| Metric | Limit | Enforcement |
|--------|-------|-------------|
| Subscribe requests/sec | 10 | Lambda-side check, return error |
| Messages received from client/sec | 50 | API Gateway route throttle |
| Events pushed to client/sec | 1,000 | If exceeded, drop oldest events |

---

## Failure Modes

### Stale Connections (410 GoneException)

**Cause:** Client disconnected without sending a close frame (network failure, process crash). API Gateway does not invoke `$disconnect` for ungraceful disconnections.

**Detection:** `@connections POST` returns 410 GoneException.

**Resolution:** The event dispatcher catches 410, calls `cleanup_stale_connection()` to remove the connection record and all subscription records. The heartbeat Lambda also detects stale connections and terminates them.

**Impact:** Events may be sent to a stale connection for up to 60 seconds (2 heartbeat cycles) before the connection is cleaned up. These events are silently lost. The client must reconnect with `lastEventId` to replay.

### Lambda Cold Starts

**Cause:** The websocket-pipeline dispatcher Lambda is invoked after a period of inactivity.

**Impact:** 500-2000ms added latency for the first event after a cold start. Subsequent events within the same Lambda instance are processed in ~50ms.

**Mitigation:** Provisioned concurrency of 5 instances for the event dispatcher Lambda. Cost: ~$35/mo (5 instances x 1024 MB x $0.000004826/GB-sec x 730 hours).

### Kinesis Iterator Aging

**Cause:** The websocket-pipeline Lambda falls behind reading from Kinesis. The iterator age (difference between the latest record and the consumer's current position) increases.

**Detection:** CloudWatch metric `IteratorAgeMilliseconds` for the websocket-pipeline consumer.

**Impact:** Events are delayed by the iterator age. At >5 minutes iterator age, events are effectively stale for real-time use.

**Alarm:** IteratorAgeMilliseconds > 30000 (30 seconds) for 5 minutes triggers P2 alert.

**Resolution:**
1. Increase Lambda concurrency (more parallel shard processors)
2. Increase Lambda memory (faster processing per event)
3. If DynamoDB queries are the bottleneck, add DAX cache
4. If fan-out is the bottleneck, lower HIGH_FANOUT_THRESHOLD to offload to SQS sooner

### API Gateway Management API Throttling

**Cause:** Too many `@connections POST` calls per second (account-level limit: 10,000/sec).

**Detection:** 429 errors from @connections POST.

**Impact:** Some events are not delivered. The dispatcher retries with exponential backoff, but under sustained load, events may be dropped.

**Mitigation:**
1. Request service quota increase (up to 100,000/sec)
2. Batch multiple events into a single WebSocket frame (reduces @connections calls)
3. Use SQS-based fan-out for high-connection-count events

---

## Client SDK Example

```python
import asyncio
import json
import websockets


class AgentMailWebSocket:
    """AgentMail WebSocket client with auto-reconnect and replay."""
    
    def __init__(self, api_key: str, channels: list[str], on_event=None):
        self.api_key = api_key
        self.channels = channels
        self.on_event = on_event or (lambda e: print(e))
        self.last_event_id = None
        self._ws = None
        self._running = False
    
    async def connect(self):
        """Connect to AgentMail WebSocket with automatic reconnection."""
        self._running = True
        while self._running:
            try:
                url = f"wss://ws.agentmail.aws/v1?apiKey={self.api_key}"
                if self.last_event_id:
                    url += f"&lastEventId={self.last_event_id}"
                
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    
                    # Subscribe to channels
                    for channel in self.channels:
                        await ws.send(json.dumps({
                            "action": "subscribe",
                            "channel": channel,
                        }))
                    
                    # Listen for messages
                    async for raw_message in ws:
                        message = json.loads(raw_message)
                        
                        if message["type"] == "event":
                            event = message["event"]
                            self.last_event_id = event["eventId"]
                            await self.on_event(event)
                        elif message["type"] == "ping":
                            await ws.send(json.dumps({"action": "ping"}))
                        elif message["type"] == "replay-start":
                            print(f"Replaying from {message['fromEventId']}")
                        elif message["type"] == "replay-complete":
                            print(f"Replay complete: {message['eventsReplayed']} events")
                        elif message["type"] == "error":
                            print(f"Error: {message['message']}")
            
            except websockets.exceptions.ConnectionClosed:
                print("Connection closed. Reconnecting in 1s...")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Connection error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
    
    async def disconnect(self):
        self._running = False
        if self._ws:
            await self._ws.close()


# Usage
async def handle_event(event):
    print(f"Received: {event['eventType']} for {event['inboxId']}")

client = AgentMailWebSocket(
    api_key="ak_01JRWX...",
    channels=["inbox:inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y"],
    on_event=handle_event,
)

asyncio.run(client.connect())
```
