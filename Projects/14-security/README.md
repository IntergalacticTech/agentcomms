# Security Architecture

This document covers the complete security architecture for AgentMail, including encryption, access control, network security, API key management, WAF configuration, secrets management, OWASP mitigations, compliance roadmap, and incident response planning.

---

## Encryption at Rest

| Data Store | Default Encryption | Enterprise Option | Key Management |
|------------|-------------------|-------------------|----------------|
| **DynamoDB** | AWS-owned key (no additional cost) | AWS KMS customer-managed key (CMK) | AWS manages rotation for owned keys; CMK rotation configurable (annual recommended) |
| **S3** | SSE-S3 (AES-256, S3-managed keys) | SSE-KMS with customer-managed key | S3 handles encryption/decryption transparently; KMS provides audit trail via CloudTrail |
| **ElastiCache Redis** | At-rest encryption enabled (AES-256) | N/A (Redis at-rest encryption is binary on/off) | AWS manages the encryption key |
| **OpenSearch Serverless** | Encryption enabled (mandatory for Serverless) | AWS KMS customer-managed key | Encryption is mandatory and cannot be disabled |
| **Kinesis Data Streams** | Server-side encryption with AWS-managed key | AWS KMS customer-managed key | Encrypts data at rest within the stream |
| **SQS** | SSE-SQS (default encryption) | SSE-KMS with customer-managed key | All queues encrypted by default |
| **CloudWatch Logs** | Encrypted by default | AWS KMS customer-managed key | Log groups can use CMK for additional control |

### Enterprise KMS Configuration

For enterprise customers requiring customer-managed keys (CMK) for compliance:

```python
# CDK: Create a KMS key for enterprise tenant data encryption
from aws_cdk import aws_kms as kms

enterprise_key = kms.Key(
    self, "EnterpriseDataKey",
    alias="alias/agentmail-enterprise-data",
    description="AgentMail enterprise tenant data encryption key",
    enable_key_rotation=True,  # Annual automatic rotation
    pending_window=Duration.days(30),  # 30-day deletion window
    policy=iam.PolicyDocument(
        statements=[
            iam.PolicyStatement(
                sid="AllowKeyAdministration",
                effect=iam.Effect.ALLOW,
                principals=[iam.AccountRootPrincipal()],
                actions=["kms:*"],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="AllowServiceUsage",
                effect=iam.Effect.ALLOW,
                principals=[
                    iam.ServicePrincipal("dynamodb.amazonaws.com"),
                    iam.ServicePrincipal("s3.amazonaws.com"),
                ],
                actions=[
                    "kms:Decrypt",
                    "kms:DescribeKey",
                    "kms:Encrypt",
                    "kms:GenerateDataKey*",
                    "kms:ReEncrypt*",
                ],
                resources=["*"],
            ),
        ]
    ),
)
```

---

## Encryption in Transit

| Connection Path | Protocol | Minimum Version | Configuration |
|----------------|----------|-----------------|---------------|
| Client to API Gateway | HTTPS | TLS 1.2 | API Gateway security policy: `TLS_1_2` |
| Client to CloudFront | HTTPS | TLS 1.2 | CloudFront security policy: `TLSv1.2_2021` |
| API Gateway to Lambda | AWS internal (encrypted) | N/A | Automatically encrypted by AWS |
| Lambda to DynamoDB | HTTPS | TLS 1.2 | AWS SDK uses HTTPS by default |
| Lambda to S3 | HTTPS | TLS 1.2 | Bucket policy enforces `aws:SecureTransport` |
| Lambda to Redis | TLS | TLS 1.2 | ElastiCache in-transit encryption enabled |
| Lambda to OpenSearch | HTTPS | TLS 1.2 | OpenSearch Serverless enforces HTTPS |
| Client to SMTP | SMTPS / STARTTLS | TLS 1.2 | NLB terminates TLS; ECS Fargate handles STARTTLS |
| Client to IMAP | IMAPS | TLS 1.2 | NLB terminates TLS |
| Webhook delivery | HTTPS | TLS 1.2 | Webhook URLs must use HTTPS; HTTP URLs rejected |

### S3 HTTPS-Only Enforcement

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::agentmail-*",
        "arn:aws:s3:::agentmail-*/*"
      ],
      "Condition": {
        "Bool": {
          "aws:SecureTransport": "false"
        }
      }
    }
  ]
}
```

---

## API Key Security

### Key Format

```
am_<64 hex characters>
Example: am_a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890
```

- **Prefix `am_`**: Identifies the key as an AgentMail key (enables secret scanning by GitHub, GitGuardian, etc.)
- **64 hex characters**: 256 bits of entropy from `secrets.token_hex(32)`

### Storage: SHA-256 Hashing

API keys are **never stored in plaintext**. Only the SHA-256 hash is stored in DynamoDB.

```python
import hashlib
import secrets


