# Authentication

This document covers the complete authentication architecture for the AgentMail API, including API key format, generation, storage, scoping, the Lambda authorizer flow, OTP verification for sign-up, and key rotation strategy.

---

## User Account Authentication (Console)

In addition to API key authentication (for programmatic access), AgentMail provides user account authentication for the web console at agentmail.dev.

### Identity Provider: AWS Cognito User Pool

User accounts are managed by an AWS Cognito User Pool, which handles registration, login, password resets, and MFA.

### Sign-Up Methods

| Method | Flow |
|--------|------|
| **Email + Password** | User registers with email and password. Cognito sends a verification email. After verification, the user can log in. |
| **Google OAuth** | Cognito Hosted UI redirects to Google. On success, Cognito creates or links the user account. |
| **GitHub OAuth** | Cognito OIDC integration with GitHub as an identity provider. Same link-or-create flow. |

### Session Tokens

After successful authentication, Cognito issues three JWT tokens:

- **ID Token**: Contains user claims (email, name, org_id). Used by the console frontend.
- **Access Token**: Used for authenticated API calls from the console. Contains scopes.
- **Refresh Token**: Long-lived token (30 days) for obtaining new ID/Access tokens without re-authentication.

ID and Access tokens expire after 1 hour. The console frontend uses the Refresh token to silently renew them.

### Relationship: User Account to Organization

```
User Account (Cognito)
    |
    +-- email, name, auth provider
    |
    +-- Organization (1:1 for new sign-ups, many:1 for team members)
          |
          +-- API Keys (for programmatic access)
          +-- Pods, Inboxes, Messages...
```

When a user signs up, a new Organization is automatically created and the user is set as the owner. Team members can be invited to join an existing Organization (Business tier and above).

### Dual Auth: JWT + API Key

The API supports both authentication methods:

| Method | Header | Source | Use Case |
|--------|--------|--------|----------|
| **JWT** | `Authorization: Bearer <id_token>` | Console sessions | Web console UI, interactive use |
| **API Key** | `x-api-key: ak_live_...` or `Authorization: Bearer ak_live_...` | Programmatic clients | SDKs, scripts, agent integrations |

The Lambda authorizer handles both methods:

1. If the token starts with `ak_live_` or `ak_test_`, it is treated as an API key.
2. Otherwise, the token is validated as a Cognito JWT:
   - Verify signature against Cognito JWKS endpoint (cached)
   - Check `iss` matches the User Pool URL
   - Check `exp` is in the future
   - Extract `org_id` from custom claims
   - Build the same auth context used by API key auth

This means downstream Lambda handlers receive an identical auth context regardless of whether the request came from the console (JWT) or from a programmatic client (API key).

---

## API Key Format

AgentComms uses prefixed API keys that encode environment and provide a recognizable format:

```
ak_live_EXAMPLE
|  |    |
|  |    +-- 32 random bytes, base62 encoded (43 chars)
|  +------- environment: "live" production key
+---------- prefix: "ak" (AgentComms API key)
```

| Environment | Prefix | Example |
|-------------|--------|---------|
| Production | `ak_live_` | `ak_live_EXAMPLE` |
| Test/Sandbox | `ak_test_` | `ak_test_9xR2tU4wP0qS3yZ6aB8cD1eF5gH7jK` |

Test keys can only access sandbox resources. Production keys can only access production resources. The prefix allows developers and support teams to immediately identify key type from logs without exposing the secret portion.

The first 4 characters after the prefix are stored as the key `prefix` field in metadata, enabling key identification without exposing the full key:

```
ak_live_7kB3...
        ^^^^
        stored as "prefix" for display
```

---

## Key Generation

### Algorithm

```python
import secrets
import hashlib

BASE62_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def generate_api_key(environment: str = "live") -> tuple[str, str]:
    """
    Generate an API key and its SHA-256 hash.

    Returns:
        (plaintext_key, sha256_hash)
    """
    # Generate 32 cryptographically random bytes
    random_bytes = secrets.token_bytes(32)

    # Encode to base62 (43 characters for 32 bytes)
    num = int.from_bytes(random_bytes, "big")
    encoded = []
    while num > 0:
        num, remainder = divmod(num, 62)
        encoded.append(BASE62_CHARS[remainder])
    encoded_str = "".join(reversed(encoded)).rjust(43, "0")

    # Construct the full key
    plaintext_key = f"am_{environment}_{encoded_str}"

    # Hash for storage
    key_hash = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()

    return plaintext_key, key_hash
```

### Properties

| Property | Value |
|----------|-------|
| Random entropy | 256 bits (32 bytes) |
| Encoding | Base62 (alphanumeric only, no special chars) |
| Total key length | 51 characters (`ak_live_` + 43 chars) |
| Hash algorithm | SHA-256 |
| Collision probability | ~1 in 2^128 (birthday bound for 256-bit space) |

