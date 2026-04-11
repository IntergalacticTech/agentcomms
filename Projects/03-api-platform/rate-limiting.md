# Rate Limiting

AgentMail uses a three-tier rate limiting architecture to balance fair usage, abuse prevention, and DDoS protection. Each tier operates independently and serves a distinct purpose.

---

## Architecture Overview

```
Incoming Request
      |
      v
+---------------------+
| Tier 3: AWS WAF      |   Per-IP rate rules (DDoS protection)
| (CloudFront/ALB)     |   Blocks at network edge before request reaches API Gateway
+---------------------+
      |
      v
+---------------------+
| Tier 1: API Gateway   |   Per-key throttle + monthly quota (Usage Plans)
| (Usage Plans)         |   Enforced by API Gateway natively
+---------------------+
      |
      v
+---------------------+
| Tier 2: Redis         |   Per-org, per-endpoint sliding window
| (Sliding Window)      |   Fine-grained control in Lambda
+---------------------+
      |
      v
  Lambda Handler
```

---

## Tier 1: API Gateway Usage Plans

API Gateway Usage Plans provide per-API-key throttling and monthly request quotas. These are the first line of defense after WAF and require zero custom code.

### Configuration Per Pricing Tier

**SaaS Tiers:**

| Tier | Burst (rps) | Sustained (rps) | Monthly Quota | Price |
|------|:-----------:|:----------------:|:-------------:|-------|
| Free | 10 | 5 | 50,000 | $0 |
| Pro | 100 | 50 | 500,000 | $29/mo |
| Business | 500 | 250 | 2,000,000 | $99/mo |
| Scale | 1,000 | 500 | 10,000,000 | $299/mo |

**Marketplace Tiers:**

| Tier | Burst (rps) | Sustained (rps) | Monthly Quota | Price |
|------|:-----------:|:----------------:|:-------------:|-------|
| Starter | 100 | 50 | 500,000 | $29/mo |
| Growth | 500 | 250 | 2,000,000 | $99/mo |
| Scale | 1,000 | 500 | 10,000,000 | $499/mo |
| Enterprise | 2,000 | 1,000 | Unlimited | Custom |

### Usage Plan CloudFormation

```yaml
Resources:
  FreeTierUsagePlan:
    Type: AWS::ApiGateway::UsagePlan
    Properties:
      UsagePlanName: agentmail-free
      Description: Free tier - 10 rps burst, 10K monthly
      ApiStages:
        - ApiId: !Ref ApiGateway
          Stage: v1
      Throttle:
        BurstLimit: 10
        RateLimit: 5
      Quota:
        Limit: 10000
        Period: MONTH

  ProTierUsagePlan:
    Type: AWS::ApiGateway::UsagePlan
    Properties:
      UsagePlanName: agentmail-pro
      Description: Pro tier - 100 rps burst, 1M monthly
      ApiStages:
        - ApiId: !Ref ApiGateway
          Stage: v1
      Throttle:
        BurstLimit: 100
        RateLimit: 50
      Quota:
        Limit: 1000000
        Period: MONTH

  EnterpriseTierUsagePlan:
    Type: AWS::ApiGateway::UsagePlan
    Properties:
      UsagePlanName: agentmail-enterprise
      Description: Enterprise tier - 2000 rps burst, unlimited
      ApiStages:
        - ApiId: !Ref ApiGateway
          Stage: v1
      Throttle:
        BurstLimit: 2000
        RateLimit: 1000
      # No quota (unlimited)
```

### Behavior

- **Burst limit** allows short spikes above the sustained rate. API Gateway uses a token bucket algorithm where tokens refill at the sustained rate and the bucket holds up to the burst limit.
- **Monthly quota** is tracked per API key. When exhausted, all requests return 429 until the next billing period.
- When a request is throttled at this tier, API Gateway returns `429 Too Many Requests` with a `Retry-After` header before the Lambda is invoked (saving compute cost).

---

## Tier 2: Redis Sliding Window

For fine-grained, per-organization, per-endpoint rate limiting, we use a Redis-based sliding window counter implemented as a Lua script. This runs inside the Lambda function after authentication but before business logic.

### Why Sliding Window