def create_api_key(org_id: str, name: str, scopes: list) -> dict:
    """
    Create a new API key. Returns the raw key exactly ONCE.
    After this function returns, the raw key cannot be recovered.
    """
    raw_key = f"am_{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]  # For UI display: "am_a1b2c3d4..."

    # Store hash only
    tenant_table.put_item(Item={
        "PK": f"ORG#{org_id}",
        "SK": f"APIKEY#{key_hash}",
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "org_id": org_id,
        "name": name,
        "scopes": scopes,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_used_at": None,
    })

    return {
        "key": raw_key,        # Shown to user ONCE, never stored
        "key_prefix": key_prefix,  # For identification in UI
        "key_id": key_hash[:16],   # Shortened hash for API responses
    }
```

### Authentication Flow

```python
def authenticate_request(api_key: str) -> dict:
    """
    Authenticate an API request.
    1. Hash the provided key
    2. Check Redis cache
    3. Fallback to DynamoDB
    4. Return org context or raise 401
    """
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Check Redis cache first (sub-ms)
    cached = redis_client.get(f"auth:{key_hash}")
    if cached:
        auth_context = json.loads(cached)
        if auth_context["status"] != "active":
            raise UnauthorizedException("API key is disabled")
        return auth_context

    # Cache miss -- check DynamoDB
    # Query GSI to find the key across all orgs
    response = tenant_table.query(
        IndexName="ApiKeyIndex",
        KeyConditionExpression="key_hash = :kh",
        ExpressionAttributeValues={":kh": key_hash},
    )

    if not response["Items"]:
        raise UnauthorizedException("Invalid API key")

    key_record = response["Items"][0]

    if key_record["status"] != "active":
        raise UnauthorizedException("API key is disabled")

    auth_context = {
        "org_id": key_record["org_id"],
        "scopes": key_record["scopes"],
        "status": key_record["status"],
    }

    # Cache for 1 hour
    redis_client.setex(f"auth:{key_hash}", 3600, json.dumps(auth_context))

    # Update last_used_at (async, don't block the request)
    update_last_used_async(key_record["PK"], key_record["SK"])

    return auth_context
```

### Key Revocation

```python
def revoke_api_key(org_id: str, key_id: str):
    """
    Revoke an API key. Takes effect immediately by:
    1. Updating DynamoDB status to 'revoked'
    2. Deleting Redis cache entry (forces re-auth which will fail)
    """
    # Find key by prefix or hash
    key_record = find_key(org_id, key_id)

    # Update DynamoDB
    tenant_table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"APIKEY#{key_record['key_hash']}"},
        UpdateExpression="SET #s = :revoked, revoked_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":revoked": "revoked",
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Delete Redis cache (forces next request to hit DynamoDB and fail)
    redis_client.delete(f"auth:{key_record['key_hash']}")
```

---

## Webhook Secret Security

Webhook secrets are used to sign webhook payloads via HMAC-SHA256. Customers verify the signature to confirm the webhook came from AgentMail.

### KMS Encryption

Webhook secrets are encrypted with AWS KMS before storage. They are never exposed after creation.

```python
def create_webhook(org_id: str, url: str, events: list) -> dict:
    """Create a webhook with a KMS-encrypted signing secret."""
    # Generate a strong random secret
    raw_secret = secrets.token_hex(32)

    # Encrypt with KMS
    kms_client = boto3.client("kms")
    encrypted = kms_client.encrypt(
        KeyId=os.environ["WEBHOOK_KMS_KEY_ID"],
        Plaintext=raw_secret.encode(),
        EncryptionContext={
            "org_id": org_id,
            "resource_type": "webhook_secret",
        },
    )

    webhook_id = f"wh-{uuid.uuid4().hex[:12]}"

    # Store encrypted secret (never plaintext)
    tenant_table.put_item(Item={
        "PK": f"ORG#{org_id}",
        "SK": f"WEBHOOK#{webhook_id}",
        "webhook_id": webhook_id,
        "org_id": org_id,
        "url": url,
        "events": events,
        "secret_encrypted": encrypted["CiphertextBlob"],  # Binary, KMS-encrypted
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Return the raw secret ONCE (like API keys)
    return {
        "webhook_id": webhook_id,
        "secret": raw_secret,  # Shown once, never retrievable again
        "url": url,
        "events": events,
    }


def sign_webhook_payload(org_id: str, webhook_id: str, payload: bytes) -> str:
    """Sign a webhook payload using the decrypted secret."""
    # Retrieve encrypted secret
    record = tenant_table.get_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"WEBHOOK#{webhook_id}"}
    )["Item"]

    # Decrypt with KMS
    kms_client = boto3.client("kms")
    decrypted = kms_client.decrypt(
        CiphertextBlob=record["secret_encrypted"],
        EncryptionContext={
            "org_id": org_id,
            "resource_type": "webhook_secret",
        },
    )
    secret = decrypted["Plaintext"]

    # HMAC-SHA256 signature
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return signature
```

### Webhook Delivery Headers

```
POST /webhook-endpoint HTTP/1.1
Content-Type: application/json
X-AgentMail-Signature: sha256=a1b2c3d4e5f6...
X-AgentMail-Timestamp: 2026-04-10T14:30:00Z
X-AgentMail-Event: message.received
X-AgentMail-Delivery-Id: del-abc123
```

Customers verify the signature:

```python
import hmac
import hashlib