---

## Key Storage

API keys are stored in DynamoDB with the SHA-256 hash as the lookup key. The plaintext key is never stored.

### DynamoDB Item

```json
{
  "PK": "ORG#01HXYZ1234567890ABCDEFGHJK",
  "SK": "APIKEY#01HXYZ1234567890ABCDEFGHJL",
  "GSI1PK": "APIKEY#a1b2c3d4e5f6...sha256hash",
  "GSI1SK": "APIKEY#01HXYZ1234567890ABCDEFGHJL",
  "entity_type": "ApiKey",
  "id": "01HXYZ1234567890ABCDEFGHJL",
  "org_id": "01HXYZ1234567890ABCDEFGHJK",
  "name": "Production Key",
  "prefix": "ak_live_7kB3",
  "key_hash": "a1b2c3d4e5f6...full_sha256_hash",
  "environment": "live",
  "scope": "org",
  "scope_resource_id": null,
  "status": "active",
  "last_used_at": "2026-04-10T14:00:00.000Z",
  "created_at": "2026-01-15T09:00:00.000Z",
  "expires_at": null
}
```

### Creation Flow

1. Client calls `POST /api-keys` with key name and scope.
2. Lambda generates plaintext key and SHA-256 hash.
3. Lambda writes DynamoDB item with hash (never the plaintext).
4. Lambda returns the full plaintext key in the response body.
5. Client stores the key. It is never shown again.

---

## Key Scoping

API keys are scoped to control access at three levels:

### Scope Levels

| Scope | Access | Use Case |
|-------|--------|----------|
| `org` | Full access to all resources in the organization | Admin operations, CI/CD pipelines |
| `pod` | Access to all inboxes and messages within a specific pod | Per-project or per-team isolation |
| `inbox` | Access to a single inbox and its messages/threads/drafts | Single-agent operation |

### Permission Matrix

| Operation | `org` scope | `pod` scope | `inbox` scope |
|-----------|:-----------:|:-----------:|:-------------:|
| GET /organizations/me | Yes | Yes (read-only) | Yes (read-only) |
| CRUD /api-keys | Yes | No | No |
| CRUD /pods | Yes | Own pod only | No |
| CRUD /inboxes | Yes | Own pod only | Own inbox only |
| CRUD /messages | Yes | Own pod's inboxes | Own inbox only |
| CRUD /threads | Yes | Own pod's inboxes | Own inbox only |
| CRUD /drafts | Yes | Own pod's inboxes | Own inbox only |
| CRUD /domains | Yes | No | No |
| CRUD /webhooks | Yes | No | No |
| CRUD /lists | Yes | Own pod's lists | No |
| POST /metrics/query | Yes | Own pod only | Own inbox only |
| POST /search | Yes | Own pod only | Own inbox only |
| WSS /ws | Yes | Own pod channels | Own inbox channel |

### Scope Validation

When a request arrives, the authorizer extracts the scope from the cached auth context and validates:

```python
def validate_scope(auth_context: dict, resource_path: str, resource_ids: dict) -> bool:
    scope = auth_context["scope"]
    scope_resource_id = auth_context.get("scope_resource_id")

    if scope == "org":
        # Org-scoped keys have full access
        return True

    if scope == "pod":
        # Pod-scoped keys: verify the target resource belongs to this pod
        if "pod_id" in resource_ids:
            return resource_ids["pod_id"] == scope_resource_id
        if "inbox_id" in resource_ids:
            # Look up the inbox's pod_id
            inbox = get_inbox(resource_ids["inbox_id"])
            return inbox and inbox["pod_id"] == scope_resource_id
        return False

    if scope == "inbox":
        # Inbox-scoped keys: verify the target is this exact inbox
        if "inbox_id" in resource_ids:
            return resource_ids["inbox_id"] == scope_resource_id
        return False

    return False
```

---

## Lambda Authorizer Flow

The Lambda authorizer is a request-based authorizer (not token-based) that runs on every API Gateway invocation. It validates the API key, resolves organizational context, and returns an IAM policy.

### Detailed Flow