| Algorithm | Pros | Cons |
|-----------|------|------|
| Fixed window | Simple, low memory | Boundary spike (2x burst at window edges) |
| Sliding log | Perfect accuracy | High memory (stores every timestamp) |
| **Sliding window** | **Near-perfect accuracy, low memory** | **Slightly more complex** |

The sliding window algorithm estimates the current window's count by weighting the previous window's count by the overlap percentage. This prevents the boundary-spike problem of fixed windows while using only two counters per key.

### Redis Lua Script

```lua
-- sliding_window_rate_limit.lua
-- Atomic sliding window rate limiter
--
-- KEYS[1] = rate limit key (e.g., "rl:{org_id}:{endpoint}:{window}")
-- ARGV[1] = window size in seconds
-- ARGV[2] = max requests per window
-- ARGV[3] = current timestamp (seconds, float)
--
-- Returns: {allowed (0/1), remaining, reset_at, retry_after}

local key = KEYS[1]
local window_size = tonumber(ARGV[1])
local max_requests = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

-- Calculate current and previous window boundaries
local current_window = math.floor(now / window_size) * window_size
local previous_window = current_window - window_size

-- Keys for current and previous window counters
local current_key = key .. ":" .. tostring(current_window)
local previous_key = key .. ":" .. tostring(previous_window)

-- Get counts
local current_count = tonumber(redis.call("GET", current_key) or "0")
local previous_count = tonumber(redis.call("GET", previous_key) or "0")

-- Calculate weighted count using sliding window
-- Weight = percentage of previous window that overlaps with our sliding window
local elapsed_in_current = now - current_window
local weight = math.max(0, (window_size - elapsed_in_current) / window_size)
local weighted_count = math.floor(previous_count * weight) + current_count

if weighted_count >= max_requests then
    -- Rate limited
    local reset_at = current_window + window_size
    local retry_after = math.ceil(reset_at - now)
    return {0, 0, reset_at, retry_after}
end

-- Allowed: increment current window counter
local new_count = redis.call("INCR", current_key)

-- Set TTL on current window key (2x window size for sliding calculation)
redis.call("EXPIRE", current_key, window_size * 2)

-- Recalculate remaining
local new_weighted = math.floor(previous_count * weight) + new_count
local remaining = math.max(0, max_requests - new_weighted)
local reset_at = current_window + window_size

return {1, remaining, reset_at, 0}
```

### Python Wrapper

```python
import time
import redis

# Load the Lua script once at module level
SLIDING_WINDOW_SCRIPT = """
... (Lua script above) ...
"""


class RateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.script = self.redis.register_script(SLIDING_WINDOW_SCRIPT)

    def check(
        self,
        org_id: str,
        endpoint: str,
        window_seconds: int,
        max_requests: int,
    ) -> dict:
        """
        Check if a request is allowed under the rate limit.

        Returns:
            {
                "allowed": bool,
                "remaining": int,
                "reset_at": int (unix timestamp),
                "retry_after": int (seconds, 0 if allowed)
            }
        """
        key = f"rl:{org_id}:{endpoint}"
        now = time.time()

        result = self.script(
            keys=[key],
            args=[window_seconds, max_requests, now],
        )

        return {
            "allowed": bool(result[0]),
            "remaining": int(result[1]),
            "reset_at": int(result[2]),
            "retry_after": int(result[3]),
        }
```

### Per-Endpoint Rate Limits

Different endpoints have different rate limits to protect resource-intensive operations:

| Endpoint Group | Window | Free | Pro | Enterprise |
|---------------|--------|:----:|:---:|:----------:|
| Read (GET) | 60s | 60 | 600 | 6,000 |
| Write (POST/PATCH) | 60s | 30 | 300 | 3,000 |
| Send message | 60s | 10 | 100 | 1,000 |
| Search | 60s | 5 | 50 | 500 |
| Bulk operations | 60s | 2 | 20 | 200 |
| Sign-up / verify | 3600s | 3 | 3 | 3 |

### Integration in Lambda Handler