def verify_webhook(payload: bytes, signature_header: str, secret: str) -> bool:
    """Verify an AgentMail webhook signature."""
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

---

## S3 Access Control

### VPC Endpoint Restriction

All S3 access from compute resources goes through a VPC endpoint. The bucket policy denies access from outside the VPC endpoint, preventing data exfiltration even with valid credentials.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "VPCEndpointOnly",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::agentmail-email-bodies",
        "arn:aws:s3:::agentmail-email-bodies/*",
        "arn:aws:s3:::agentmail-attachments",
        "arn:aws:s3:::agentmail-attachments/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:sourceVpce": "vpce-0abc123def456789"
        },
        "StringNotEquals": {
          "aws:PrincipalServiceName": "s3.amazonaws.com"
        }
      }
    }
  ]
}
```

**Exception**: Pre-signed URLs bypass the VPC endpoint condition because the request comes from the customer's network. The pre-signed URL itself is scoped to a specific object key (within the org prefix) and expires in 15 minutes.

### Pre-Signed URL Generation

```python
def generate_presigned_download_url(org_id: str, bucket: str, key: str) -> str:
    """
    Generate a pre-signed URL for downloading an object.
    The key MUST start with the org_id prefix.
    """
    # Security check: verify the key belongs to this org
    if not key.startswith(f"{org_id}/"):
        raise ForbiddenException("Access denied: object does not belong to this organization")

    s3_client = boto3.client("s3")
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
        },
        ExpiresIn=900,  # 15 minutes
    )
    return url
```

### Public Access Block

All S3 buckets have public access completely blocked:

```python
s3.put_public_access_block(
    Bucket=bucket_name,
    PublicAccessBlockConfiguration={
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    },
)
```

---

## IAM: Least-Privilege Lambda Roles

Every Lambda function has a dedicated IAM role with the minimum permissions required for its function. No Lambda function shares a role with another function.

### Example: Inbound Email Processor Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadS3RawEmail",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/agentmail-raw-email/*"
    },
    {
      "Sid": "WriteS3EmailBodies",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::agentmail-email-bodies/*"
    },
    {
      "Sid": "WriteS3Attachments",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::agentmail-attachments/*"
    },
    {
      "Sid": "DynamoDBWriteMessages",
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/agentmail-main",
      "Condition": {
        "ForAllValues:StringLike": {
          "dynamodb:LeadingKeys": ["ORG#*"]
        }
      }
    },
    {
      "Sid": "KinesisWriteEvents",
      "Effect": "Allow",
      "Action": ["kinesis:PutRecord", "kinesis:PutRecords"],
      "Resource": "arn:aws:kinesis:us-east-1:ACCOUNT_ID:stream/agentmail-*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:ACCOUNT_ID:log-group:/aws/lambda/agentmail-inbound-processor:*"
    }
  ]
}
```

### DynamoDB LeadingKeys Condition

The `dynamodb:LeadingKeys` condition key restricts DynamoDB access to items where the partition key matches a pattern. This is the IAM-level enforcement of tenant isolation:

```json
{
  "Condition": {
    "ForAllValues:StringLike": {
      "dynamodb:LeadingKeys": ["ORG#${aws:PrincipalTag/org_id}*"]
    }
  }
}
```

The `${aws:PrincipalTag/org_id}` is resolved from session tags passed by the Lambda authorizer. Even if application code has a bug that constructs a query for the wrong organization, IAM blocks the request.

---

## WAF Configuration

AWS WAF is attached to the API Gateway and CloudFront distributions.

### WAF Rules