```
1. API Gateway extracts headers from request
   |
2. Lambda Authorizer invoked with:
   - headers (x-api-key or Authorization)
   - methodArn (HTTP method + resource path)
   - requestContext
   |
3. Extract API key from headers
   - Check x-api-key header first
   - Fall back to Authorization: Bearer
   - If neither present: return 401
   |
4. Hash the key: SHA-256(plaintext_key)
   |
5. Check Redis cache: GET auth:{key_hash}
   |
   +-- Cache HIT: Parse cached auth context (JSON)
   |   |
   |   +-- Check if cached entry shows key as revoked
   |       - If revoked: return 403
   |       - If active: proceed to step 7
   |
   +-- Cache MISS: Query DynamoDB
       |
6.     Query DynamoDB GSI1:
       GSI1PK = "APIKEY#{key_hash}"
       |
       +-- No result: return 401 (invalid key)
       |
       +-- Result found:
           - Check status == "active"
           - Check expires_at is null or in the future
           - Check environment matches (live vs test)
           - If any check fails: return 401/403
           |
           Build auth context:
           {
             "org_id": "...",
             "key_id": "...",
             "scope": "org|pod|inbox",
             "scope_resource_id": "...|null",
             "environment": "live|test",
             "tier": "free|pro|enterprise"
           }
           |
           Write to Redis: SET auth:{key_hash} {json} EX 300
   |
7. Validate scope against requested resource
   - Parse resource path to extract resource IDs
   - Call validate_scope(auth_context, path, resource_ids)
   - If scope violation: return 403
   |
8. Update last_used_at (async, fire-and-forget)
   - DynamoDB UpdateItem on the API key record
   - Throttled to at most once per minute per key
   |
9. Return IAM policy + context to API Gateway:
   {
     "principalId": "{org_id}",
     "policyDocument": {
       "Version": "2012-10-17",
       "Statement": [{
         "Action": "execute-api:Invoke",
         "Effect": "Allow",
         "Resource": "{methodArn}"
       }]
     },
     "context": {
       "org_id": "...",
       "key_id": "...",
       "scope": "...",
       "scope_resource_id": "...",
       "environment": "...",
       "tier": "..."
     }
   }
```

### Authorizer Lambda Code (Core)

```python
import hashlib
import json
import os
import boto3
import redis

redis_client = redis.Redis(
    host=os.environ["REDIS_HOST"],
    port=6379,
    ssl=True,
    decode_responses=True,
)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

CACHE_TTL = 300  # 5 minutes


def handler(event, context):
    # Step 1: Extract API key
    api_key = extract_api_key(event["headers"])
    if not api_key:
        raise Exception("Unauthorized")  # API Gateway maps to 401

    # Step 2: Hash the key
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    # Step 3: Check Redis cache
    cache_key = f"auth:{key_hash}"
    cached = redis_client.get(cache_key)

    if cached:
        auth_context = json.loads(cached)
    else:
        # Step 4: Query DynamoDB GSI1
        response = table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={
                ":pk": f"APIKEY#{key_hash}",
            },
            Limit=1,
        )

        if not response["Items"]:
            raise Exception("Unauthorized")

        item = response["Items"][0]

        # Validate key status
        if item["status"] != "active":
            raise Exception("Unauthorized")

        # Build auth context
        auth_context = {
            "org_id": item["org_id"],
            "key_id": item["id"],
            "scope": item["scope"],
            "scope_resource_id": item.get("scope_resource_id"),
            "environment": item["environment"],
            "tier": get_org_tier(item["org_id"]),
        }

        # Cache in Redis
        redis_client.setex(cache_key, CACHE_TTL, json.dumps(auth_context))

    # Step 5: Validate scope
    method_arn = event["methodArn"]
    resource_path = extract_resource_path(method_arn)
    resource_ids = parse_resource_ids(resource_path)

    if not validate_scope(auth_context, resource_path, resource_ids):
        raise Exception("Unauthorized")  # 403

    # Step 6: Async update last_used_at (fire and forget via SQS)
    update_last_used(auth_context["key_id"])

    # Step 7: Return policy
    return generate_policy(
        principal_id=auth_context["org_id"],
        effect="Allow",
        resource=method_arn,
        context=auth_context,
    )


def extract_api_key(headers: dict) -> str | None:
    """Extract API key from x-api-key or Authorization header."""
    # Normalize header names to lowercase
    normalized = {k.lower(): v for k, v in headers.items()}

    if "x-api-key" in normalized:
        return normalized["x-api-key"]

    auth = normalized.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]

    return None


def generate_policy(principal_id, effect, resource, context):
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
        "context": {
            k: str(v) if v is not None else ""
            for k, v in context.items()
        },
    }
```

### Authorizer Caching

API Gateway's built-in authorizer caching is **disabled**. Instead, we use Redis for caching because:

1. API Gateway's authorizer cache is per-key and per-resource, leading to excessive Lambda invocations for keys used across many endpoints.
2. Redis gives us explicit control over TTL and invalidation.
3. Redis cache is shared across all authorizer Lambda instances.

---

## OTP Verification Flow

New account sign-up uses a one-time password (OTP) sent to the agent's email.

### Flow