```python
rate_limiter = RateLimiter(redis_client)

# Endpoint group mapping
ENDPOINT_GROUPS = {
    ("GET", "/inboxes"): "read",
    ("GET", "/inboxes/{id}"): "read",
    ("GET", "/inboxes/{id}/messages"): "read",
    ("POST", "/inboxes"): "write",
    ("POST", "/inboxes/{id}/messages"): "send",
    ("POST", "/search"): "search",
    # ... etc
}

# Rate limits per tier per group: {tier: {group: (window_seconds, max_requests)}}
RATE_LIMITS = {
    "free": {
        "read": (60, 60),
        "write": (60, 30),
        "send": (60, 10),
        "search": (60, 5),
    },
    "pro": {
        "read": (60, 600),
        "write": (60, 300),
        "send": (60, 100),
        "search": (60, 50),
    },
    "enterprise": {
        "read": (60, 6000),
        "write": (60, 3000),
        "send": (60, 1000),
        "search": (60, 500),
    },
}


def apply_rate_limit(org_id: str, tier: str, method: str, path: str) -> dict | None:
    """
    Apply rate limiting. Returns None if allowed, or error response dict if limited.
    """
    endpoint_key = (method, normalize_path(path))
    group = ENDPOINT_GROUPS.get(endpoint_key, "read")

    limits = RATE_LIMITS.get(tier, RATE_LIMITS["free"])
    window_seconds, max_requests = limits.get(group, (60, 60))

    result = rate_limiter.check(org_id, group, window_seconds, max_requests)

    # Always set rate limit headers (returned to client via Lambda response)
    headers = {
        "X-RateLimit-Limit": str(max_requests),
        "X-RateLimit-Remaining": str(result["remaining"]),
        "X-RateLimit-Reset": str(result["reset_at"]),
    }

    if not result["allowed"]:
        headers["Retry-After"] = str(result["retry_after"])
        return {
            "statusCode": 429,
            "headers": headers,
            "body": json.dumps({
                "error": {
                    "code": "RATE_LIMITED",
                    "message": f"Rate limit exceeded. Retry after {result['retry_after']} seconds.",
                }
            }),
        }

    # Store headers for the response (picked up by response middleware)
    return headers  # Caller merges these into the success response
```

---

## Tier 3: AWS WAF Rate Rules

AWS WAF sits at the network edge (CloudFront or API Gateway) and provides per-IP rate limiting for DDoS protection. This tier blocks abusive IPs before requests reach API Gateway, protecting both the platform and legitimate users.

### WAF Rules

```yaml
Resources:
  AgentMailWebACL:
    Type: AWS::WAFv2::WebACL
    Properties:
      Name: agentmail-api-waf
      Scope: REGIONAL  # or CLOUDFRONT
      DefaultAction:
        Allow: {}
      Rules:
        # Rule 1: Block IPs exceeding 2000 requests per 5 minutes
        - Name: rate-limit-per-ip
          Priority: 1
          Action:
            Block:
              CustomResponse:
                ResponseCode: 429
                ResponseHeaders:
                  - Name: Retry-After
                    Value: "60"
                CustomResponseBodyKey: rate-limited
          Statement:
            RateBasedStatement:
              Limit: 2000
              AggregateKeyType: IP
          VisibilityConfig:
            SampledRequestsEnabled: true
            CloudWatchMetricsEnabled: true
            MetricName: rate-limit-per-ip

        # Rule 2: Block IPs with 50+ failed auth attempts per 5 minutes
        - Name: auth-abuse-per-ip
          Priority: 2
          Action:
            Block:
              CustomResponse:
                ResponseCode: 403
          Statement:
            RateBasedStatement:
              Limit: 50
              AggregateKeyType: IP
              ScopeDownStatement:
                ByteMatchStatement:
                  FieldToMatch:
                    SingleHeader:
                      Name: x-amzn-errortype
                  SearchString: "UnauthorizedException"
                  PositionalConstraint: CONTAINS
                  TextTransformations:
                    - Priority: 0
                      Type: NONE
          VisibilityConfig:
            SampledRequestsEnabled: true
            CloudWatchMetricsEnabled: true
            MetricName: auth-abuse-per-ip

        # Rule 3: Geographic blocking (optional, configurable per org)
        - Name: geo-block
          Priority: 3
          Action:
            Block: {}
          Statement:
            GeoMatchStatement:
              CountryCodes:
                - XX  # Placeholder - configured per deployment
          VisibilityConfig:
            SampledRequestsEnabled: true
            CloudWatchMetricsEnabled: true
            MetricName: geo-block

        # Rule 4: AWS Managed Rules - Common Rule Set
        - Name: aws-managed-common
          Priority: 10
          OverrideAction:
            None: {}
          Statement:
            ManagedRuleGroupStatement:
              VendorName: AWS
              Name: AWSManagedRulesCommonRuleSet
          VisibilityConfig:
            SampledRequestsEnabled: true
            CloudWatchMetricsEnabled: true
            MetricName: aws-managed-common

        # Rule 5: AWS Managed Rules - Known Bad Inputs
        - Name: aws-managed-bad-inputs
          Priority: 11
          OverrideAction:
            None: {}
          Statement:
            ManagedRuleGroupStatement:
              VendorName: AWS
              Name: AWSManagedRulesKnownBadInputsRuleSet
          VisibilityConfig:
            SampledRequestsEnabled: true
            CloudWatchMetricsEnabled: true
            MetricName: aws-managed-bad-inputs

      CustomResponseBodies:
        rate-limited:
          ContentType: APPLICATION_JSON
          Content: '{"error":{"code":"RATE_LIMITED","message":"Too many requests from this IP. Please retry later."}}'

      VisibilityConfig:
        SampledRequestsEnabled: true
        CloudWatchMetricsEnabled: true
        MetricName: agentmail-api-waf
```