```python
# CDK: WAF Web ACL configuration
from aws_cdk import aws_wafv2 as wafv2

web_acl = wafv2.CfnWebACL(
    self, "AgentMailWAF",
    scope="REGIONAL",  # For API Gateway; use "CLOUDFRONT" for CF distribution
    default_action={"allow": {}},
    visibility_config={
        "sampledRequestsEnabled": True,
        "cloudWatchMetricsEnabled": True,
        "metricName": "AgentMailWAF",
    },
    rules=[
        # Rule 1: AWS Managed Rules - Common Rule Set
        {
            "name": "AWSManagedRulesCommonRuleSet",
            "priority": 1,
            "override_action": {"none": {}},
            "visibility_config": {
                "sampledRequestsEnabled": True,
                "cloudWatchMetricsEnabled": True,
                "metricName": "CommonRuleSet",
            },
            "statement": {
                "managed_rule_group_statement": {
                    "vendor_name": "AWS",
                    "name": "AWSManagedRulesCommonRuleSet",
                }
            },
        },
        # Rule 2: AWS Managed Rules - SQL Injection Protection
        {
            "name": "AWSManagedRulesSQLiRuleSet",
            "priority": 2,
            "override_action": {"none": {}},
            "visibility_config": {
                "sampledRequestsEnabled": True,
                "cloudWatchMetricsEnabled": True,
                "metricName": "SQLiRuleSet",
            },
            "statement": {
                "managed_rule_group_statement": {
                    "vendor_name": "AWS",
                    "name": "AWSManagedRulesSQLiRuleSet",
                }
            },
        },
        # Rule 3: AWS Managed Rules - Bot Control
        {
            "name": "AWSManagedRulesBotControlRuleSet",
            "priority": 3,
            "override_action": {"none": {}},
            "visibility_config": {
                "sampledRequestsEnabled": True,
                "cloudWatchMetricsEnabled": True,
                "metricName": "BotControlRuleSet",
            },
            "statement": {
                "managed_rule_group_statement": {
                    "vendor_name": "AWS",
                    "name": "AWSManagedRulesBotControlRuleSet",
                }
            },
        },
        # Rule 4: Rate Limiting (per IP)
        {
            "name": "RateLimitPerIP",
            "priority": 4,
            "action": {"block": {}},
            "visibility_config": {
                "sampledRequestsEnabled": True,
                "cloudWatchMetricsEnabled": True,
                "metricName": "RateLimitPerIP",
            },
            "statement": {
                "rate_based_statement": {
                    "limit": 2000,  # 2000 requests per 5-minute window per IP
                    "aggregate_key_type": "IP",
                }
            },
        },
        # Rule 5: Geo-blocking (optional, configurable per deployment)
        {
            "name": "GeoBlock",
            "priority": 5,
            "action": {"block": {}},
            "visibility_config": {
                "sampledRequestsEnabled": True,
                "cloudWatchMetricsEnabled": True,
                "metricName": "GeoBlock",
            },
            "statement": {
                "geo_match_statement": {
                    "country_codes": [
                        # Block countries based on compliance requirements
                        # Example: OFAC-sanctioned countries
                        "KP", "IR", "SY", "CU",
                    ]
                }
            },
        },
        # Rule 6: Block requests with no API key header
        {
            "name": "RequireAPIKey",
            "priority": 6,
            "action": {"block": {}},
            "visibility_config": {
                "sampledRequestsEnabled": True,
                "cloudWatchMetricsEnabled": True,
                "metricName": "RequireAPIKey",
            },
            "statement": {
                "not_statement": {
                    "statement": {
                        "byte_match_statement": {
                            "search_string": "am_",
                            "field_to_match": {
                                "single_header": {"name": "x-api-key"}
                            },
                            "positional_constraint": "STARTS_WITH",
                            "text_transformations": [
                                {"priority": 0, "type": "NONE"}
                            ],
                        }
                    }
                }
            },
        },
    ],
)
```

---

## Network Security

### VPC Architecture

```
VPC: 10.0.0.0/16
    |
    +-- Public Subnets (10.0.0.0/24, 10.0.1.0/24, 10.0.2.0/24)
    |     |-- NAT Gateways (for Lambda outbound internet)
    |     |-- NLB (for IMAP/SMTP endpoints)
    |     |-- No compute resources (Lambda, ECS) in public subnets
    |
    +-- Private Subnets (10.0.10.0/24, 10.0.11.0/24, 10.0.12.0/24)
    |     |-- Lambda functions (VPC-attached for Redis/OpenSearch access)
    |     |-- ECS Fargate tasks (IMAP/SMTP servers)
    |     |-- ElastiCache Redis cluster
    |     |-- OpenSearch Serverless VPC endpoint
    |     |-- No public IP addresses
    |
    +-- VPC Endpoints (no internet traversal for AWS API calls)
          |-- com.amazonaws.us-east-1.dynamodb (Gateway endpoint)
          |-- com.amazonaws.us-east-1.s3 (Gateway endpoint)
          |-- com.amazonaws.us-east-1.sqs (Interface endpoint)
          |-- com.amazonaws.us-east-1.sns (Interface endpoint)
          |-- com.amazonaws.us-east-1.kms (Interface endpoint)
          |-- com.amazonaws.us-east-1.secretsmanager (Interface endpoint)
          |-- com.amazonaws.us-east-1.kinesis-streams (Interface endpoint)
          |-- com.amazonaws.us-east-1.monitoring (Interface endpoint)
          |-- com.amazonaws.us-east-1.logs (Interface endpoint)
```

### Security Groups