```
1. Client: POST /agent/signup { email, org_name }
   |
2. Server validates email format
   |
3. Server generates OTP:
   - 6 digits: random.randint(100000, 999999)
   - Store in DynamoDB:
     PK: "OTP#{email}"
     SK: "OTP#{timestamp}"
     code_hash: SHA-256(code)
     attempts: 0
     max_attempts: 10
     expires_at: now + 24 hours
   |
4. Server sends email via SES:
   Subject: "Your AgentMail verification code"
   Body: "Your code is: 482917. It expires in 24 hours."
   |
5. Server returns 201: { message, email, expires_at }
   |
6. Client: POST /agent/verify { email, code }
   |
7. Server queries OTP record:
   - PK: "OTP#{email}"
   - Get most recent SK
   |
8. Validate:
   - Check expires_at > now
   - Check attempts < max_attempts (10)
   - Increment attempts counter
   - Compare SHA-256(submitted_code) == stored code_hash
   |
   +-- Invalid code: return 401, increment attempts
   +-- Expired: return 401 "Code expired"
   +-- Max attempts: return 401 "Too many attempts"
   |
9. Code valid:
   - Create Organization record in DynamoDB
   - Generate initial API key (org-scoped)
   - Delete OTP record
   - Return 200: { organization, api_key }
```

### OTP DynamoDB Item

```json
{
  "PK": "OTP#admin@example.com",
  "SK": "OTP#2026-04-10T14:32:00.000Z",
  "code_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "email": "admin@example.com",
  "org_name": "Acme Corp",
  "attempts": 0,
  "max_attempts": 10,
  "expires_at": "2026-04-11T14:32:00.000Z",
  "created_at": "2026-04-10T14:32:00.000Z",
  "ttl": 1712930520
}
```

The `ttl` attribute triggers DynamoDB TTL to auto-delete the record after expiry plus a buffer.

### Security Properties

| Property | Value | Rationale |
|----------|-------|-----------|
| Code length | 6 digits | 1M combinations -- sufficient for time-limited OTP |
| Expiry | 24 hours | Generous for automated sign-up flows that may queue |
| Max attempts | 10 | Prevents brute-force (1M / 10 = 0.001% success) |
| Code storage | SHA-256 hash | Database compromise does not reveal codes |
| Rate limit | 3 sign-up requests per email per hour | Prevents email bombing |

---

## Key Rotation Strategy

API keys do not expire by default, but organizations can implement rotation through the following workflow:

### Recommended Rotation Flow

```
1. Create a new key: POST /api-keys
   - New key is immediately active
   |
2. Update client configuration to use the new key
   - Both old and new keys work during this transition
   |
3. Verify the new key is working
   - Check last_used_at on the new key
   |
4. Revoke the old key: DELETE /api-keys/{old_key_id}
   - Old key becomes immediately invalid
   - Cached auth entries expire within 5 minutes (Redis TTL)
```

### Forced Rotation

Organizations can set key expiry at creation:

```json
{
  "name": "Rotating Key",
  "scope": "org",
  "expires_in_days": 90
}
```

Expired keys return 401 immediately. The API sends a `key.expiring_soon` webhook event 7 days before expiry to give clients time to rotate.

### Emergency Revocation

When a key is compromised:

1. `DELETE /api-keys/{id}` immediately marks the key as revoked.
2. A `REVOKED` status is written to the DynamoDB record.
3. The Redis cache entry is explicitly deleted (not just left to expire).
4. Any in-flight API Gateway authorizer cache entries expire naturally (API Gateway cache is disabled, so this only affects Redis).

```python
def revoke_key(key_id: str, org_id: str):
    """Immediately revoke an API key."""
    # Update DynamoDB
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"APIKEY#{key_id}"},
        UpdateExpression="SET #status = :revoked, revoked_at = :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":revoked": "revoked",
            ":now": datetime.utcnow().isoformat() + "Z",
        },
    )

    # Get the key hash to invalidate cache
    item = table.get_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"APIKEY#{key_id}"}
    )["Item"]

    # Delete Redis cache
    redis_client.delete(f"auth:{item['key_hash']}")
```

---

## Security Considerations

### Transport Security

- All API traffic requires HTTPS (TLS 1.2+). HTTP requests are rejected.
- API Gateway enforces minimum TLS 1.2 via security policy.
- CloudFront adds HSTS headers.

### Key Confidentiality

- Plaintext keys are never stored. Only SHA-256 hashes are persisted.
- Keys are transmitted only at creation time (once) and in request headers (over TLS).
- Keys never appear in server-side logs. API Gateway access logging masks the `x-api-key` header.
- The key `prefix` (first 4 chars after `ak_live_`) is stored for identification without exposing the secret.

### Timing Attacks

- Key hash comparison uses constant-time comparison (`hmac.compare_digest`).
- OTP code verification uses hash comparison (constant-time by nature of hash equality check).

### Rate Limiting on Auth

- The Lambda authorizer itself is rate-limited by API Gateway's throttle settings.
- Failed authentication attempts are logged with source IP for anomaly detection.
- 10 failed attempts from the same IP within 5 minutes triggers WAF rate blocking.