---

## Response Headers

Every API response includes rate limit headers, regardless of whether the request was rate-limited:

### Success Response (200)

```http
HTTP/1.1 200 OK
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 587
X-RateLimit-Reset: 1712764860
Content-Type: application/json

{"data": [...]}
```

### Rate Limited Response (429)

```http
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1712764860
Retry-After: 23
Content-Type: application/json

{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Rate limit exceeded. Retry after 23 seconds."
  }
}
```

### Header Definitions

| Header | Type | Description |
|--------|------|-------------|
| `X-RateLimit-Limit` | integer | Maximum requests allowed in the current window |
| `X-RateLimit-Remaining` | integer | Requests remaining in the current window |
| `X-RateLimit-Reset` | integer | Unix timestamp when the current window resets |
| `Retry-After` | integer | Seconds to wait before retrying (only on 429) |

---

## Burst vs Sustained Rate Handling

The three tiers handle burst and sustained traffic differently:

### Burst Handling

| Tier | Mechanism | Behavior |
|------|-----------|----------|
| WAF (Tier 3) | 5-minute sliding window | Allows bursts up to 2000 requests per 5 minutes, then blocks IP |
| API Gateway (Tier 1) | Token bucket | Allows burst up to `BurstLimit` tokens, refills at `RateLimit` per second |
| Redis (Tier 2) | Sliding window | Smooth limiting with no boundary spikes; previous window weighted |

### Example: Pro Tier Client Sending Messages

```
Sustained rate: 50 messages/minute (Tier 2 limit)
Burst capacity: 100 rps for ~2 seconds (Tier 1 burst limit)
IP safety: 2000 requests/5 min (Tier 3 WAF)

Scenario: Client sends 80 messages in 10 seconds, then goes quiet.
- Tier 1 (API Gateway): Allows the burst (100 burst > 80 requests)
- Tier 2 (Redis): Allows the burst (100 < 100 per-minute limit for send)
  - But if they try 20 more in the same minute, they hit the limit
- Tier 3 (WAF): No issue (80 << 2000 per 5 minutes)
```

### Monitoring and Alerting

Rate limit metrics are published to CloudWatch:

| Metric | Namespace | Dimensions |
|--------|-----------|------------|
| `RateLimitHits` | `AgentMail/RateLimiting` | `Tier`, `OrgId`, `EndpointGroup` |
| `WAFBlockedRequests` | `AWS/WAFV2` | `Rule`, `WebACL` |
| `APIGateway429Count` | `AWS/ApiGateway` | `ApiName`, `Stage` |

An alarm triggers when any single org hits rate limits more than 100 times per hour, indicating either a misconfigured client or potential abuse. The ops team receives a notification with the org ID, endpoint group, and current tier to determine if the customer needs a tier upgrade or if there is an abuse pattern.