```python
# Lambda security group: outbound only to Redis, OpenSearch, VPC endpoints
lambda_sg = ec2.SecurityGroup(
    self, "LambdaSG",
    vpc=vpc,
    description="Lambda functions - outbound to Redis, OpenSearch, VPC endpoints",
    allow_all_outbound=False,
)
lambda_sg.add_egress_rule(redis_sg, ec2.Port.tcp(6379), "Redis")
lambda_sg.add_egress_rule(opensearch_sg, ec2.Port.tcp(443), "OpenSearch")
lambda_sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS to VPC endpoints and internet")

# Redis security group: inbound from Lambda only
redis_sg = ec2.SecurityGroup(
    self, "RedisSG",
    vpc=vpc,
    description="Redis - inbound from Lambda only",
    allow_all_outbound=False,
)
redis_sg.add_ingress_rule(lambda_sg, ec2.Port.tcp(6379), "Lambda to Redis")
```

---

## Audit

### CloudTrail

CloudTrail captures all AWS API calls across all regions:

```python
trail = cloudtrail.Trail(
    self, "AgentMailTrail",
    bucket=audit_bucket,
    is_multi_region_trail=True,
    include_global_service_events=True,
    enable_file_validation=True,  # Log file integrity validation
    cloud_watch_logs_group=log_group,
    send_to_cloud_watch_logs=True,
)

# Data events for S3 (track object-level access)
trail.add_s3_event_selector(
    s3_selector=[
        cloudtrail.S3EventSelector(bucket=email_bodies_bucket),
        cloudtrail.S3EventSelector(bucket=attachments_bucket),
    ],
    include_management_events=False,
)

# Data events for DynamoDB (track item-level access)
trail.add_event_selector(
    data_resource_type="AWS::DynamoDB::Table",
    data_resource_values=[main_table.table_arn],
    include_management_events=False,
)
```

### DynamoDB Streams for Data Change Audit

DynamoDB Streams captures every write operation (INSERT, MODIFY, REMOVE) on the main table. This provides a complete audit trail of all data changes:

```python
main_table = dynamodb.Table(
    self, "MainTable",
    # ... other config ...
    stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
)

# Stream processor for audit logging
audit_function = lambda_.Function(
    self, "AuditProcessor",
    # ... other config ...
)
audit_function.add_event_source(
    lambda_event_sources.DynamoEventSource(
        main_table,
        starting_position=lambda_.StartingPosition.LATEST,
        batch_size=100,
        retry_attempts=3,
    )
)
```

---

## Secrets Management

All secrets are stored in AWS Secrets Manager. No secrets are hardcoded, stored in environment variables as plaintext, or committed to source control.

| Secret | Secrets Manager Path | Rotation |
|--------|---------------------|----------|
| SES SMTP credentials | `/agentmail/ses/smtp-credentials` | 90-day automatic rotation |
| Database passwords (if any) | `/agentmail/db/password` | 30-day automatic rotation |
| KMS key IDs | Referenced by alias, not stored as secrets | N/A (KMS manages) |
| Marketplace product code | `/agentmail/marketplace/product-code` | Manual (changes on new listing) |
| Webhook signing keys | Stored encrypted in DynamoDB via KMS | Per-webhook, manual rotation |

### Accessing Secrets in Lambda

```python
import boto3
import json
from functools import lru_cache

secrets_client = boto3.client("secretsmanager")


@lru_cache(maxsize=32)
def get_secret(secret_name: str) -> dict:
    """
    Retrieve a secret from Secrets Manager with in-memory caching.
    Cache is valid for the lifetime of the Lambda execution environment
    (typically 5-15 minutes between invocations).
    """
    response = secrets_client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])
```

---

## OWASP Top 10 Mitigations

### 1. Injection (A03:2021)

| Attack Vector | Mitigation |
|---------------|------------|
| SQL Injection | **Not applicable.** DynamoDB does not use SQL. All queries use the DynamoDB SDK with parameterized key conditions and filter expressions. No string interpolation into queries. |
| NoSQL Injection | DynamoDB SDK uses typed parameters (`ExpressionAttributeValues`), not string interpolation. User input is never directly embedded in key conditions. |
| Command Injection | No shell commands are executed. All Lambda functions process JSON input through validated schemas. |
| LDAP / XPath Injection | Not applicable. No LDAP or XML processing. |

```python
# SAFE: Parameterized DynamoDB query
response = table.query(
    KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
    ExpressionAttributeValues={
        ":pk": f"ORG#{org_id}",      # org_id validated by authorizer
        ":prefix": f"INBOX#{inbox_id}",  # inbox_id validated by schema
    },
)

# UNSAFE (never do this):
# response = table.query(
#     KeyConditionExpression=f"PK = 'ORG#{user_input}'"  # NEVER
# )
```

### 2. Broken Authentication (A07:2021)

| Attack Vector | Mitigation |
|---------------|------------|
| Credential stuffing | API keys are 256-bit random; brute force infeasible. WAF rate limits at 2000 requests per 5-minute window per IP. |
| Key leakage | API keys shown once at creation. SHA-256 hashed in storage. GitHub secret scanning detects `am_` prefix in public repos. |
| Replay attacks | Each API request includes timestamp; stale requests rejected. TLS prevents MITM. |
| Session fixation | No sessions. Each request is independently authenticated via API key. |

### 3. Sensitive Data Exposure (A02:2021)

| Data Type | Protection |
|-----------|------------|
| Email bodies | Encrypted at rest (S3 SSE), encrypted in transit (TLS), access via pre-signed URLs (15-min expiry), VPC endpoint restriction |
| API keys | SHA-256 hashed, never stored plaintext, shown once at creation |
| Webhook secrets | KMS-encrypted, never exposed after creation |
| Customer PII | Encrypted at rest (DynamoDB encryption), not logged, not included in error responses |

### 4. XML External Entities (A05:2017)

**Not applicable.** AgentMail is a JSON-only API. No XML parsing anywhere in the stack. Email MIME parsing uses battle-tested libraries (Python `email` module) that do not process XML entities.

### 5. Broken Access Control (A01:2021)

| Attack Vector | Mitigation |
|---------------|------------|
| IDOR (Insecure Direct Object Reference) | Every resource access validates `org_id` ownership. IAM `dynamodb:LeadingKeys` condition provides hard boundary. |
| Privilege escalation | API key scopes enforce minimum privilege. Scopes are stored server-side and cannot be modified by the API key holder. |
| Cross-tenant access | DynamoDB partition key prefix, S3 path prefix, OpenSearch mandatory filter, IAM conditions. Four independent layers of isolation. |

```python
def get_message(org_id: str, inbox_id: str, message_id: str):
    """Fetch a message with ownership validation at every level."""
    # Level 1: IAM LeadingKeys condition on DynamoDB
    # Level 2: Application-level org_id check
    response = table.get_item(
        Key={
            "PK": f"ORG#{org_id}",
            "SK": f"MSG#{message_id}",
        }
    )

    if "Item" not in response:
        raise NotFoundException("Message not found")

    message = response["Item"]

    # Level 3: Verify inbox ownership
    if message.get("inbox_id") != inbox_id:
        raise ForbiddenException("Message does not belong to this inbox")

    return message
```

### 6. Security Misconfiguration (A05:2021)

| Vector | Mitigation |
|--------|------------|
| Default credentials | No default credentials. All secrets generated randomly and stored in Secrets Manager. |
| Unnecessary services | CDK stacks are purpose-built. No unused services deployed. Security groups deny all by default. |
| Error disclosure | API error responses use generic messages. Stack traces and internal details are logged to CloudWatch, never returned to clients. |
| S3 bucket misconfiguration | Public access block on all buckets. Bucket policies enforce VPC endpoint and HTTPS. No bucket ACLs. |

```python
# CDK guardrails: enforce security settings via Aspects
from aws_cdk import Aspects, IAspect
import jsii

@jsii.implements(IAspect)
class SecurityGuardrails:
    def visit(self, node):
        # Ensure all S3 buckets have encryption
        if isinstance(node, s3.CfnBucket):
            if not node.bucket_encryption:
                raise ValueError(f"S3 bucket {node.node.id} must have encryption enabled")

        # Ensure all Lambda functions have reserved memory limits
        if isinstance(node, lambda_.CfnFunction):
            if not node.memory_size or node.memory_size > 3008:
                raise ValueError(f"Lambda {node.node.id} memory must be set and <= 3008 MB")

Aspects.of(app).add(SecurityGuardrails())
```

### 7. Cross-Site Scripting (A03:2021)

**Not applicable.** AgentMail is an API-only platform with no HTML rendering. API responses are JSON. The API does not serve web pages. Email HTML content is stored and returned as-is (the consuming application is responsible for sanitization before rendering).

### 8. Insecure Deserialization (A08:2017)

| Vector | Mitigation |
|--------|------------|
| Malicious JSON payload | All API inputs validated against JSON Schema before processing. Maximum payload size enforced by API Gateway (10 MB). |
| Pickle / object injection | No pickle, YAML, or other unsafe deserialization. All serialization uses `json.loads()` / `json.dumps()`. |
| Oversized payloads | API Gateway enforces 10 MB limit. Application-level validation enforces per-field limits. |

```python
# JSON Schema validation on all API inputs
from jsonschema import validate, ValidationError

SEND_MESSAGE_SCHEMA = {
    "type": "object",
    "required": ["to", "subject"],
    "properties": {
        "to": {
            "type": "array",
            "items": {"type": "string", "format": "email", "maxLength": 254},
            "minItems": 1,
            "maxItems": 50,
        },
        "subject": {"type": "string", "maxLength": 998},
        "body_text": {"type": "string", "maxLength": 1000000},
        "body_html": {"type": "string", "maxLength": 5000000},
    },
    "additionalProperties": False,
}

def validate_input(data: dict, schema: dict):
    try:
        validate(instance=data, schema=schema)
    except ValidationError as e:
        raise BadRequestException(f"Invalid input: {e.message}")
```

### 9. Insufficient Logging and Monitoring (A09:2021)

| Requirement | Implementation |
|-------------|---------------|
| Authentication events | All auth attempts (success + failure) logged with API key prefix, IP, timestamp |
| Authorization failures | All 403 responses logged with org_id, attempted resource, IP |
| Input validation failures | All 400 responses logged with sanitized input summary |
| High-value transactions | API key creation, webhook creation, domain verification logged to dedicated audit stream |
| Structured logs | All logs are JSON-formatted with consistent fields (timestamp, org_id, request_id, action, outcome) |
| CloudTrail | All AWS API calls logged, log file integrity validation enabled |
| X-Ray tracing | End-to-end request tracing across Lambda, DynamoDB, S3, Kinesis |
| Alerting | CloudWatch Alarms on error rate > 1%, 403 spike, unusual API key creation, metering failures |

```python
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def log_event(action: str, org_id: str, outcome: str, details: dict = None):
    """Structured audit log entry."""
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "org_id": org_id,
        "outcome": outcome,
        "request_id": os.environ.get("_X_AMZN_TRACE_ID", "unknown"),
    }
    if details:
        log_entry["details"] = details

    logger.info(json.dumps(log_entry))


# Usage:
# log_event("api_key.create", org_id, "success", {"key_prefix": "am_a1b2c3"})
# log_event("message.send", org_id, "failure", {"error": "quota_exceeded"})
# log_event("auth.failure", "unknown", "failure", {"ip": "1.2.3.4", "key_prefix": "am_xxxxxx"})
```

### 10. Server-Side Request Forgery (A10:2021)

Webhook delivery is the primary SSRF vector. AgentMail sends HTTP requests to customer-provided URLs, which must be validated to prevent SSRF attacks.

```python
import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),       # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),     # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),    # RFC 1918
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local (AWS metadata!)
    ipaddress.ip_network("100.64.0.0/10"),     # Shared address space
    ipaddress.ip_network("0.0.0.0/8"),         # "This" network
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]


def validate_webhook_url(url: str) -> bool:
    """
    Validate a webhook URL to prevent SSRF attacks.

    Critical: 169.254.169.254 is the AWS EC2 metadata service.
    An attacker could set a webhook URL to http://169.254.169.254/latest/meta-data/
    to steal IAM role credentials from the Lambda execution environment.
    """
    parsed = urlparse(url)

    # Must be HTTPS
    if parsed.scheme != "https":
        raise BadRequestException("Webhook URL must use HTTPS")

    # Must have a valid hostname
    hostname = parsed.hostname
    if not hostname:
        raise BadRequestException("Webhook URL must have a valid hostname")

    # Block IP addresses directly (must use domain names)
    try:
        ipaddress.ip_address(hostname)
        raise BadRequestException("Webhook URLs must use domain names, not IP addresses")
    except ValueError:
        pass  # Not an IP address, good

    # Resolve hostname and check against blocked ranges
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in resolved_ips:
            ip = ipaddress.ip_address(sockaddr[0])
            for blocked in BLOCKED_RANGES:
                if ip in blocked:
                    raise BadRequestException(
                        f"Webhook URL resolves to a private/blocked IP range"
                    )
    except socket.gaierror:
        raise BadRequestException(f"Webhook URL hostname could not be resolved")

    # Block known dangerous hostnames
    dangerous_hosts = [
        "metadata.google.internal",
        "metadata.google",
        "kubernetes.default",
    ]
    if hostname.lower() in dangerous_hosts:
        raise BadRequestException("Webhook URL hostname is blocked")

    return True
```

---

## Compliance Roadmap

### SOC 2 Type II (Recommended -- Start Here)

SOC 2 is the most commonly requested compliance certification for SaaS products. Type II demonstrates that controls are not just designed but operating effectively over a period (typically 6-12 months).

| Trust Service Criteria | AgentMail Coverage |
|-----------------------|-------------------|
| **Security** | IAM least-privilege, encryption at rest/transit, WAF, VPC isolation, audit logging |
| **Availability** | Multi-AZ deployment, auto-scaling, health checks, incident response plan |
| **Processing Integrity** | Input validation, idempotent operations, reconciliation checks |
| **Confidentiality** | Tenant isolation, KMS encryption, pre-signed URLs, no plaintext secrets |
| **Privacy** | Data retention policies, right to deletion, data export capability |

**Timeline**: 3-6 months to prepare, 6-12 month observation period, 1-2 months for audit report. Total: 10-20 months from decision to report.

**Cost**: $30K-$80K for the audit (varies by auditor and scope). Internal preparation cost depends on tooling adopted (Vanta, Drata, or manual).

### HIPAA (If Healthcare Customers)

Required if AgentMail processes Protected Health Information (PHI) -- e.g., a healthcare AI agent handling patient emails.

| Requirement | Implementation |
|-------------|---------------|
| BAA with AWS | AWS provides BAA for eligible services (DynamoDB, S3, Lambda, KMS, CloudWatch, etc.) |
| BAA with customer | Custom EULA amendment via Marketplace private offer |
| PHI encryption | KMS customer-managed keys (mandatory, not optional) |
| Access controls | Already implemented (IAM, API keys, tenant isolation) |
| Audit trail | Already implemented (CloudTrail, DynamoDB Streams, structured logging) |
| Breach notification | Incident response plan with 60-day notification requirement |

### GDPR (If EU Customers)

Required if processing personal data of EU residents.

| Requirement | Implementation |
|-------------|---------------|
| Data residency | Deploy in `eu-west-1` (Ireland) or `eu-central-1` (Frankfurt). All data stays in EU region. |
| Right to erasure | Tenant deprovisioning flow deletes all data within 90 days (accelerate to 30 days on request) |
| Right to portability | Data export API provides all customer data in machine-readable JSON format |
| Data Processing Agreement | Custom EULA amendment via Marketplace private offer |
| Data Protection Impact Assessment | Documented risk assessment for email processing operations |
| Sub-processor disclosure | AWS is the sub-processor; disclosed in DPA |

---

## Incident Response Plan

### Severity Levels

| Level | Definition | Response Time | Example |
|-------|-----------|--------------|---------|
| **SEV-1** | Complete service outage or data breach | 15 minutes (page on-call) | All API requests failing, customer data exposed |
| **SEV-2** | Major feature degraded, multiple customers affected | 30 minutes (page on-call) | Email delivery delayed > 30 minutes, metering pipeline down |
| **SEV-3** | Minor feature degraded, single customer affected | 4 hours (business hours) | One customer's webhooks failing, search latency spike |
| **SEV-4** | Non-impacting issue or improvement opportunity | Next business day | CloudTrail gap in non-primary region, non-critical alarm noise |

### Response Phases

1. **Detection**: CloudWatch Alarm, customer report, automated health check
2. **Triage**: On-call engineer assesses severity, opens incident channel
3. **Containment**: Isolate affected resource (disable Lambda, block IP, revoke key)
4. **Mitigation**: Apply fix or workaround to restore service
5. **Communication**: Customer notification via status page and email (SEV-1/2)
6. **Resolution**: Permanent fix deployed and verified
7. **Post-Mortem**: Blameless review within 72 hours (SEV-1/2), 1 week (SEV-3)

### Post-Mortem Template

```
Incident: [Title]
Date: [Date]
Duration: [Start time] - [End time] ([Duration])
Severity: [SEV-1/2/3/4]
Impact: [Number of customers, number of failed requests, revenue impact]

Timeline:
  [HH:MM] - [Event]
  [HH:MM] - [Event]
  ...

Root Cause:
  [5 Whys analysis]

Action Items:
  [ ] [Action] - Owner: [Name] - Due: [Date]
  [ ] [Action] - Owner: [Name] - Due: [Date]

Lessons Learned:
  - [Lesson]
  - [Lesson]
```

---

## Penetration Testing Considerations

### AWS Penetration Testing Policy

AWS **permits** penetration testing against your own AWS resources without prior notification for the following services:
- EC2 instances, NAT Gateways, ELBs
- RDS
- CloudFront
- Aurora
- API Gateway
- Lambda and Lambda Edge
- Lightsail
- Elastic Beanstalk environments

**Prohibited activities** (require explicit AWS approval):
- DNS zone walking via Amazon Route 53 Hosted Zones
- Denial of Service (DoS) or Distributed DoS simulation
- Port flooding
- Protocol flooding
- Request flooding (API Gateway throttle testing is allowed; overwhelming the service is not)

### Recommended Testing Scope

| Area | Test Focus |
|------|-----------|
| API authentication | Brute force API keys, invalid key formats, expired keys, revoked keys |
| Authorization | Cross-tenant access attempts, IDOR on all resource types, scope escalation |
| Input validation | Oversized payloads, malformed JSON, injection attempts in all string fields |
| SSRF | Webhook URL validation bypass (DNS rebinding, IPv6 mapped addresses, URL encoding tricks) |
| Rate limiting | Verify WAF and API Gateway throttle enforcement under load |
| Data exposure | API error response inspection, timing side channels on auth, enumeration attacks |
| Encryption | TLS version negotiation, cipher suite strength, certificate validation |

### Recommended Frequency

- **Annual**: Full penetration test by external firm
- **Per release**: Automated security scanning (OWASP ZAP, Burp Suite) in CI/CD pipeline
- **Continuous**: Dependency vulnerability scanning (Dependabot, Snyk) on every PR
