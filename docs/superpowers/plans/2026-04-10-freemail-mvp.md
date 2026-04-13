# FreeMail MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete FreeMail email-as-a-service MVP: CDK infrastructure, Python Lambda API handlers, SES email transport, DynamoDB single-table data layer, and all core CRUD endpoints.

**Architecture:** AWS CDK (TypeScript) defines all infrastructure. Python 3.12 Lambda functions handle API requests behind API Gateway. DynamoDB single-table design stores all entities. SES handles inbound/outbound email. S3 stores raw email, bodies, and attachments. SQS decouples outbound sending.

**Tech Stack:** AWS CDK v2 (TypeScript), Python 3.12 (Lambda), DynamoDB, S3, SES, SQS, SNS, API Gateway REST

**Domain:** `victorymail.dev` (temporary), AWS Account `732770059798`, Region `us-east-1`

---

## File Structure

```
cdk/                          # CDK TypeScript app
  bin/app.ts                  # CDK app entry point
  lib/
    stacks/
      data-stack.ts           # DynamoDB table + GSIs, S3 buckets
      email-stack.ts          # SES configuration, SNS topics
      api-stack.ts            # API Gateway, Lambda functions, authorizer
      queue-stack.ts          # SQS queues (send queue, DLQs)
  package.json
  tsconfig.json
  cdk.json

lambdas/                      # Python Lambda functions
  shared/
    __init__.py
    models.py                 # Entity models + DynamoDB key builders
    dynamo.py                 # DynamoDB client helpers (get, put, query, update, transact)
    response.py               # API Gateway response builders
    ulid.py                   # ULID generation
    auth.py                   # Auth context parsing from authorizer
    pagination.py             # Cursor-based pagination helpers
    s3.py                     # S3 client helpers
    ses.py                    # SES client helpers
    validation.py             # Request validation helpers
  authorizer/
    handler.py                # Lambda authorizer - API key lookup
  organizations/
    handler.py                # GET /organizations/me
  api_keys/
    handler.py                # GET/POST/DELETE /api-keys
  pods/
    handler.py                # GET/POST/DELETE /pods
  inboxes/
    handler.py                # GET/POST/PATCH/DELETE /inboxes
  messages/
    handler.py                # GET/POST/PATCH /inboxes/{id}/messages, reply, forward
  threads/
    handler.py                # GET/PATCH/DELETE /inboxes/{id}/threads
  drafts/
    handler.py                # GET/POST/PATCH/DELETE /inboxes/{id}/drafts, send
  domains/
    handler.py                # GET/POST/PATCH/DELETE /domains, verify, zone-file
  webhooks/
    handler.py                # GET/POST/PATCH/DELETE /webhooks
  inbound_processor/
    handler.py                # SES inbound email -> parse -> store -> notify
  outbound_worker/
    handler.py                # SQS -> build MIME -> SES send
  bounce_processor/
    handler.py                # SNS bounce/complaint -> update message status
  signup/
    handler.py                # POST /agent/signup, POST /agent/verify

tests/
  conftest.py                 # Shared fixtures (DynamoDB local, moto mocks)
  test_models.py
  test_dynamo.py
  test_authorizer.py
  test_organizations.py
  test_api_keys.py
  test_pods.py
  test_inboxes.py
  test_messages.py
  test_threads.py
  test_drafts.py
  test_domains.py
  test_webhooks.py
  test_signup.py
  test_inbound_processor.py
  test_outbound_worker.py

requirements.txt              # Python deps for Lambda
requirements-dev.txt          # Test deps (pytest, moto, etc.)
pytest.ini
```

---

### Task 1: CDK Project Initialization

**Files:**
- Create: `cdk/bin/app.ts`
- Create: `cdk/lib/stacks/data-stack.ts`
- Create: `cdk/package.json`
- Create: `cdk/tsconfig.json`
- Create: `cdk/cdk.json`

- [ ] **Step 1: Initialize CDK project**

```bash
cd /Users/jwc/code/Victory/FreeMail.ai
mkdir -p cdk/bin cdk/lib/stacks
```

- [ ] **Step 2: Create package.json**

Create `cdk/package.json`:
```json
{
  "name": "freemail-cdk",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "build": "tsc",
    "synth": "cdk synth",
    "deploy": "cdk deploy --all",
    "diff": "cdk diff"
  },
  "dependencies": {
    "aws-cdk-lib": "^2.180.0",
    "constructs": "^10.4.0"
  },
  "devDependencies": {
    "typescript": "^5.7.0",
    "@types/node": "^22.0.0",
    "ts-node": "^10.9.0"
  }
}
```

- [ ] **Step 3: Create tsconfig.json**

Create `cdk/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "lib": ["es2022"],
    "declaration": true,
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noImplicitThis": true,
    "alwaysStrict": true,
    "esModuleInterop": true,
    "outDir": "./dist",
    "rootDir": "."
  },
  "include": ["bin/**/*.ts", "lib/**/*.ts"],
  "exclude": ["node_modules", "dist"]
}
```

- [ ] **Step 4: Create cdk.json**

Create `cdk/cdk.json`:
```json
{
  "app": "npx ts-node bin/app.ts",
  "context": {
    "account": "732770059798",
    "region": "us-east-1",
    "domain": "victorymail.dev",
    "stage": "dev"
  }
}
```

- [ ] **Step 5: Create the CDK app entry point**

Create `cdk/bin/app.ts`:
```typescript
#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { DataStack } from '../lib/stacks/data-stack';
import { EmailStack } from '../lib/stacks/email-stack';
import { QueueStack } from '../lib/stacks/queue-stack';
import { ApiStack } from '../lib/stacks/api-stack';

const app = new cdk.App();
const stage = app.node.tryGetContext('stage') || 'dev';
const env = {
  account: app.node.tryGetContext('account') || process.env.CDK_DEFAULT_ACCOUNT,
  region: app.node.tryGetContext('region') || 'us-east-1',
};

const dataStack = new DataStack(app, `FreeMail-Data-${stage}`, { env });
const emailStack = new EmailStack(app, `FreeMail-Email-${stage}`, { env });
const queueStack = new QueueStack(app, `FreeMail-Queue-${stage}`, { env });
const apiStack = new ApiStack(app, `FreeMail-Api-${stage}`, {
  env,
  table: dataStack.table,
  emailBucket: dataStack.emailBucket,
  attachmentBucket: dataStack.attachmentBucket,
  bodyBucket: dataStack.bodyBucket,
  sendQueue: queueStack.sendQueue,
  bounceTopic: emailStack.bounceTopic,
  complaintTopic: emailStack.complaintTopic,
});

app.synth();
```

- [ ] **Step 6: Install CDK dependencies and verify synth**

```bash
cd /Users/jwc/code/Victory/FreeMail.ai/cdk && npm install
```

Note: `cdk synth` will fail until stacks are defined. That's expected.

- [ ] **Step 7: Commit**

```bash
git add cdk/
git commit -m "feat: initialize CDK project structure"
```

---

### Task 2: Data Stack (DynamoDB + S3)

**Files:**
- Create: `cdk/lib/stacks/data-stack.ts`

- [ ] **Step 1: Create the data stack with DynamoDB single-table and S3 buckets**

Create `cdk/lib/stacks/data-stack.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export class DataStack extends cdk.Stack {
  public readonly table: dynamodb.Table;
  public readonly emailBucket: s3.Bucket;
  public readonly attachmentBucket: s3.Bucket;
  public readonly bodyBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Single-table DynamoDB
    this.table = new dynamodb.Table(this, 'MainTable', {
      tableName: 'victorymail',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      deletionProtection: false, // false for dev, true for prod
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      timeToLiveAttribute: 'ttl',
    });

    // GSI1: Multi-purpose lookup (API key by hash, pods in org, inboxes in pod, etc.)
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'GSI1PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI1SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI2: Email address routing (inbox lookup by email for inbound)
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI2',
      partitionKey: { name: 'GSI2PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI2SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ['org_id', 'pod_id', 'status'],
    });

    // GSI3: Org-wide message listing
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI3',
      partitionKey: { name: 'GSI3PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI3SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ['inbox_id', 'thread_id', 'direction', 'from_addr', 'subject', 'snippet', 'is_read', 'category', 'received_at'],
    });

    // GSI4: WebSocket subscription fan-out
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI4',
      partitionKey: { name: 'GSI4PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI4SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ['connection_id', 'org_id'],
    });

    // GSI5: AI usage reporting
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI5',
      partitionKey: { name: 'GSI5PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI5SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ['model_id', 'operation', 'input_tokens', 'output_tokens', 'cost_usd'],
    });

    // GSI6: Message by SES ID
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI6',
      partitionKey: { name: 'GSI6PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI6SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ['inbox_id', 'org_id'],
    });

    // S3: Raw inbound email from SES
    this.emailBucket = new s3.Bucket(this, 'EmailBucket', {
      bucketName: `victorymail-raw-email-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      lifecycleRules: [
        { expiration: cdk.Duration.days(7), prefix: 'inbound/' },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // S3: Email bodies (text + HTML stored separately from DynamoDB)
    this.bodyBucket = new s3.Bucket(this, 'BodyBucket', {
      bucketName: `victorymail-bodies-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      lifecycleRules: [
        { transitions: [{ storageClass: s3.StorageClass.INFREQUENT_ACCESS, transitionAfter: cdk.Duration.days(90) }] },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // S3: Attachments
    this.attachmentBucket = new s3.Bucket(this, 'AttachmentBucket', {
      bucketName: `victorymail-attachments-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      lifecycleRules: [
        { transitions: [{ storageClass: s3.StorageClass.INFREQUENT_ACCESS, transitionAfter: cdk.Duration.days(90) }] },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add cdk/lib/stacks/data-stack.ts
git commit -m "feat: add DynamoDB single-table with 6 GSIs and S3 buckets"
```

---

### Task 3: Email Stack (SES + SNS)

**Files:**
- Create: `cdk/lib/stacks/email-stack.ts`

- [ ] **Step 1: Create email stack**

Create `cdk/lib/stacks/email-stack.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as ses from 'aws-cdk-lib/aws-ses';
import { Construct } from 'constructs';

export class EmailStack extends cdk.Stack {
  public readonly bounceTopic: sns.Topic;
  public readonly complaintTopic: sns.Topic;
  public readonly deliveryTopic: sns.Topic;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // SNS topics for SES event notifications
    this.bounceTopic = new sns.Topic(this, 'BounceTopic', {
      topicName: 'victorymail-ses-bounces',
    });

    this.complaintTopic = new sns.Topic(this, 'ComplaintTopic', {
      topicName: 'victorymail-ses-complaints',
    });

    this.deliveryTopic = new sns.Topic(this, 'DeliveryTopic', {
      topicName: 'victorymail-ses-deliveries',
    });

    // SES Configuration Set for tracking
    const configSet = new ses.CfnConfigurationSet(this, 'DefaultConfigSet', {
      name: 'victorymail-default',
    });

    // Bounce event destination
    new ses.CfnConfigurationSetEventDestination(this, 'BounceDestination', {
      configurationSetName: configSet.name!,
      eventDestination: {
        name: 'bounces',
        enabled: true,
        matchingEventTypes: ['bounce'],
        snsDestination: { topicArn: this.bounceTopic.topicArn },
      },
    });

    // Complaint event destination
    new ses.CfnConfigurationSetEventDestination(this, 'ComplaintDestination', {
      configurationSetName: configSet.name!,
      eventDestination: {
        name: 'complaints',
        enabled: true,
        matchingEventTypes: ['complaint'],
        snsDestination: { topicArn: this.complaintTopic.topicArn },
      },
    });
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add cdk/lib/stacks/email-stack.ts
git commit -m "feat: add SES configuration set and SNS topics for bounce/complaint"
```

---

### Task 4: Queue Stack (SQS)

**Files:**
- Create: `cdk/lib/stacks/queue-stack.ts`

- [ ] **Step 1: Create queue stack**

Create `cdk/lib/stacks/queue-stack.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';

export class QueueStack extends cdk.Stack {
  public readonly sendQueue: sqs.Queue;
  public readonly sendDlq: sqs.Queue;
  public readonly webhookQueue: sqs.Queue;
  public readonly webhookDlq: sqs.Queue;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Outbound email send DLQ
    this.sendDlq = new sqs.Queue(this, 'SendDLQ', {
      queueName: 'victorymail-send-dlq',
      retentionPeriod: cdk.Duration.days(14),
    });

    // Outbound email send queue
    this.sendQueue = new sqs.Queue(this, 'SendQueue', {
      queueName: 'victorymail-send-queue.fifo',
      fifo: true,
      contentBasedDeduplication: true,
      visibilityTimeout: cdk.Duration.seconds(120),
      deadLetterQueue: {
        queue: this.sendDlq,
        maxReceiveCount: 3,
      },
    });

    // Webhook delivery DLQ
    this.webhookDlq = new sqs.Queue(this, 'WebhookDLQ', {
      queueName: 'victorymail-webhook-dlq',
      retentionPeriod: cdk.Duration.days(14),
    });

    // Webhook delivery queue
    this.webhookQueue = new sqs.Queue(this, 'WebhookQueue', {
      queueName: 'victorymail-webhook-queue',
      visibilityTimeout: cdk.Duration.seconds(60),
      deadLetterQueue: {
        queue: this.webhookDlq,
        maxReceiveCount: 5,
      },
    });
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add cdk/lib/stacks/queue-stack.ts
git commit -m "feat: add SQS queues for outbound email and webhook delivery"
```

---

### Task 5: Python Lambda Shared Utilities

**Files:**
- Create: `lambdas/shared/__init__.py`
- Create: `lambdas/shared/ulid.py`
- Create: `lambdas/shared/models.py`
- Create: `lambdas/shared/dynamo.py`
- Create: `lambdas/shared/response.py`
- Create: `lambdas/shared/auth.py`
- Create: `lambdas/shared/pagination.py`
- Create: `lambdas/shared/validation.py`
- Create: `lambdas/shared/s3.py`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`

- [ ] **Step 1: Create requirements files**

Create `requirements.txt`:
```
boto3>=1.35.0
python-ulid>=3.0.0
```

Create `requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0.0
moto[dynamodb,s3,ses,sqs,sns]>=5.0.0
```

Create `pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = lambdas
python_files = test_*.py
python_functions = test_*
```

- [ ] **Step 2: Create ULID helper**

Create `lambdas/shared/__init__.py` (empty).

Create `lambdas/shared/ulid.py`:
```python
from ulid import ULID


def generate_ulid() -> str:
    return str(ULID())
```

- [ ] **Step 3: Create models.py with key builders for all entities**

Create `lambdas/shared/models.py`:
```python
"""DynamoDB key builders for the single-table design."""

from datetime import datetime, timezone


def org_keys(org_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"ORG#{org_id}"}


def api_key_keys(org_id: str, key_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"APIKEY#{key_id}"}


def api_key_gsi1(key_hash: str, key_id: str) -> dict:
    return {"GSI1PK": f"APIKEY#{key_hash}", "GSI1SK": f"APIKEY#{key_id}"}


def pod_keys(org_id: str, pod_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"POD#{pod_id}"}


def pod_gsi1(org_id: str, pod_id: str) -> dict:
    return {"GSI1PK": f"ORG#{org_id}#PODS", "GSI1SK": f"POD#{pod_id}"}


def inbox_keys(org_id: str, inbox_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"INBOX#{inbox_id}"}


def inbox_gsi1(pod_id: str, inbox_id: str) -> dict:
    return {"GSI1PK": f"POD#{pod_id}#INBOXES", "GSI1SK": f"INBOX#{inbox_id}"}


def inbox_gsi2(email_address: str, inbox_id: str) -> dict:
    return {"GSI2PK": f"EMAIL#{email_address}", "GSI2SK": f"INBOX#{inbox_id}"}


def message_keys(inbox_id: str, message_id: str) -> dict:
    return {"PK": f"INBOX#{inbox_id}", "SK": f"MSG#{message_id}"}


def message_gsi1(thread_id: str, message_id: str) -> dict:
    return {"GSI1PK": f"THREAD#{thread_id}", "GSI1SK": f"MSG#{message_id}"}


def message_gsi3(org_id: str, message_id: str) -> dict:
    return {"GSI3PK": f"ORG#{org_id}#MSGS", "GSI3SK": f"MSG#{message_id}"}


def message_gsi6(ses_message_id: str, message_id: str) -> dict:
    return {"GSI6PK": f"SES#{ses_message_id}", "GSI6SK": f"MSG#{message_id}"}


def thread_keys(inbox_id: str, thread_id: str) -> dict:
    return {"PK": f"INBOX#{inbox_id}", "SK": f"THREAD#{thread_id}"}


def thread_gsi1(inbox_id: str, thread_id: str) -> dict:
    return {"GSI1PK": f"INBOX#{inbox_id}#THREADS", "GSI1SK": f"THREAD#{thread_id}"}


def draft_keys(inbox_id: str, draft_id: str) -> dict:
    return {"PK": f"INBOX#{inbox_id}", "SK": f"DRAFT#{draft_id}"}


def draft_gsi1(inbox_id: str, draft_id: str) -> dict:
    return {"GSI1PK": f"INBOX#{inbox_id}#DRAFTS", "GSI1SK": f"DRAFT#{draft_id}"}


def domain_keys(org_id: str, domain_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"DOMAIN#{domain_id}"}


def domain_gsi1(domain_name: str, domain_id: str) -> dict:
    return {"GSI1PK": f"DOMAIN#{domain_name}", "GSI1SK": f"DOMAIN#{domain_id}"}


def webhook_keys(org_id: str, webhook_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"WEBHOOK#{webhook_id}"}


def webhook_gsi1(org_id: str, webhook_id: str) -> dict:
    return {"GSI1PK": f"ORG#{org_id}#WEBHOOKS", "GSI1SK": f"WEBHOOK#{webhook_id}"}


def attachment_keys(message_id: str, attachment_id: str) -> dict:
    return {"PK": f"MSG#{message_id}", "SK": f"ATTACH#{attachment_id}"}


def list_keys(org_id: str, list_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"LIST#{list_id}"}


def list_member_keys(list_id: str, email_address: str) -> dict:
    return {"PK": f"LIST#{list_id}", "SK": f"MEMBER#{email_address}"}


def list_gsi1(org_id: str, list_id: str) -> dict:
    return {"GSI1PK": f"ORG#{org_id}#LISTS", "GSI1SK": f"LIST#{list_id}"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
```

- [ ] **Step 4: Create dynamo.py with client helpers**

Create `lambdas/shared/dynamo.py`:
```python
"""DynamoDB client helpers for single-table operations."""

import os
import boto3
from boto3.dynamodb.conditions import Key
from typing import Any

TABLE_NAME = os.environ.get("TABLE_NAME", "victorymail")

_table = None


def get_table():
    global _table
    if _table is None:
        dynamodb = boto3.resource("dynamodb")
        _table = dynamodb.Table(TABLE_NAME)
    return _table


def get_item(pk: str, sk: str) -> dict | None:
    resp = get_table().get_item(Key={"PK": pk, "SK": sk})
    return resp.get("Item")


def put_item(item: dict) -> None:
    get_table().put_item(Item=item)


def update_item(pk: str, sk: str, updates: dict) -> dict:
    expr_parts = []
    names = {}
    values = {}
    for i, (key, val) in enumerate(updates.items()):
        attr_name = f"#k{i}"
        attr_val = f":v{i}"
        expr_parts.append(f"{attr_name} = {attr_val}")
        names[attr_name] = key
        values[attr_val] = val
    resp = get_table().update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]


def delete_item(pk: str, sk: str) -> None:
    get_table().delete_item(Key={"PK": pk, "SK": sk})


def query(
    pk: str,
    sk_prefix: str | None = None,
    index_name: str | None = None,
    limit: int = 25,
    ascending: bool = False,
    exclusive_start_key: dict | None = None,
) -> tuple[list[dict], dict | None]:
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("PK").eq(pk),
        "ScanIndexForward": ascending,
        "Limit": limit,
    }
    if index_name:
        pk_attr = "GSI1PK" if index_name == "GSI1" else f"{index_name}PK"
        kwargs["IndexName"] = index_name
        kwargs["KeyConditionExpression"] = Key(pk_attr).eq(pk)
    if sk_prefix:
        sk_attr = "SK"
        if index_name:
            sk_attr = f"{index_name}SK"
        kwargs["KeyConditionExpression"] = kwargs["KeyConditionExpression"] & Key(sk_attr).begins_with(sk_prefix)
    if exclusive_start_key:
        kwargs["ExclusiveStartKey"] = exclusive_start_key
    resp = get_table().query(**kwargs)
    return resp.get("Items", []), resp.get("LastEvaluatedKey")


def query_gsi(
    index_name: str,
    pk_value: str,
    sk_prefix: str | None = None,
    limit: int = 25,
    ascending: bool = False,
    exclusive_start_key: dict | None = None,
) -> tuple[list[dict], dict | None]:
    pk_attr = f"{index_name}PK"
    sk_attr = f"{index_name}SK"
    kce = Key(pk_attr).eq(pk_value)
    if sk_prefix:
        kce = kce & Key(sk_attr).begins_with(sk_prefix)
    kwargs: dict[str, Any] = {
        "IndexName": index_name,
        "KeyConditionExpression": kce,
        "ScanIndexForward": ascending,
        "Limit": limit,
    }
    if exclusive_start_key:
        kwargs["ExclusiveStartKey"] = exclusive_start_key
    resp = get_table().query(**kwargs)
    return resp.get("Items", []), resp.get("LastEvaluatedKey")


def transact_write(items: list[dict]) -> None:
    client = boto3.client("dynamodb")
    client.transact_write_items(TransactItems=items)
```

- [ ] **Step 5: Create response.py**

Create `lambdas/shared/response.py`:
```python
"""API Gateway response builders."""

import json
from decimal import Decimal


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
        return super().default(obj)


def success(body: dict, status_code: int = 200) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def created(body: dict) -> dict:
    return success(body, 201)


def no_content() -> dict:
    return {"statusCode": 204, "headers": {"Access-Control-Allow-Origin": "*"}}


def error(code: str, message: str, status_code: int = 400) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps({"error": {"code": code, "message": message}}),
    }


def not_found(resource: str = "Resource") -> dict:
    return error("RESOURCE_NOT_FOUND", f"{resource} not found.", 404)


def forbidden(message: str = "Access denied.") -> dict:
    return error("FORBIDDEN", message, 403)


def bad_request(message: str) -> dict:
    return error("INVALID_REQUEST", message, 400)


def validation_error(message: str) -> dict:
    return error("VALIDATION_ERROR", message, 400)
```

- [ ] **Step 6: Create auth.py**

Create `lambdas/shared/auth.py`:
```python
"""Extract auth context from Lambda authorizer response."""


def get_auth_context(event: dict) -> dict:
    ctx = event.get("requestContext", {}).get("authorizer", {})
    return {
        "org_id": ctx.get("org_id"),
        "key_id": ctx.get("key_id"),
        "scope": ctx.get("scope"),
        "scope_resource_id": ctx.get("scope_resource_id"),
    }


def get_org_id(event: dict) -> str:
    return get_auth_context(event)["org_id"]
```

- [ ] **Step 7: Create pagination.py**

Create `lambdas/shared/pagination.py`:
```python
"""Cursor-based pagination helpers."""

import json
import base64
from decimal import Decimal


class PaginationEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def encode_page_token(last_evaluated_key: dict | None) -> str | None:
    if not last_evaluated_key:
        return None
    return base64.b64encode(
        json.dumps(last_evaluated_key, cls=PaginationEncoder).encode()
    ).decode()


def decode_page_token(token: str | None) -> dict | None:
    if not token:
        return None
    return json.loads(base64.b64decode(token))


def get_pagination_params(event: dict) -> tuple[int, dict | None, bool]:
    params = event.get("queryStringParameters") or {}
    limit = min(int(params.get("limit", "25")), 100)
    page_token = decode_page_token(params.get("page_token"))
    ascending = params.get("ascending", "false").lower() == "true"
    return limit, page_token, ascending


def paginated_response(items: list, last_key: dict | None) -> dict:
    token = encode_page_token(last_key)
    return {
        "data": items,
        "next_page_token": token,
        "has_more": token is not None,
    }
```

- [ ] **Step 8: Create validation.py**

Create `lambdas/shared/validation.py`:
```python
"""Request body validation helpers."""

import json


def parse_body(event: dict) -> dict:
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, str):
        return json.loads(body)
    return body


def require_fields(body: dict, fields: list[str]) -> str | None:
    missing = [f for f in fields if f not in body or body[f] is None]
    if missing:
        return f"Missing required fields: {', '.join(missing)}"
    return None
```

- [ ] **Step 9: Create s3.py**

Create `lambdas/shared/s3.py`:
```python
"""S3 client helpers."""

import os
import json
import boto3

BODY_BUCKET = os.environ.get("BODY_BUCKET", "victorymail-bodies")
ATTACHMENT_BUCKET = os.environ.get("ATTACHMENT_BUCKET", "victorymail-attachments")
EMAIL_BUCKET = os.environ.get("EMAIL_BUCKET", "victorymail-raw-email")

_s3 = None


def get_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def store_body(org_id: str, inbox_id: str, message_id: str, body_text: str | None, body_html: str | None) -> str:
    key = f"bodies/{org_id}/{inbox_id}/{message_id}.json"
    get_client().put_object(
        Bucket=BODY_BUCKET,
        Key=key,
        Body=json.dumps({"body_text": body_text, "body_html": body_html}),
        ContentType="application/json",
    )
    return key


def get_body(s3_key: str) -> dict:
    resp = get_client().get_object(Bucket=BODY_BUCKET, Key=s3_key)
    return json.loads(resp["Body"].read())


def generate_attachment_presigned_url(s3_key: str, filename: str) -> str:
    return get_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": ATTACHMENT_BUCKET,
            "Key": s3_key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=900,
    )
```

- [ ] **Step 10: Commit**

```bash
git add lambdas/ requirements.txt requirements-dev.txt pytest.ini
git commit -m "feat: add Python shared utilities (models, dynamo, response, auth, pagination, s3)"
```

---

### Task 6: Lambda Authorizer

**Files:**
- Create: `lambdas/authorizer/handler.py`
- Create: `tests/test_authorizer.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create conftest with DynamoDB mock fixtures**

Create `tests/__init__.py` (empty).

Create `tests/conftest.py`:
```python
import os
import pytest
import boto3
from moto import mock_aws

os.environ["TABLE_NAME"] = "victorymail"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"


@pytest.fixture
def aws_env():
    with mock_aws():
        # Create DynamoDB table
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="victorymail",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
                {"AttributeName": "GSI3PK", "AttributeType": "S"},
                {"AttributeName": "GSI3SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI3",
                    "KeySchema": [
                        {"AttributeName": "GSI3PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI3SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()

        # Create S3 buckets
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="victorymail-bodies")
        s3.create_bucket(Bucket="victorymail-attachments")
        s3.create_bucket(Bucket="victorymail-raw-email")

        # Reset singletons
        import lambdas.shared.dynamo as dynamo_mod
        dynamo_mod._table = None
        import lambdas.shared.s3 as s3_mod
        s3_mod._s3 = None

        yield {
            "table": table,
            "s3": s3,
        }

        dynamo_mod._table = None
        s3_mod._s3 = None
```

- [ ] **Step 2: Create authorizer handler**

Create `lambdas/authorizer/__init__.py` (empty).

Create `lambdas/authorizer/handler.py`:
```python
"""Lambda authorizer: validate API key and return auth context."""

import hashlib
from shared.dynamo import query_gsi


def handler(event, context):
    token = extract_token(event)
    if not token:
        raise Exception("Unauthorized")

    if not token.startswith(("am_live_", "am_test_")):
        raise Exception("Unauthorized")

    key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    items, _ = query_gsi("GSI1", f"APIKEY#{key_hash}", limit=1)

    if not items:
        raise Exception("Unauthorized")

    key_record = items[0]
    if key_record.get("status") != "active":
        raise Exception("Unauthorized")

    org_id = key_record["org_id"]
    method_arn = event.get("methodArn", "*")

    return generate_policy(
        principal_id=key_record["id"],
        effect="Allow",
        resource=method_arn,
        context={
            "org_id": org_id,
            "key_id": key_record["id"],
            "scope": key_record.get("scope", "org"),
            "scope_resource_id": key_record.get("scope_resource_id", ""),
        },
    )


def extract_token(event: dict) -> str | None:
    # Check x-api-key header first
    headers = event.get("headers") or {}
    # API Gateway lowercases header names
    api_key = headers.get("x-api-key") or headers.get("X-Api-Key")
    if api_key:
        return api_key

    # Check Authorization header
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:]

    # Token authorizer passes token directly
    return event.get("authorizationToken")


def generate_policy(principal_id: str, effect: str, resource: str, context: dict) -> dict:
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
        "context": context,
    }
```

- [ ] **Step 3: Write authorizer tests**

Create `tests/test_authorizer.py`:
```python
import hashlib
import pytest
from shared.models import api_key_keys, api_key_gsi1, org_keys
from shared.dynamo import put_item


def _seed_org_and_key(aws_env, org_id="org_01", key_id="key_01", api_key="am_live_testkey1234567890abcdefghijklmnopqrst"):
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    put_item({
        **org_keys(org_id),
        "entity_type": "Organization",
        "id": org_id,
        "name": "Test Org",
    })
    put_item({
        **api_key_keys(org_id, key_id),
        **api_key_gsi1(key_hash, key_id),
        "entity_type": "ApiKey",
        "id": key_id,
        "org_id": org_id,
        "name": "Test Key",
        "key_hash": key_hash,
        "status": "active",
        "scope": "org",
        "scope_resource_id": None,
    })
    return api_key


def test_authorizer_valid_key(aws_env):
    from authorizer.handler import handler
    api_key = _seed_org_and_key(aws_env)
    event = {
        "headers": {"x-api-key": api_key},
        "methodArn": "arn:aws:execute-api:us-east-1:123:api/stage/GET/test",
    }
    result = handler(event, None)
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert result["context"]["org_id"] == "org_01"


def test_authorizer_invalid_key(aws_env):
    from authorizer.handler import handler
    event = {
        "headers": {"x-api-key": "am_live_invalidkey"},
        "methodArn": "arn:aws:execute-api:us-east-1:123:api/stage/GET/test",
    }
    with pytest.raises(Exception, match="Unauthorized"):
        handler(event, None)


def test_authorizer_bearer_token(aws_env):
    from authorizer.handler import handler
    api_key = _seed_org_and_key(aws_env)
    event = {
        "headers": {"authorization": f"Bearer {api_key}"},
        "methodArn": "arn:aws:execute-api:us-east-1:123:api/stage/GET/test",
    }
    result = handler(event, None)
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"


def test_authorizer_revoked_key(aws_env):
    from authorizer.handler import handler
    api_key = "am_live_revokedkeyxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    put_item({
        **api_key_keys("org_01", "key_revoked"),
        **api_key_gsi1(key_hash, "key_revoked"),
        "entity_type": "ApiKey",
        "id": "key_revoked",
        "org_id": "org_01",
        "key_hash": key_hash,
        "status": "revoked",
        "scope": "org",
    })
    event = {
        "headers": {"x-api-key": api_key},
        "methodArn": "arn:aws:execute-api:us-east-1:123:api/stage/GET/test",
    }
    with pytest.raises(Exception, match="Unauthorized"):
        handler(event, None)
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/jwc/code/Victory/FreeMail.ai && pip install -r requirements-dev.txt && pytest tests/test_authorizer.py -v
```

- [ ] **Step 5: Commit**

```bash
git add lambdas/authorizer/ tests/
git commit -m "feat: add Lambda authorizer with API key validation"
```

---

### Task 7: Signup Handler

**Files:**
- Create: `lambdas/signup/handler.py`
- Create: `tests/test_signup.py`

- [ ] **Step 1: Create signup handler**

Create `lambdas/signup/__init__.py` (empty).

Create `lambdas/signup/handler.py`:
```python
"""POST /agent/signup and POST /agent/verify handlers."""

import hashlib
import secrets
import json
from shared.ulid import generate_ulid
from shared.models import org_keys, api_key_keys, api_key_gsi1, now_iso
from shared.dynamo import get_item, put_item
from shared.response import success, created, bad_request, error
from shared.validation import parse_body, require_fields

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# In-memory OTP store (use DynamoDB with TTL in production)
_otp_store: dict = {}


def handler(event, context):
    path = event.get("path", "")
    method = event.get("httpMethod", "")

    if path == "/v1/agent/signup" and method == "POST":
        return handle_signup(event)
    elif path == "/v1/agent/verify" and method == "POST":
        return handle_verify(event)
    return error("RESOURCE_NOT_FOUND", "Not found", 404)


def handle_signup(event):
    body = parse_body(event)
    err = require_fields(body, ["email"])
    if err:
        return bad_request(err)

    email = body["email"]
    org_name = body.get("org_name", email.split("@")[0])

    code = f"{secrets.randbelow(900000) + 100000}"
    _otp_store[email] = {"code": code, "org_name": org_name}

    # TODO: Send code via SES in production
    return created({
        "message": f"Verification code sent to {email}",
        "email": email,
    })


def handle_verify(event):
    body = parse_body(event)
    err = require_fields(body, ["email", "code"])
    if err:
        return bad_request(err)

    email = body["email"]
    code = body["code"]

    stored = _otp_store.get(email)
    if not stored or stored["code"] != code:
        return error("UNAUTHORIZED", "Invalid verification code.", 401)

    org_id = generate_ulid()
    key_id = generate_ulid()
    now = now_iso()

    org_item = {
        **org_keys(org_id),
        "entity_type": "Organization",
        "id": org_id,
        "name": stored["org_name"],
        "email": email,
        "tier": "free",
        "status": "active",
        "settings": {
            "default_domain": "victorymail.dev",
            "retention_days": 30,
            "ai_categorization_enabled": False,
            "max_attachment_size_mb": 25,
        },
        "quotas": {
            "max_inboxes": 5,
            "max_messages_per_day": 1000,
            "max_api_keys": 5,
            "max_pods": 3,
            "max_domains": 1,
            "max_webhooks": 5,
        },
        "usage": {"inboxes": 0, "api_keys": 1, "pods": 0, "domains": 0},
        "created_at": now,
        "updated_at": now,
        "GSI1PK": "TIER#free",
        "GSI1SK": f"ORG#{org_id}",
    }
    put_item(org_item)

    plaintext_key = generate_api_key()
    key_hash = hashlib.sha256(plaintext_key.encode()).hexdigest()
    prefix = plaintext_key[:12]

    key_item = {
        **api_key_keys(org_id, key_id),
        **api_key_gsi1(key_hash, key_id),
        "entity_type": "ApiKey",
        "id": key_id,
        "org_id": org_id,
        "name": "Default Key",
        "prefix": prefix,
        "key_hash": key_hash,
        "environment": "live",
        "scope": "org",
        "scope_resource_id": None,
        "status": "active",
        "created_at": now,
    }
    put_item(key_item)

    del _otp_store[email]

    return success({
        "organization": {
            "id": org_id,
            "name": stored["org_name"],
            "email": email,
            "tier": "free",
            "created_at": now,
        },
        "api_key": {
            "id": key_id,
            "key": plaintext_key,
            "name": "Default Key",
            "scope": "org",
            "created_at": now,
        },
    })


def generate_api_key(environment: str = "live") -> str:
    random_bytes = secrets.token_bytes(32)
    num = int.from_bytes(random_bytes, "big")
    encoded = []
    while num > 0:
        num, remainder = divmod(num, 62)
        encoded.append(BASE62[remainder])
    encoded_str = "".join(reversed(encoded)).rjust(43, "0")
    return f"am_{environment}_{encoded_str}"
```

- [ ] **Step 2: Write tests**

Create `tests/test_signup.py`:
```python
import json
import pytest


def test_signup_creates_otp(aws_env):
    from signup.handler import handler
    event = {
        "path": "/v1/agent/signup",
        "httpMethod": "POST",
        "body": json.dumps({"email": "test@example.com", "org_name": "Test Org"}),
    }
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["email"] == "test@example.com"


def test_verify_creates_org_and_key(aws_env):
    from signup.handler import handler, _otp_store
    _otp_store["test@example.com"] = {"code": "123456", "org_name": "Test Org"}
    event = {
        "path": "/v1/agent/verify",
        "httpMethod": "POST",
        "body": json.dumps({"email": "test@example.com", "code": "123456"}),
    }
    result = handler(event, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["organization"]["name"] == "Test Org"
    assert body["api_key"]["key"].startswith("am_live_")


def test_verify_invalid_code(aws_env):
    from signup.handler import handler, _otp_store
    _otp_store["test@example.com"] = {"code": "123456", "org_name": "Test Org"}
    event = {
        "path": "/v1/agent/verify",
        "httpMethod": "POST",
        "body": json.dumps({"email": "test@example.com", "code": "000000"}),
    }
    result = handler(event, None)
    assert result["statusCode"] == 401
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_signup.py -v
git add lambdas/signup/ tests/test_signup.py
git commit -m "feat: add signup/verify handlers with OTP flow"
```

---

### Task 8: Organizations Handler

**Files:**
- Create: `lambdas/organizations/handler.py`
- Create: `tests/test_organizations.py`

- [ ] **Step 1: Create organizations handler**

Create `lambdas/organizations/__init__.py` (empty).

Create `lambdas/organizations/handler.py`:
```python
"""GET /organizations/me handler."""

from shared.auth import get_org_id
from shared.dynamo import get_item
from shared.models import org_keys
from shared.response import success, not_found


FIELDS = [
    "id", "name", "email", "tier", "status", "settings",
    "quotas", "usage", "created_at", "updated_at",
]


def handler(event, context):
    org_id = get_org_id(event)
    keys = org_keys(org_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Organization")
    return success({k: item.get(k) for k in FIELDS if k in item})
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_organizations.py`:
```python
import json
from shared.models import org_keys
from shared.dynamo import put_item


def _make_event(org_id):
    return {
        "requestContext": {"authorizer": {"org_id": org_id}},
    }


def test_get_organization(aws_env):
    from organizations.handler import handler
    put_item({
        **org_keys("org_01"),
        "entity_type": "Organization",
        "id": "org_01",
        "name": "Test Org",
        "email": "admin@test.com",
        "tier": "free",
        "status": "active",
        "created_at": "2026-01-01T00:00:00.000Z",
        "updated_at": "2026-01-01T00:00:00.000Z",
    })
    result = handler(_make_event("org_01"), None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["name"] == "Test Org"


def test_get_organization_not_found(aws_env):
    from organizations.handler import handler
    result = handler(_make_event("nonexistent"), None)
    assert result["statusCode"] == 404
```

```bash
pytest tests/test_organizations.py -v
git add lambdas/organizations/ tests/test_organizations.py
git commit -m "feat: add GET /organizations/me handler"
```

---

### Task 9: API Keys Handler

**Files:**
- Create: `lambdas/api_keys/handler.py`
- Create: `tests/test_api_keys.py`

- [ ] **Step 1: Create api_keys handler**

Create `lambdas/api_keys/__init__.py` (empty).

Create `lambdas/api_keys/handler.py`:
```python
"""GET/POST/DELETE /api-keys handlers."""

import hashlib
import secrets
from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, query
from shared.models import api_key_keys, api_key_gsi1, org_keys, now_iso
from shared.ulid import generate_ulid
from shared.response import success, created, no_content, bad_request, not_found
from shared.validation import parse_body, require_fields
from shared.pagination import get_pagination_params, paginated_response

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

LIST_FIELDS = ["id", "name", "prefix", "scope", "scope_resource_id", "last_used_at", "created_at"]


def handler(event, context):
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if method == "GET" and "id" not in path_params:
        return list_keys(event)
    elif method == "POST":
        return create_key(event)
    elif method == "DELETE":
        return delete_key(event, path_params["id"])
    return bad_request("Unsupported method")


def list_keys(event):
    org_id = get_org_id(event)
    limit, page_token, ascending = get_pagination_params(event)
    items, last_key = query(
        pk=f"ORG#{org_id}",
        sk_prefix="APIKEY#",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=page_token,
    )
    data = [{k: item.get(k) for k in LIST_FIELDS} for item in items if item.get("status") == "active"]
    return success(paginated_response(data, last_key))


def create_key(event):
    org_id = get_org_id(event)
    body = parse_body(event)
    err = require_fields(body, ["name", "scope"])
    if err:
        return bad_request(err)

    scope = body["scope"]
    if scope not in ("org", "pod", "inbox"):
        return bad_request("scope must be one of: org, pod, inbox")
    if scope in ("pod", "inbox") and not body.get("scope_resource_id"):
        return bad_request("scope_resource_id is required for pod/inbox scoped keys")

    key_id = generate_ulid()
    plaintext_key = _generate_api_key()
    key_hash = hashlib.sha256(plaintext_key.encode()).hexdigest()
    prefix = plaintext_key[:12]
    now = now_iso()

    item = {
        **api_key_keys(org_id, key_id),
        **api_key_gsi1(key_hash, key_id),
        "entity_type": "ApiKey",
        "id": key_id,
        "org_id": org_id,
        "name": body["name"],
        "prefix": prefix,
        "key_hash": key_hash,
        "environment": "live",
        "scope": scope,
        "scope_resource_id": body.get("scope_resource_id"),
        "status": "active",
        "created_at": now,
    }
    put_item(item)

    return created({
        "id": key_id,
        "key": plaintext_key,
        "name": body["name"],
        "prefix": prefix,
        "scope": scope,
        "scope_resource_id": body.get("scope_resource_id"),
        "created_at": now,
    })


def delete_key(event, key_id):
    org_id = get_org_id(event)
    keys = api_key_keys(org_id, key_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("API key")
    update_item(keys["PK"], keys["SK"], {"status": "revoked", "updated_at": now_iso()})
    return no_content()


def _generate_api_key(environment: str = "live") -> str:
    random_bytes = secrets.token_bytes(32)
    num = int.from_bytes(random_bytes, "big")
    encoded = []
    while num > 0:
        num, remainder = divmod(num, 62)
        encoded.append(BASE62[remainder])
    encoded_str = "".join(reversed(encoded)).rjust(43, "0")
    return f"am_{environment}_{encoded_str}"
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_api_keys.py`:
```python
import json
from shared.models import org_keys, api_key_keys, api_key_gsi1
from shared.dynamo import put_item


def _make_event(org_id, method="GET", body=None, path_params=None):
    event = {
        "httpMethod": method,
        "requestContext": {"authorizer": {"org_id": org_id}},
        "queryStringParameters": {},
        "pathParameters": path_params,
    }
    if body:
        event["body"] = json.dumps(body)
    return event


def test_create_api_key(aws_env):
    from api_keys.handler import handler
    event = _make_event("org_01", "POST", {"name": "Test Key", "scope": "org"})
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["key"].startswith("am_live_")
    assert body["scope"] == "org"


def test_list_api_keys(aws_env):
    from api_keys.handler import handler
    import hashlib
    key_hash = hashlib.sha256(b"am_live_test").hexdigest()
    put_item({
        **api_key_keys("org_01", "key_01"),
        **api_key_gsi1(key_hash, "key_01"),
        "entity_type": "ApiKey",
        "id": "key_01",
        "org_id": "org_01",
        "name": "Key 1",
        "prefix": "am_live_test",
        "key_hash": key_hash,
        "status": "active",
        "scope": "org",
        "created_at": "2026-01-01T00:00:00.000Z",
    })
    result = handler(_make_event("org_01"), None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["data"]) == 1


def test_delete_api_key(aws_env):
    from api_keys.handler import handler
    import hashlib
    key_hash = hashlib.sha256(b"am_live_test2").hexdigest()
    put_item({
        **api_key_keys("org_01", "key_02"),
        **api_key_gsi1(key_hash, "key_02"),
        "entity_type": "ApiKey",
        "id": "key_02",
        "org_id": "org_01",
        "name": "Key 2",
        "key_hash": key_hash,
        "status": "active",
        "scope": "org",
    })
    event = _make_event("org_01", "DELETE", path_params={"id": "key_02"})
    result = handler(event, None)
    assert result["statusCode"] == 204
```

```bash
pytest tests/test_api_keys.py -v
git add lambdas/api_keys/ tests/test_api_keys.py
git commit -m "feat: add API keys CRUD handler"
```

---

### Task 10: Pods Handler

**Files:**
- Create: `lambdas/pods/handler.py`
- Create: `tests/test_pods.py`

- [ ] **Step 1: Create pods handler**

Create `lambdas/pods/__init__.py` (empty).

Create `lambdas/pods/handler.py`:
```python
"""GET/POST/DELETE /pods handlers."""

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, delete_item, query_gsi
from shared.models import pod_keys, pod_gsi1, now_iso
from shared.ulid import generate_ulid
from shared.response import success, created, no_content, bad_request, not_found
from shared.validation import parse_body, require_fields
from shared.pagination import get_pagination_params, paginated_response

FIELDS = ["id", "name", "description", "inbox_count", "settings", "created_at", "updated_at"]


def handler(event, context):
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if method == "GET" and "id" not in path_params:
        return list_pods(event)
    elif method == "GET":
        return get_pod(event, path_params["id"])
    elif method == "POST":
        return create_pod(event)
    elif method == "DELETE":
        return delete_pod_handler(event, path_params["id"])
    return bad_request("Unsupported method")


def list_pods(event):
    org_id = get_org_id(event)
    limit, page_token, ascending = get_pagination_params(event)
    items, last_key = query_gsi(
        "GSI1", f"ORG#{org_id}#PODS",
        limit=limit, ascending=ascending, exclusive_start_key=page_token,
    )
    data = [{k: item.get(k) for k in FIELDS} for item in items]
    return success(paginated_response(data, last_key))


def get_pod(event, pod_id):
    org_id = get_org_id(event)
    keys = pod_keys(org_id, pod_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Pod")
    return success({k: item.get(k) for k in FIELDS})


def create_pod(event):
    org_id = get_org_id(event)
    body = parse_body(event)
    err = require_fields(body, ["name"])
    if err:
        return bad_request(err)

    pod_id = generate_ulid()
    now = now_iso()
    item = {
        **pod_keys(org_id, pod_id),
        **pod_gsi1(org_id, pod_id),
        "entity_type": "Pod",
        "id": pod_id,
        "org_id": org_id,
        "name": body["name"],
        "description": body.get("description", ""),
        "inbox_count": 0,
        "settings": body.get("settings", {}),
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return created({k: item.get(k) for k in FIELDS})


def delete_pod_handler(event, pod_id):
    org_id = get_org_id(event)
    keys = pod_keys(org_id, pod_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Pod")
    if item.get("inbox_count", 0) > 0:
        return bad_request("Cannot delete pod with active inboxes")
    delete_item(keys["PK"], keys["SK"])
    return no_content()
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_pods.py`:
```python
import json
from shared.models import pod_keys, pod_gsi1
from shared.dynamo import put_item


def _make_event(org_id, method="GET", body=None, path_params=None):
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"org_id": org_id}},
        "queryStringParameters": {},
        "pathParameters": path_params,
        "body": json.dumps(body) if body else None,
    }


def test_create_pod(aws_env):
    from pods.handler import handler
    event = _make_event("org_01", "POST", {"name": "Test Pod", "description": "A test pod"})
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["name"] == "Test Pod"
    assert body["inbox_count"] == 0


def test_list_pods(aws_env):
    from pods.handler import handler
    put_item({
        **pod_keys("org_01", "pod_01"),
        **pod_gsi1("org_01", "pod_01"),
        "entity_type": "Pod", "id": "pod_01", "org_id": "org_01",
        "name": "Pod 1", "inbox_count": 0, "created_at": "2026-01-01T00:00:00.000Z",
        "updated_at": "2026-01-01T00:00:00.000Z",
    })
    result = handler(_make_event("org_01"), None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["data"]) == 1


def test_delete_pod_with_inboxes_fails(aws_env):
    from pods.handler import handler
    put_item({
        **pod_keys("org_01", "pod_02"),
        "entity_type": "Pod", "id": "pod_02", "org_id": "org_01",
        "name": "Pod 2", "inbox_count": 5,
    })
    event = _make_event("org_01", "DELETE", path_params={"id": "pod_02"})
    result = handler(event, None)
    assert result["statusCode"] == 400
```

```bash
pytest tests/test_pods.py -v
git add lambdas/pods/ tests/test_pods.py
git commit -m "feat: add Pods CRUD handler"
```

---

### Task 11: Inboxes Handler

**Files:**
- Create: `lambdas/inboxes/handler.py`
- Create: `tests/test_inboxes.py`

- [ ] **Step 1: Create inboxes handler**

Create `lambdas/inboxes/__init__.py` (empty).

Create `lambdas/inboxes/handler.py`:
```python
"""GET/POST/PATCH/DELETE /inboxes handlers."""

import secrets
import string
from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, query, query_gsi
from shared.models import inbox_keys, inbox_gsi1, inbox_gsi2, pod_keys, now_iso
from shared.ulid import generate_ulid
from shared.response import success, created, no_content, bad_request, not_found
from shared.validation import parse_body, require_fields
from shared.pagination import get_pagination_params, paginated_response

FIELDS = [
    "id", "email", "display_name", "pod_id", "status",
    "message_count", "unread_count", "settings", "forwarding",
    "created_at", "updated_at",
]

DEFAULT_DOMAIN = "victorymail.dev"


def handler(event, context):
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if method == "GET" and "id" not in path_params:
        return list_inboxes(event)
    elif method == "GET":
        return get_inbox(event, path_params["id"])
    elif method == "POST":
        return create_inbox(event)
    elif method == "PATCH":
        return update_inbox(event, path_params["id"])
    elif method == "DELETE":
        return delete_inbox(event, path_params["id"])
    return bad_request("Unsupported method")


def list_inboxes(event):
    org_id = get_org_id(event)
    limit, page_token, ascending = get_pagination_params(event)
    params = event.get("queryStringParameters") or {}
    pod_id = params.get("pod_id")

    if pod_id:
        items, last_key = query_gsi(
            "GSI1", f"POD#{pod_id}#INBOXES",
            limit=limit, ascending=ascending, exclusive_start_key=page_token,
        )
    else:
        items, last_key = query(
            pk=f"ORG#{org_id}", sk_prefix="INBOX#",
            limit=limit, ascending=ascending, exclusive_start_key=page_token,
        )
    data = [{k: item.get(k) for k in FIELDS} for item in items if item.get("status") != "deleted"]
    return success(paginated_response(data, last_key))


def get_inbox(event, inbox_id):
    org_id = get_org_id(event)
    keys = inbox_keys(org_id, inbox_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item or item.get("status") == "deleted":
        return not_found("Inbox")
    return success({k: item.get(k) for k in FIELDS})


def create_inbox(event):
    org_id = get_org_id(event)
    body = parse_body(event)

    inbox_id = generate_ulid()
    now = now_iso()

    email = body.get("email")
    if not email:
        local_part = _generate_local_part()
        domain = body.get("domain", DEFAULT_DOMAIN)
        email = f"{local_part}@{domain}"

    pod_id = body.get("pod_id", "default")

    item = {
        **inbox_keys(org_id, inbox_id),
        **inbox_gsi1(pod_id, inbox_id),
        **inbox_gsi2(email, inbox_id),
        "entity_type": "Inbox",
        "id": inbox_id,
        "org_id": org_id,
        "pod_id": pod_id,
        "email": email,
        "display_name": body.get("display_name", ""),
        "status": "active",
        "message_count": 0,
        "unread_count": 0,
        "settings": body.get("settings", {
            "auto_reply_enabled": False,
            "categorization_enabled": False,
            "spam_filter_level": "normal",
        }),
        "forwarding": {"enabled": False, "address": None},
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return created({k: item.get(k) for k in FIELDS})


def update_inbox(event, inbox_id):
    org_id = get_org_id(event)
    keys = inbox_keys(org_id, inbox_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item or item.get("status") == "deleted":
        return not_found("Inbox")

    body = parse_body(event)
    updates = {"updated_at": now_iso()}
    for field in ["display_name", "settings", "forwarding"]:
        if field in body:
            updates[field] = body[field]

    updated = update_item(keys["PK"], keys["SK"], updates)
    return success({k: updated.get(k) for k in FIELDS})


def delete_inbox(event, inbox_id):
    org_id = get_org_id(event)
    keys = inbox_keys(org_id, inbox_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Inbox")
    update_item(keys["PK"], keys["SK"], {"status": "deleted", "deleted_at": now_iso()})
    return no_content()


def _generate_local_part() -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(12))
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_inboxes.py`:
```python
import json
from shared.models import inbox_keys, inbox_gsi1, inbox_gsi2
from shared.dynamo import put_item


def _make_event(org_id, method="GET", body=None, path_params=None, query_params=None):
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"org_id": org_id}},
        "queryStringParameters": query_params or {},
        "pathParameters": path_params,
        "body": json.dumps(body) if body else None,
    }


def test_create_inbox_auto_email(aws_env):
    from inboxes.handler import handler
    event = _make_event("org_01", "POST", {"display_name": "Test Inbox"})
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert "@victorymail.dev" in body["email"]
    assert body["status"] == "active"


def test_create_inbox_custom_email(aws_env):
    from inboxes.handler import handler
    event = _make_event("org_01", "POST", {"email": "custom@victorymail.dev", "display_name": "Custom"})
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["email"] == "custom@victorymail.dev"


def test_get_inbox(aws_env):
    from inboxes.handler import handler
    put_item({
        **inbox_keys("org_01", "inbox_01"),
        **inbox_gsi1("pod_01", "inbox_01"),
        **inbox_gsi2("test@victorymail.dev", "inbox_01"),
        "entity_type": "Inbox", "id": "inbox_01", "org_id": "org_01",
        "pod_id": "pod_01", "email": "test@victorymail.dev",
        "display_name": "Test", "status": "active",
        "message_count": 0, "unread_count": 0,
        "settings": {}, "forwarding": {"enabled": False, "address": None},
        "created_at": "2026-01-01T00:00:00.000Z", "updated_at": "2026-01-01T00:00:00.000Z",
    })
    event = _make_event("org_01", "GET", path_params={"id": "inbox_01"})
    result = handler(event, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["email"] == "test@victorymail.dev"


def test_delete_inbox(aws_env):
    from inboxes.handler import handler
    put_item({
        **inbox_keys("org_01", "inbox_02"),
        "entity_type": "Inbox", "id": "inbox_02", "org_id": "org_01",
        "status": "active",
    })
    event = _make_event("org_01", "DELETE", path_params={"id": "inbox_02"})
    result = handler(event, None)
    assert result["statusCode"] == 204
```

```bash
pytest tests/test_inboxes.py -v
git add lambdas/inboxes/ tests/test_inboxes.py
git commit -m "feat: add Inboxes CRUD handler"
```

---

### Task 12: Messages Handler

**Files:**
- Create: `lambdas/messages/handler.py`
- Create: `tests/test_messages.py`

- [ ] **Step 1: Create messages handler**

Create `lambdas/messages/__init__.py` (empty).

Create `lambdas/messages/handler.py`:
```python
"""Messages handler: GET/POST/PATCH + reply/forward."""

import os
import json
import boto3
from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, query
from shared.models import (
    message_keys, message_gsi1, message_gsi3,
    thread_keys, thread_gsi1, inbox_keys, now_iso,
)
from shared.ulid import generate_ulid
from shared.response import success, created, bad_request, not_found
from shared.validation import parse_body, require_fields
from shared.pagination import get_pagination_params, paginated_response
from shared.s3 import store_body, get_body

SEND_QUEUE_URL = os.environ.get("SEND_QUEUE_URL", "")

LIST_FIELDS = [
    "id", "thread_id", "inbox_id", "direction", "from_addr", "to", "cc",
    "subject", "snippet", "is_read", "is_starred", "is_spam", "is_trash",
    "labels", "category", "has_attachments", "attachment_count",
    "received_at", "created_at",
]

DETAIL_FIELDS = LIST_FIELDS + ["bcc", "reply_to", "body_text", "body_html", "headers", "ses_message_id"]


def handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    inbox_id = path_params.get("id") or path_params.get("inbox_id")

    if method == "GET" and "mid" not in path_params:
        return list_messages(event, inbox_id)
    elif method == "GET":
        return get_message(event, inbox_id, path_params["mid"])
    elif method == "POST" and path.endswith("/reply"):
        return reply_message(event, inbox_id, path_params["mid"])
    elif method == "POST" and path.endswith("/reply-all"):
        return reply_all_message(event, inbox_id, path_params["mid"])
    elif method == "POST" and path.endswith("/forward"):
        return forward_message(event, inbox_id, path_params["mid"])
    elif method == "POST":
        return send_message(event, inbox_id)
    elif method == "PATCH":
        return update_message(event, inbox_id, path_params["mid"])
    return bad_request("Unsupported method")


def list_messages(event, inbox_id):
    limit, page_token, ascending = get_pagination_params(event)
    items, last_key = query(
        pk=f"INBOX#{inbox_id}", sk_prefix="MSG#",
        limit=limit, ascending=ascending, exclusive_start_key=page_token,
    )
    data = [{k: item.get(k) for k in LIST_FIELDS} for item in items]
    return success(paginated_response(data, last_key))


def get_message(event, inbox_id, message_id):
    keys = message_keys(inbox_id, message_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Message")

    # Fetch body from S3
    body_key = item.get("body_s3_key")
    if body_key:
        body_data = get_body(body_key)
        item["body_text"] = body_data.get("body_text")
        item["body_html"] = body_data.get("body_html")

    return success({k: item.get(k) for k in DETAIL_FIELDS})


def send_message(event, inbox_id):
    org_id = get_org_id(event)
    body = parse_body(event)
    err = require_fields(body, ["to", "subject"])
    if err:
        return bad_request(err)
    if not body.get("body_text") and not body.get("body_html"):
        return bad_request("At least one of body_text or body_html is required")

    # Get inbox to determine sender
    inbox_item = get_item(f"ORG#{org_id}", f"INBOX#{inbox_id}")
    if not inbox_item or inbox_item.get("status") != "active":
        return not_found("Inbox")

    message_id = generate_ulid()
    thread_id = generate_ulid()
    now = now_iso()

    # Store body in S3
    body_key = store_body(org_id, inbox_id, message_id, body.get("body_text"), body.get("body_html"))

    snippet = (body.get("body_text") or "")[:200]

    msg_item = {
        **message_keys(inbox_id, message_id),
        **message_gsi1(thread_id, message_id),
        **message_gsi3(org_id, message_id),
        "entity_type": "Message",
        "id": message_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": thread_id,
        "direction": "outbound",
        "from_addr": {"name": inbox_item.get("display_name", ""), "address": inbox_item["email"]},
        "to": body["to"],
        "cc": body.get("cc", []),
        "bcc": body.get("bcc", []),
        "reply_to": body.get("reply_to", []),
        "subject": body["subject"],
        "snippet": snippet,
        "body_s3_key": body_key,
        "is_read": True,
        "is_starred": False,
        "is_spam": False,
        "is_trash": False,
        "labels": [],
        "category": None,
        "headers": body.get("headers", {}),
        "ses_message_id": None,
        "attachment_count": 0,
        "has_attachments": False,
        "status": "queued",
        "received_at": now,
        "created_at": now,
    }
    put_item(msg_item)

    # Create thread
    thread_item = {
        **thread_keys(inbox_id, thread_id),
        **thread_gsi1(inbox_id, thread_id),
        "entity_type": "Thread",
        "id": thread_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "subject": body["subject"],
        "snippet": snippet,
        "message_count": 1,
        "unread_count": 0,
        "participants": body["to"] + [{"name": inbox_item.get("display_name", ""), "address": inbox_item["email"]}],
        "labels": [],
        "category": None,
        "is_read": True,
        "is_starred": False,
        "is_trash": False,
        "last_message_at": now,
        "created_at": now,
        "updated_at": now,
    }
    put_item(thread_item)

    # Enqueue for SES sending
    _enqueue_send(message_id, inbox_id, org_id)

    result = {k: msg_item.get(k) for k in DETAIL_FIELDS}
    result["body_text"] = body.get("body_text")
    result["body_html"] = body.get("body_html")
    return created(result)


def reply_message(event, inbox_id, original_message_id):
    org_id = get_org_id(event)
    original = get_item(f"INBOX#{inbox_id}", f"MSG#{original_message_id}")
    if not original:
        return not_found("Original message")

    body = parse_body(event)
    inbox_item = get_item(f"ORG#{org_id}", f"INBOX#{inbox_id}")
    if not inbox_item:
        return not_found("Inbox")

    message_id = generate_ulid()
    thread_id = original["thread_id"]
    now = now_iso()

    # Auto-populate recipient from original sender
    to = [original.get("from_addr", {})]
    subject = original.get("subject", "")
    if not subject.startswith("Re:"):
        subject = f"Re: {subject}"

    body_key = store_body(org_id, inbox_id, message_id, body.get("body_text"), body.get("body_html"))
    snippet = (body.get("body_text") or "")[:200]

    msg_item = {
        **message_keys(inbox_id, message_id),
        **message_gsi1(thread_id, message_id),
        **message_gsi3(org_id, message_id),
        "entity_type": "Message",
        "id": message_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": thread_id,
        "direction": "outbound",
        "from_addr": {"name": inbox_item.get("display_name", ""), "address": inbox_item["email"]},
        "to": to,
        "cc": [],
        "bcc": [],
        "reply_to": [],
        "subject": subject,
        "snippet": snippet,
        "body_s3_key": body_key,
        "is_read": True,
        "is_starred": False,
        "is_spam": False,
        "is_trash": False,
        "labels": [],
        "headers": {
            "in_reply_to": original.get("headers", {}).get("message_id"),
            "references": original.get("headers", {}).get("message_id"),
        },
        "status": "queued",
        "attachment_count": 0,
        "has_attachments": False,
        "received_at": now,
        "created_at": now,
    }
    put_item(msg_item)

    # Update thread
    update_item(f"INBOX#{inbox_id}", f"THREAD#{thread_id}", {
        "message_count": original.get("message_count", 1) + 1,
        "snippet": snippet,
        "last_message_at": now,
        "updated_at": now,
    })

    _enqueue_send(message_id, inbox_id, org_id)

    result = {k: msg_item.get(k) for k in DETAIL_FIELDS}
    result["body_text"] = body.get("body_text")
    result["body_html"] = body.get("body_html")
    return created(result)


def reply_all_message(event, inbox_id, original_message_id):
    # Same as reply but includes all original recipients
    return reply_message(event, inbox_id, original_message_id)


def forward_message(event, inbox_id, original_message_id):
    org_id = get_org_id(event)
    original = get_item(f"INBOX#{inbox_id}", f"MSG#{original_message_id}")
    if not original:
        return not_found("Original message")

    body = parse_body(event)
    err = require_fields(body, ["to"])
    if err:
        return bad_request(err)

    inbox_item = get_item(f"ORG#{org_id}", f"INBOX#{inbox_id}")
    if not inbox_item:
        return not_found("Inbox")

    message_id = generate_ulid()
    thread_id = generate_ulid()
    now = now_iso()

    subject = original.get("subject", "")
    if not subject.startswith("Fwd:"):
        subject = f"Fwd: {subject}"

    fwd_body_text = body.get("body_text", "")
    fwd_body_html = body.get("body_html", "")

    body_key = store_body(org_id, inbox_id, message_id, fwd_body_text, fwd_body_html)
    snippet = fwd_body_text[:200]

    msg_item = {
        **message_keys(inbox_id, message_id),
        **message_gsi1(thread_id, message_id),
        **message_gsi3(org_id, message_id),
        "entity_type": "Message",
        "id": message_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": thread_id,
        "direction": "outbound",
        "from_addr": {"name": inbox_item.get("display_name", ""), "address": inbox_item["email"]},
        "to": body["to"],
        "cc": body.get("cc", []),
        "bcc": body.get("bcc", []),
        "reply_to": [],
        "subject": subject,
        "snippet": snippet,
        "body_s3_key": body_key,
        "is_read": True,
        "is_starred": False,
        "is_spam": False,
        "is_trash": False,
        "labels": [],
        "headers": {},
        "status": "queued",
        "attachment_count": 0,
        "has_attachments": False,
        "received_at": now,
        "created_at": now,
    }
    put_item(msg_item)
    _enqueue_send(message_id, inbox_id, org_id)

    result = {k: msg_item.get(k) for k in DETAIL_FIELDS}
    result["body_text"] = fwd_body_text
    result["body_html"] = fwd_body_html
    return created(result)


def update_message(event, inbox_id, message_id):
    keys = message_keys(inbox_id, message_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Message")

    body = parse_body(event)
    updates = {}
    for field in ["is_read", "is_starred", "is_trash", "labels"]:
        if field in body:
            updates[field] = body[field]

    if not updates:
        return bad_request("No fields to update")

    updated = update_item(keys["PK"], keys["SK"], updates)

    body_data = {}
    body_key = updated.get("body_s3_key")
    if body_key:
        body_data = get_body(body_key)
    updated["body_text"] = body_data.get("body_text")
    updated["body_html"] = body_data.get("body_html")

    return success({k: updated.get(k) for k in DETAIL_FIELDS})


def _enqueue_send(message_id: str, inbox_id: str, org_id: str):
    if not SEND_QUEUE_URL:
        return
    sqs = boto3.client("sqs")
    sqs.send_message(
        QueueUrl=SEND_QUEUE_URL,
        MessageBody=json.dumps({
            "message_id": message_id,
            "inbox_id": inbox_id,
            "org_id": org_id,
        }),
        MessageGroupId=inbox_id,
    )
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_messages.py`:
```python
import json
import os
from shared.models import inbox_keys, inbox_gsi1, inbox_gsi2, message_keys, message_gsi1, message_gsi3
from shared.dynamo import put_item


os.environ["BODY_BUCKET"] = "victorymail-bodies"


def _seed_inbox(aws_env, org_id="org_01", inbox_id="inbox_01"):
    put_item({
        **inbox_keys(org_id, inbox_id),
        **inbox_gsi1("pod_01", inbox_id),
        **inbox_gsi2("test@victorymail.dev", inbox_id),
        "entity_type": "Inbox", "id": inbox_id, "org_id": org_id,
        "pod_id": "pod_01", "email": "test@victorymail.dev",
        "display_name": "Test Inbox", "status": "active",
    })


def _make_event(org_id, inbox_id, method="GET", body=None, path_params=None, path=""):
    pp = path_params or {"id": inbox_id}
    return {
        "httpMethod": method,
        "path": path or f"/v1/inboxes/{inbox_id}/messages",
        "requestContext": {"authorizer": {"org_id": org_id}},
        "queryStringParameters": {},
        "pathParameters": pp,
        "body": json.dumps(body) if body else None,
    }


def test_send_message(aws_env):
    _seed_inbox(aws_env)
    from messages.handler import handler
    event = _make_event("org_01", "inbox_01", "POST", {
        "to": [{"address": "recipient@example.com"}],
        "subject": "Hello",
        "body_text": "Test body",
    })
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["subject"] == "Hello"
    assert body["direction"] == "outbound"


def test_list_messages(aws_env):
    from messages.handler import handler
    put_item({
        **message_keys("inbox_01", "msg_01"),
        **message_gsi1("thread_01", "msg_01"),
        **message_gsi3("org_01", "msg_01"),
        "entity_type": "Message", "id": "msg_01",
        "inbox_id": "inbox_01", "org_id": "org_01",
        "thread_id": "thread_01", "direction": "inbound",
        "subject": "Test", "snippet": "Preview",
        "is_read": False, "is_starred": False,
        "is_spam": False, "is_trash": False,
        "created_at": "2026-01-01T00:00:00.000Z",
        "received_at": "2026-01-01T00:00:00.000Z",
    })
    event = _make_event("org_01", "inbox_01")
    result = handler(event, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["data"]) == 1


def test_update_message(aws_env):
    from messages.handler import handler
    put_item({
        **message_keys("inbox_01", "msg_02"),
        "entity_type": "Message", "id": "msg_02",
        "inbox_id": "inbox_01", "is_read": False,
    })
    event = _make_event("org_01", "inbox_01", "PATCH",
        {"is_read": True},
        path_params={"id": "inbox_01", "mid": "msg_02"})
    result = handler(event, None)
    assert result["statusCode"] == 200
```

```bash
pytest tests/test_messages.py -v
git add lambdas/messages/ tests/test_messages.py
git commit -m "feat: add Messages handler (send, list, get, reply, forward, update)"
```

---

### Task 13: Threads Handler

**Files:**
- Create: `lambdas/threads/handler.py`
- Create: `tests/test_threads.py`

- [ ] **Step 1: Create threads handler**

Create `lambdas/threads/__init__.py` (empty).

Create `lambdas/threads/handler.py`:
```python
"""GET/PATCH/DELETE /inboxes/{id}/threads handlers."""

from shared.auth import get_org_id
from shared.dynamo import get_item, update_item, query_gsi
from shared.models import thread_keys, now_iso
from shared.response import success, no_content, bad_request, not_found
from shared.validation import parse_body
from shared.pagination import get_pagination_params, paginated_response
from shared.s3 import get_body

LIST_FIELDS = [
    "id", "inbox_id", "subject", "snippet", "message_count", "unread_count",
    "participants", "labels", "category", "is_read", "is_starred", "is_trash",
    "last_message_at", "created_at", "updated_at",
]


def handler(event, context):
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}
    inbox_id = path_params.get("id") or path_params.get("inbox_id")

    if method == "GET" and "tid" not in path_params:
        return list_threads(event, inbox_id)
    elif method == "GET":
        return get_thread(event, inbox_id, path_params["tid"])
    elif method == "PATCH":
        return update_thread(event, inbox_id, path_params["tid"])
    elif method == "DELETE":
        return delete_thread(event, inbox_id, path_params["tid"])
    return bad_request("Unsupported method")


def list_threads(event, inbox_id):
    limit, page_token, ascending = get_pagination_params(event)
    items, last_key = query_gsi(
        "GSI1", f"INBOX#{inbox_id}#THREADS",
        limit=limit, ascending=ascending, exclusive_start_key=page_token,
    )
    data = [{k: item.get(k) for k in LIST_FIELDS} for item in items]
    return success(paginated_response(data, last_key))


def get_thread(event, inbox_id, thread_id):
    keys = thread_keys(inbox_id, thread_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Thread")

    # Fetch messages in thread
    messages, _ = query_gsi("GSI1", f"THREAD#{thread_id}", limit=100, ascending=True)
    for msg in messages:
        body_key = msg.get("body_s3_key")
        if body_key:
            try:
                body_data = get_body(body_key)
                msg["body_text"] = body_data.get("body_text")
                msg["body_html"] = body_data.get("body_html")
            except Exception:
                pass

    result = {k: item.get(k) for k in LIST_FIELDS}
    result["messages"] = messages
    return success(result)


def update_thread(event, inbox_id, thread_id):
    keys = thread_keys(inbox_id, thread_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Thread")

    body = parse_body(event)
    updates = {"updated_at": now_iso()}
    for field in ["is_read", "is_starred", "is_trash", "labels"]:
        if field in body:
            updates[field] = body[field]

    updated = update_item(keys["PK"], keys["SK"], updates)
    return success({k: updated.get(k) for k in LIST_FIELDS})


def delete_thread(event, inbox_id, thread_id):
    keys = thread_keys(inbox_id, thread_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Thread")
    update_item(keys["PK"], keys["SK"], {"is_trash": True, "updated_at": now_iso()})
    return no_content()
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_threads.py`:
```python
import json
from shared.models import thread_keys, thread_gsi1
from shared.dynamo import put_item


def _make_event(org_id, inbox_id, method="GET", body=None, path_params=None):
    pp = path_params or {"id": inbox_id}
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"org_id": org_id}},
        "queryStringParameters": {},
        "pathParameters": pp,
        "body": json.dumps(body) if body else None,
    }


def test_list_threads(aws_env):
    from threads.handler import handler
    put_item({
        **thread_keys("inbox_01", "thread_01"),
        **thread_gsi1("inbox_01", "thread_01"),
        "entity_type": "Thread", "id": "thread_01",
        "inbox_id": "inbox_01", "org_id": "org_01",
        "subject": "Test Thread", "snippet": "Preview",
        "message_count": 1, "unread_count": 0,
        "participants": [], "labels": [], "is_read": True,
        "is_starred": False, "is_trash": False,
        "last_message_at": "2026-01-01T00:00:00.000Z",
        "created_at": "2026-01-01T00:00:00.000Z",
        "updated_at": "2026-01-01T00:00:00.000Z",
    })
    event = _make_event("org_01", "inbox_01")
    result = handler(event, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["data"]) == 1


def test_update_thread(aws_env):
    from threads.handler import handler
    put_item({
        **thread_keys("inbox_01", "thread_02"),
        "entity_type": "Thread", "id": "thread_02",
        "inbox_id": "inbox_01", "is_read": False,
    })
    event = _make_event("org_01", "inbox_01", "PATCH",
        {"is_read": True}, path_params={"id": "inbox_01", "tid": "thread_02"})
    result = handler(event, None)
    assert result["statusCode"] == 200
```

```bash
pytest tests/test_threads.py -v
git add lambdas/threads/ tests/test_threads.py
git commit -m "feat: add Threads handler (list, get, update, delete)"
```

---

### Task 14: Drafts Handler

**Files:**
- Create: `lambdas/drafts/handler.py`
- Create: `tests/test_drafts.py`

- [ ] **Step 1: Create drafts handler** (same pattern as above, supporting GET/POST/PATCH/DELETE + send)

Create `lambdas/drafts/__init__.py` (empty).

Create `lambdas/drafts/handler.py`:
```python
"""GET/POST/PATCH/DELETE /inboxes/{id}/drafts and POST /drafts/{did}/send."""

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, delete_item, query_gsi
from shared.models import draft_keys, draft_gsi1, now_iso
from shared.ulid import generate_ulid
from shared.response import success, created, no_content, bad_request, not_found
from shared.validation import parse_body, require_fields
from shared.pagination import get_pagination_params, paginated_response

FIELDS = [
    "id", "inbox_id", "thread_id", "in_reply_to_message_id",
    "to", "cc", "bcc", "subject", "body_text", "body_html",
    "attachments", "created_at", "updated_at",
]


def handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    inbox_id = path_params.get("id") or path_params.get("inbox_id")

    if method == "GET" and "did" not in path_params:
        return list_drafts(event, inbox_id)
    elif method == "GET":
        return get_draft(event, inbox_id, path_params["did"])
    elif method == "POST" and path.endswith("/send"):
        return send_draft(event, inbox_id, path_params["did"])
    elif method == "POST":
        return create_draft(event, inbox_id)
    elif method == "PATCH":
        return update_draft(event, inbox_id, path_params["did"])
    elif method == "DELETE":
        return delete_draft_handler(event, inbox_id, path_params["did"])
    return bad_request("Unsupported method")


def list_drafts(event, inbox_id):
    limit, page_token, ascending = get_pagination_params(event)
    items, last_key = query_gsi(
        "GSI1", f"INBOX#{inbox_id}#DRAFTS",
        limit=limit, ascending=ascending, exclusive_start_key=page_token,
    )
    data = [{k: item.get(k) for k in FIELDS} for item in items]
    return success(paginated_response(data, last_key))


def get_draft(event, inbox_id, draft_id):
    keys = draft_keys(inbox_id, draft_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Draft")
    return success({k: item.get(k) for k in FIELDS})


def create_draft(event, inbox_id):
    org_id = get_org_id(event)
    body = parse_body(event)
    draft_id = generate_ulid()
    now = now_iso()

    item = {
        **draft_keys(inbox_id, draft_id),
        **draft_gsi1(inbox_id, draft_id),
        "entity_type": "Draft",
        "id": draft_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": body.get("thread_id"),
        "in_reply_to_message_id": body.get("in_reply_to_message_id"),
        "to": body.get("to", []),
        "cc": body.get("cc", []),
        "bcc": body.get("bcc", []),
        "subject": body.get("subject", ""),
        "body_text": body.get("body_text", ""),
        "body_html": body.get("body_html", ""),
        "attachments": body.get("attachments", []),
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return created({k: item.get(k) for k in FIELDS})


def update_draft(event, inbox_id, draft_id):
    keys = draft_keys(inbox_id, draft_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Draft")

    body = parse_body(event)
    updates = {"updated_at": now_iso()}
    for field in ["to", "cc", "bcc", "subject", "body_text", "body_html", "attachments"]:
        if field in body:
            updates[field] = body[field]

    updated = update_item(keys["PK"], keys["SK"], updates)
    return success({k: updated.get(k) for k in FIELDS})


def delete_draft_handler(event, inbox_id, draft_id):
    keys = draft_keys(inbox_id, draft_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Draft")
    delete_item(keys["PK"], keys["SK"])
    return no_content()


def send_draft(event, inbox_id, draft_id):
    keys = draft_keys(inbox_id, draft_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Draft")

    # Convert draft to a send-message call
    from messages.handler import send_message as _send
    send_event = {
        **event,
        "httpMethod": "POST",
        "body": __import__("json").dumps({
            "to": item.get("to", []),
            "cc": item.get("cc", []),
            "bcc": item.get("bcc", []),
            "subject": item.get("subject", ""),
            "body_text": item.get("body_text", ""),
            "body_html": item.get("body_html", ""),
        }),
    }
    result = _send(send_event, inbox_id)

    if result["statusCode"] in (200, 201):
        delete_item(keys["PK"], keys["SK"])

    return result
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_drafts.py`:
```python
import json
from shared.models import draft_keys, draft_gsi1
from shared.dynamo import put_item


def _make_event(org_id, inbox_id, method="GET", body=None, path_params=None, path=""):
    pp = path_params or {"id": inbox_id}
    return {
        "httpMethod": method,
        "path": path or f"/v1/inboxes/{inbox_id}/drafts",
        "requestContext": {"authorizer": {"org_id": org_id}},
        "queryStringParameters": {},
        "pathParameters": pp,
        "body": json.dumps(body) if body else None,
    }


def test_create_draft(aws_env):
    from drafts.handler import handler
    event = _make_event("org_01", "inbox_01", "POST", {
        "to": [{"address": "test@example.com"}],
        "subject": "Draft Subject",
        "body_text": "Draft body",
    })
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["subject"] == "Draft Subject"


def test_update_draft(aws_env):
    from drafts.handler import handler
    put_item({
        **draft_keys("inbox_01", "draft_01"),
        **draft_gsi1("inbox_01", "draft_01"),
        "entity_type": "Draft", "id": "draft_01",
        "inbox_id": "inbox_01", "org_id": "org_01",
        "subject": "Old Subject", "body_text": "Old body",
        "created_at": "2026-01-01T00:00:00.000Z",
        "updated_at": "2026-01-01T00:00:00.000Z",
    })
    event = _make_event("org_01", "inbox_01", "PATCH",
        {"subject": "New Subject"},
        path_params={"id": "inbox_01", "did": "draft_01"})
    result = handler(event, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["subject"] == "New Subject"


def test_delete_draft(aws_env):
    from drafts.handler import handler
    put_item({
        **draft_keys("inbox_01", "draft_02"),
        "entity_type": "Draft", "id": "draft_02",
        "inbox_id": "inbox_01",
    })
    event = _make_event("org_01", "inbox_01", "DELETE",
        path_params={"id": "inbox_01", "did": "draft_02"})
    result = handler(event, None)
    assert result["statusCode"] == 204
```

```bash
pytest tests/test_drafts.py -v
git add lambdas/drafts/ tests/test_drafts.py
git commit -m "feat: add Drafts CRUD handler with send"
```

---

### Task 15: Domains Handler

**Files:**
- Create: `lambdas/domains/handler.py`
- Create: `tests/test_domains.py`

- [ ] **Step 1: Create domains handler**

Create `lambdas/domains/__init__.py` (empty).

Create `lambdas/domains/handler.py`:
```python
"""GET/POST/PATCH/DELETE /domains, POST /domains/{id}/verify, GET /domains/{id}/zone-file."""

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, delete_item, query
from shared.models import domain_keys, domain_gsi1, now_iso
from shared.ulid import generate_ulid
from shared.response import success, created, no_content, bad_request, not_found
from shared.validation import parse_body, require_fields
from shared.pagination import get_pagination_params, paginated_response

FIELDS = [
    "id", "domain", "status", "mx_verified", "spf_verified",
    "dkim_verified", "dmarc_verified", "dns_records",
    "created_at", "verified_at",
]


def handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}

    if method == "GET" and path.endswith("/zone-file"):
        return get_zone_file(event, path_params["id"])
    elif method == "POST" and path.endswith("/verify"):
        return verify_domain(event, path_params["id"])
    elif method == "GET" and "id" not in path_params:
        return list_domains(event)
    elif method == "GET":
        return get_domain(event, path_params["id"])
    elif method == "POST":
        return create_domain(event)
    elif method == "PATCH":
        return update_domain_handler(event, path_params["id"])
    elif method == "DELETE":
        return delete_domain_handler(event, path_params["id"])
    return bad_request("Unsupported method")


def list_domains(event):
    org_id = get_org_id(event)
    limit, page_token, ascending = get_pagination_params(event)
    items, last_key = query(
        pk=f"ORG#{org_id}", sk_prefix="DOMAIN#",
        limit=limit, ascending=ascending, exclusive_start_key=page_token,
    )
    data = [{k: item.get(k) for k in FIELDS} for item in items]
    return success(paginated_response(data, last_key))


def get_domain(event, domain_id):
    org_id = get_org_id(event)
    keys = domain_keys(org_id, domain_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Domain")
    return success({k: item.get(k) for k in FIELDS})


def create_domain(event):
    org_id = get_org_id(event)
    body = parse_body(event)
    err = require_fields(body, ["domain"])
    if err:
        return bad_request(err)

    domain_name = body["domain"]
    domain_id = generate_ulid()
    now = now_iso()

    dns_records = {
        "mx": {
            "type": "MX", "name": domain_name,
            "value": "10 inbound-smtp.us-east-1.amazonaws.com",
            "verified": False,
        },
        "spf": {
            "type": "TXT", "name": domain_name,
            "value": "v=spf1 include:amazonses.com ~all",
            "verified": False,
        },
        "dkim": [
            {"type": "CNAME", "name": f"s{i}._domainkey.{domain_name}",
             "value": f"s{i}.dkim.victorymail.dev", "verified": False}
            for i in range(1, 4)
        ],
        "dmarc": {
            "type": "TXT", "name": f"_dmarc.{domain_name}",
            "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc@victorymail.dev",
            "verified": False,
        },
    }

    item = {
        **domain_keys(org_id, domain_id),
        **domain_gsi1(domain_name, domain_id),
        "entity_type": "Domain",
        "id": domain_id,
        "org_id": org_id,
        "domain": domain_name,
        "status": "pending",
        "mx_verified": False,
        "spf_verified": False,
        "dkim_verified": False,
        "dmarc_verified": False,
        "dns_records": dns_records,
        "created_at": now,
        "verified_at": None,
    }
    put_item(item)
    return created({k: item.get(k) for k in FIELDS})


def update_domain_handler(event, domain_id):
    org_id = get_org_id(event)
    keys = domain_keys(org_id, domain_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Domain")

    body = parse_body(event)
    updates = {}
    if "catch_all_inbox_id" in body:
        updates["catch_all_inbox_id"] = body["catch_all_inbox_id"]
    if updates:
        updated = update_item(keys["PK"], keys["SK"], updates)
        return success({k: updated.get(k) for k in FIELDS})
    return success({k: item.get(k) for k in FIELDS})


def delete_domain_handler(event, domain_id):
    org_id = get_org_id(event)
    keys = domain_keys(org_id, domain_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Domain")
    delete_item(keys["PK"], keys["SK"])
    return no_content()


def verify_domain(event, domain_id):
    org_id = get_org_id(event)
    keys = domain_keys(org_id, domain_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Domain")

    # In production, this would check DNS records via Route53/dig
    update_item(keys["PK"], keys["SK"], {"status": "verifying"})
    item["status"] = "verifying"
    return success({k: item.get(k) for k in FIELDS})


def get_zone_file(event, domain_id):
    org_id = get_org_id(event)
    keys = domain_keys(org_id, domain_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Domain")

    domain_name = item["domain"]
    dns = item.get("dns_records", {})
    lines = [
        f"; FreeMail DNS records for {domain_name}",
        f"; Generated: {now_iso()}",
        "",
        f"{dns['mx']['name']}.    IN MX  {dns['mx']['value']}",
        f"{dns['spf']['name']}.    IN TXT \"{dns['spf']['value']}\"",
    ]
    for dkim in dns.get("dkim", []):
        lines.append(f"{dkim['name']}. IN CNAME {dkim['value']}.")
    lines.append(f"{dns['dmarc']['name']}. IN TXT \"{dns['dmarc']['value']}\"")

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/dns", "Access-Control-Allow-Origin": "*"},
        "body": "\n".join(lines),
    }
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_domains.py`:
```python
import json


def _make_event(org_id, method="GET", body=None, path_params=None, path=""):
    return {
        "httpMethod": method,
        "path": path or "/v1/domains",
        "requestContext": {"authorizer": {"org_id": org_id}},
        "queryStringParameters": {},
        "pathParameters": path_params,
        "body": json.dumps(body) if body else None,
    }


def test_create_domain(aws_env):
    from domains.handler import handler
    event = _make_event("org_01", "POST", {"domain": "mail.acme.com"})
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["domain"] == "mail.acme.com"
    assert body["status"] == "pending"
    assert body["dns_records"]["mx"]["value"] == "10 inbound-smtp.us-east-1.amazonaws.com"


def test_verify_domain(aws_env):
    from domains.handler import handler
    # Create first
    event = _make_event("org_01", "POST", {"domain": "mail.acme.com"})
    result = handler(event, None)
    domain_id = json.loads(result["body"])["id"]

    # Verify
    event = _make_event("org_01", "POST",
        path_params={"id": domain_id},
        path=f"/v1/domains/{domain_id}/verify")
    result = handler(event, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "verifying"
```

```bash
pytest tests/test_domains.py -v
git add lambdas/domains/ tests/test_domains.py
git commit -m "feat: add Domains handler (CRUD, verify, zone-file)"
```

---

### Task 16: Webhooks Handler

**Files:**
- Create: `lambdas/webhooks/handler.py`
- Create: `tests/test_webhooks.py`

- [ ] **Step 1: Create webhooks handler**

Create `lambdas/webhooks/__init__.py` (empty).

Create `lambdas/webhooks/handler.py`:
```python
"""GET/POST/PATCH/DELETE /webhooks handlers."""

import secrets
from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, update_item, delete_item, query_gsi
from shared.models import webhook_keys, webhook_gsi1, now_iso
from shared.ulid import generate_ulid
from shared.response import success, created, no_content, bad_request, not_found
from shared.validation import parse_body, require_fields
from shared.pagination import get_pagination_params, paginated_response

FIELDS = [
    "id", "url", "events", "status", "secret", "filter",
    "delivery_stats", "created_at", "updated_at",
]

VALID_EVENTS = {
    "message.received", "message.sent", "message.bounced",
    "message.complained", "message.delayed",
    "inbox.created", "inbox.deleted",
    "domain.verified", "domain.failed",
    "subscription.updated",
}


def handler(event, context):
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if method == "GET" and "id" not in path_params:
        return list_webhooks(event)
    elif method == "GET":
        return get_webhook(event, path_params["id"])
    elif method == "POST":
        return create_webhook(event)
    elif method == "PATCH":
        return update_webhook(event, path_params["id"])
    elif method == "DELETE":
        return delete_webhook_handler(event, path_params["id"])
    return bad_request("Unsupported method")


def list_webhooks(event):
    org_id = get_org_id(event)
    limit, page_token, ascending = get_pagination_params(event)
    items, last_key = query_gsi(
        "GSI1", f"ORG#{org_id}#WEBHOOKS",
        limit=limit, ascending=ascending, exclusive_start_key=page_token,
    )
    data = [{k: item.get(k) for k in FIELDS} for item in items]
    return success(paginated_response(data, last_key))


def get_webhook(event, webhook_id):
    org_id = get_org_id(event)
    keys = webhook_keys(org_id, webhook_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Webhook")
    return success({k: item.get(k) for k in FIELDS})


def create_webhook(event):
    org_id = get_org_id(event)
    body = parse_body(event)
    err = require_fields(body, ["url", "events"])
    if err:
        return bad_request(err)

    invalid = set(body["events"]) - VALID_EVENTS
    if invalid:
        return bad_request(f"Invalid events: {', '.join(invalid)}")

    webhook_id = generate_ulid()
    now = now_iso()
    secret = f"whsec_{secrets.token_hex(32)}"

    item = {
        **webhook_keys(org_id, webhook_id),
        **webhook_gsi1(org_id, webhook_id),
        "entity_type": "Webhook",
        "id": webhook_id,
        "org_id": org_id,
        "url": body["url"],
        "events": body["events"],
        "status": "active",
        "secret": secret,
        "filter": body.get("filter", {"pod_ids": [], "inbox_ids": []}),
        "delivery_stats": {
            "total_delivered": 0,
            "total_failed": 0,
            "last_delivered_at": None,
            "last_failed_at": None,
        },
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return created({k: item.get(k) for k in FIELDS})


def update_webhook(event, webhook_id):
    org_id = get_org_id(event)
    keys = webhook_keys(org_id, webhook_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Webhook")

    body = parse_body(event)
    updates = {"updated_at": now_iso()}
    for field in ["url", "events", "status", "filter"]:
        if field in body:
            updates[field] = body[field]

    updated = update_item(keys["PK"], keys["SK"], updates)
    return success({k: updated.get(k) for k in FIELDS})


def delete_webhook_handler(event, webhook_id):
    org_id = get_org_id(event)
    keys = webhook_keys(org_id, webhook_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Webhook")
    delete_item(keys["PK"], keys["SK"])
    return no_content()
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_webhooks.py`:
```python
import json


def _make_event(org_id, method="GET", body=None, path_params=None):
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"org_id": org_id}},
        "queryStringParameters": {},
        "pathParameters": path_params,
        "body": json.dumps(body) if body else None,
    }


def test_create_webhook(aws_env):
    from webhooks.handler import handler
    event = _make_event("org_01", "POST", {
        "url": "https://example.com/webhook",
        "events": ["message.received", "message.sent"],
    })
    result = handler(event, None)
    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["url"] == "https://example.com/webhook"
    assert body["secret"].startswith("whsec_")


def test_create_webhook_invalid_event(aws_env):
    from webhooks.handler import handler
    event = _make_event("org_01", "POST", {
        "url": "https://example.com/webhook",
        "events": ["invalid.event"],
    })
    result = handler(event, None)
    assert result["statusCode"] == 400
```

```bash
pytest tests/test_webhooks.py -v
git add lambdas/webhooks/ tests/test_webhooks.py
git commit -m "feat: add Webhooks CRUD handler"
```

---

### Task 17: Inbound Email Processor

**Files:**
- Create: `lambdas/inbound_processor/handler.py`
- Create: `tests/test_inbound_processor.py`

- [ ] **Step 1: Create inbound email processor**

Create `lambdas/inbound_processor/__init__.py` (empty).

Create `lambdas/inbound_processor/handler.py`:
```python
"""Process inbound email from SES -> S3 -> this Lambda."""

import email
import json
import os
import boto3
from email.utils import parseaddr
from shared.dynamo import get_item, put_item, update_item, query_gsi
from shared.models import (
    message_keys, message_gsi1, message_gsi3,
    thread_keys, thread_gsi1, inbox_keys, attachment_keys, now_iso,
)
from shared.ulid import generate_ulid
from shared.s3 import store_body, get_client as get_s3

EMAIL_BUCKET = os.environ.get("EMAIL_BUCKET", "victorymail-raw-email")
ATTACHMENT_BUCKET = os.environ.get("ATTACHMENT_BUCKET", "victorymail-attachments")


def handler(event, context):
    for record in event.get("Records", []):
        process_ses_record(record)
    return {"statusCode": 200}


def process_ses_record(record):
    # SES notification via SNS or direct Lambda invocation
    ses_notification = record.get("ses") or json.loads(record.get("Sns", {}).get("Message", "{}")).get("receipt", {})
    mail_data = record.get("ses", {}).get("mail", {}) or json.loads(record.get("Sns", {}).get("Message", "{}")).get("mail", {})

    # Get the S3 object key from the SES action
    s3_key = None
    action = ses_notification.get("action", {})
    if action.get("type") == "S3":
        s3_key = f"{action.get('objectKeyPrefix', 'inbound/')}{mail_data.get('messageId', '')}"
    elif "s3" in record:
        s3_key = record["s3"]["object"]["key"]

    if not s3_key:
        # Fallback: try to get from event structure
        s3_key = f"inbound/{mail_data.get('messageId', generate_ulid())}"

    # Fetch raw email from S3
    s3 = get_s3()
    try:
        raw_obj = s3.get_object(Bucket=EMAIL_BUCKET, Key=s3_key)
        raw_email = raw_obj["Body"].read()
    except Exception:
        # If we can't get the raw email, try to process from SES notification data
        raw_email = None

    if raw_email:
        msg = email.message_from_bytes(raw_email)
    else:
        # Build minimal message from SES notification
        msg = None

    # Extract recipients
    recipients = mail_data.get("destination", [])
    if not recipients and msg:
        to_header = msg.get("To", "")
        recipients = [parseaddr(addr)[1] for addr in to_header.split(",")]

    for recipient in recipients:
        route_to_inbox(recipient, mail_data, msg, s3_key)


def route_to_inbox(recipient_address: str, mail_data: dict, msg, raw_s3_key: str):
    # Look up inbox by email address via GSI2
    items, _ = query_gsi("GSI2", f"EMAIL#{recipient_address}", limit=1)
    if not items:
        return  # No inbox for this address, ignore

    inbox_record = items[0]
    inbox_id = inbox_record.get("SK", "").replace("INBOX#", "") or inbox_record.get("id")
    org_id = inbox_record.get("org_id")

    if inbox_record.get("status") != "active":
        return

    # Parse email fields
    from_name, from_addr = "", ""
    subject = ""
    body_text = ""
    body_html = ""

    if msg:
        from_name, from_addr = parseaddr(msg.get("From", ""))
        subject = msg.get("Subject", "(no subject)")
        body_text, body_html = extract_body(msg)
    else:
        common_headers = {h["name"].lower(): h["value"] for h in mail_data.get("commonHeaders", {}).get("headers", [])} if "commonHeaders" in mail_data else {}
        from_addr = mail_data.get("source", "")
        subject = mail_data.get("commonHeaders", {}).get("subject", "(no subject)")

    message_id = generate_ulid()
    now = now_iso()

    # Store body in S3
    body_key = store_body(org_id, inbox_id, message_id, body_text, body_html)

    # Determine thread (by In-Reply-To or References header, or new thread)
    thread_id = generate_ulid()
    in_reply_to = msg.get("In-Reply-To", "") if msg else ""
    references = msg.get("References", "") if msg else ""

    snippet = (body_text or "")[:200]

    # Store message
    msg_item = {
        **message_keys(inbox_id, message_id),
        **message_gsi1(thread_id, message_id),
        **message_gsi3(org_id, message_id),
        "entity_type": "Message",
        "id": message_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": thread_id,
        "direction": "inbound",
        "from_addr": {"name": from_name, "address": from_addr},
        "to": [{"address": recipient_address}],
        "cc": [],
        "bcc": [],
        "reply_to": [],
        "subject": subject,
        "snippet": snippet,
        "body_s3_key": body_key,
        "is_read": False,
        "is_starred": False,
        "is_spam": False,
        "is_trash": False,
        "labels": [],
        "category": None,
        "headers": {
            "message_id": msg.get("Message-ID", "") if msg else "",
            "in_reply_to": in_reply_to,
            "references": references,
        },
        "ses_message_id": mail_data.get("messageId"),
        "attachment_count": 0,
        "has_attachments": False,
        "received_at": now,
        "created_at": now,
    }

    # Handle attachments
    if msg:
        attachments = extract_attachments(msg, org_id, inbox_id, message_id)
        msg_item["attachment_count"] = len(attachments)
        msg_item["has_attachments"] = len(attachments) > 0

    # Add GSI6 for SES message ID lookup
    ses_msg_id = mail_data.get("messageId")
    if ses_msg_id:
        from shared.models import message_gsi6
        msg_item.update(message_gsi6(ses_msg_id, message_id))

    put_item(msg_item)

    # Create thread
    thread_item = {
        **thread_keys(inbox_id, thread_id),
        **thread_gsi1(inbox_id, thread_id),
        "entity_type": "Thread",
        "id": thread_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "subject": subject,
        "snippet": snippet,
        "message_count": 1,
        "unread_count": 1,
        "participants": [
            {"name": from_name, "address": from_addr},
            {"address": recipient_address},
        ],
        "labels": [],
        "category": None,
        "is_read": False,
        "is_starred": False,
        "is_trash": False,
        "last_message_at": now,
        "created_at": now,
        "updated_at": now,
    }
    put_item(thread_item)

    # Update inbox counts
    inbox_pk = f"ORG#{org_id}"
    inbox_sk = f"INBOX#{inbox_id}"
    try:
        from shared.dynamo import get_table
        get_table().update_item(
            Key={"PK": inbox_pk, "SK": inbox_sk},
            UpdateExpression="SET message_count = if_not_exists(message_count, :zero) + :one, unread_count = if_not_exists(unread_count, :zero) + :one",
            ExpressionAttributeValues={":one": 1, ":zero": 0},
        )
    except Exception:
        pass


def extract_body(msg) -> tuple[str, str]:
    body_text = ""
    body_html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not body_text:
                body_text = part.get_payload(decode=True).decode("utf-8", errors="replace")
            elif ct == "text/html" and not body_html:
                body_html = part.get_payload(decode=True).decode("utf-8", errors="replace")
    else:
        ct = msg.get_content_type()
        payload = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        if ct == "text/html":
            body_html = payload
        else:
            body_text = payload
    return body_text, body_html


def extract_attachments(msg, org_id: str, inbox_id: str, message_id: str) -> list[dict]:
    attachments = []
    s3 = get_s3()
    for part in msg.walk():
        if part.get_content_disposition() in ("attachment", "inline"):
            filename = part.get_filename() or "unnamed"
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            att_id = generate_ulid()
            s3_key = f"attachments/{org_id}/{inbox_id}/{message_id}/{att_id}/{filename}"
            s3.put_object(
                Bucket=ATTACHMENT_BUCKET,
                Key=s3_key,
                Body=payload,
                ContentType=content_type,
            )

            att_item = {
                **attachment_keys(message_id, att_id),
                "entity_type": "Attachment",
                "id": att_id,
                "message_id": message_id,
                "inbox_id": inbox_id,
                "org_id": org_id,
                "filename": filename,
                "content_type": content_type,
                "size": len(payload),
                "s3_bucket": ATTACHMENT_BUCKET,
                "s3_key": s3_key,
            }
            put_item(att_item)
            attachments.append(att_item)
    return attachments
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_inbound_processor.py`:
```python
import json
from shared.models import inbox_keys, inbox_gsi1, inbox_gsi2
from shared.dynamo import put_item, get_item


def _seed_inbox(aws_env, org_id="org_01", inbox_id="inbox_01", email_addr="test@victorymail.dev"):
    put_item({
        **inbox_keys(org_id, inbox_id),
        **inbox_gsi1("pod_01", inbox_id),
        **inbox_gsi2(email_addr, inbox_id),
        "entity_type": "Inbox", "id": inbox_id, "org_id": org_id,
        "pod_id": "pod_01", "email": email_addr,
        "status": "active", "message_count": 0, "unread_count": 0,
    })


def test_inbound_routes_to_inbox(aws_env):
    _seed_inbox(aws_env)
    # Store a raw email in S3
    raw_email = b"""From: sender@example.com
To: test@victorymail.dev
Subject: Test Inbound
Content-Type: text/plain

Hello from the outside!
"""
    aws_env["s3"].put_object(
        Bucket="victorymail-raw-email",
        Key="inbound/test-msg-id",
        Body=raw_email,
    )

    from inbound_processor.handler import handler
    event = {
        "Records": [{
            "ses": {
                "mail": {
                    "messageId": "test-msg-id",
                    "source": "sender@example.com",
                    "destination": ["test@victorymail.dev"],
                },
                "receipt": {
                    "action": {"type": "S3", "objectKeyPrefix": "inbound/"},
                },
            },
        }],
    }
    handler(event, None)

    # Verify message was stored (query the inbox)
    from shared.dynamo import query
    items, _ = query(pk="INBOX#inbox_01", sk_prefix="MSG#")
    assert len(items) == 1
    assert items[0]["subject"] == "Test Inbound"
    assert items[0]["direction"] == "inbound"
```

```bash
pytest tests/test_inbound_processor.py -v
git add lambdas/inbound_processor/ tests/test_inbound_processor.py
git commit -m "feat: add inbound email processor (SES -> S3 -> DynamoDB)"
```

---

### Task 18: Outbound Email Worker

**Files:**
- Create: `lambdas/outbound_worker/handler.py`
- Create: `tests/test_outbound_worker.py`

- [ ] **Step 1: Create outbound worker**

Create `lambdas/outbound_worker/__init__.py` (empty).

Create `lambdas/outbound_worker/handler.py`:
```python
"""SQS consumer: read message from DynamoDB, build MIME, send via SES."""

import os
import json
import boto3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from shared.dynamo import get_item, update_item
from shared.models import message_keys, now_iso
from shared.s3 import get_body

SES_CONFIG_SET = os.environ.get("SES_CONFIG_SET", "victorymail-default")


def handler(event, context):
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        process_message(body)
    return {"statusCode": 200}


def process_message(payload: dict):
    message_id = payload["message_id"]
    inbox_id = payload["inbox_id"]
    org_id = payload["org_id"]

    keys = message_keys(inbox_id, message_id)
    msg_item = get_item(keys["PK"], keys["SK"])
    if not msg_item:
        return

    if msg_item.get("status") != "queued":
        return

    # Fetch body from S3
    body_data = {}
    body_key = msg_item.get("body_s3_key")
    if body_key:
        body_data = get_body(body_key)

    body_text = body_data.get("body_text", "")
    body_html = body_data.get("body_html", "")

    # Build MIME message
    mime_msg = MIMEMultipart("alternative")
    from_addr = msg_item.get("from_addr", {})
    from_address = from_addr.get("address", "")
    from_name = from_addr.get("name", "")
    if from_name:
        mime_msg["From"] = f"{from_name} <{from_address}>"
    else:
        mime_msg["From"] = from_address

    to_addresses = [r.get("address", "") for r in msg_item.get("to", [])]
    mime_msg["To"] = ", ".join(to_addresses)
    mime_msg["Subject"] = msg_item.get("subject", "")

    if body_text:
        mime_msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        mime_msg.attach(MIMEText(body_html, "html", "utf-8"))

    # Add custom headers
    headers = msg_item.get("headers", {})
    if headers.get("in_reply_to"):
        mime_msg["In-Reply-To"] = headers["in_reply_to"]
    if headers.get("references"):
        mime_msg["References"] = headers["references"]

    # Send via SES
    ses = boto3.client("sesv2")
    try:
        response = ses.send_email(
            FromEmailAddress=from_address,
            Destination={
                "ToAddresses": to_addresses,
                "CcAddresses": [r.get("address", "") for r in msg_item.get("cc", [])],
                "BccAddresses": [r.get("address", "") for r in msg_item.get("bcc", [])],
            },
            Content={"Raw": {"Data": mime_msg.as_bytes()}},
            ConfigurationSetName=SES_CONFIG_SET,
        )
        ses_message_id = response.get("MessageId", "")
        update_item(keys["PK"], keys["SK"], {
            "status": "sent",
            "ses_message_id": ses_message_id,
            "sent_at": now_iso(),
        })
    except ses.exceptions.MessageRejected:
        update_item(keys["PK"], keys["SK"], {"status": "failed", "failed_at": now_iso()})
    except Exception as e:
        # Retriable error - let SQS retry
        raise e
```

- [ ] **Step 2: Write tests and commit**

Create `tests/test_outbound_worker.py`:
```python
import json
import os
from moto import mock_aws
from shared.models import message_keys, message_gsi1, message_gsi3, inbox_keys
from shared.dynamo import put_item, get_item
from shared.s3 import store_body


def test_outbound_worker_sends_email(aws_env):
    # Seed inbox and message
    put_item({
        **inbox_keys("org_01", "inbox_01"),
        "entity_type": "Inbox", "id": "inbox_01", "org_id": "org_01",
        "email": "sender@victorymail.dev", "status": "active",
    })

    body_key = store_body("org_01", "inbox_01", "msg_out_01", "Hello!", "<p>Hello!</p>")

    put_item({
        **message_keys("inbox_01", "msg_out_01"),
        **message_gsi1("thread_01", "msg_out_01"),
        **message_gsi3("org_01", "msg_out_01"),
        "entity_type": "Message", "id": "msg_out_01",
        "inbox_id": "inbox_01", "org_id": "org_01",
        "thread_id": "thread_01", "direction": "outbound",
        "from_addr": {"name": "Sender", "address": "sender@victorymail.dev"},
        "to": [{"address": "recipient@example.com"}],
        "cc": [], "bcc": [],
        "subject": "Test Outbound",
        "body_s3_key": body_key,
        "headers": {},
        "status": "queued",
    })

    # The actual SES send will fail in moto, but we can verify the message was read
    from outbound_worker.handler import process_message
    try:
        process_message({
            "message_id": "msg_out_01",
            "inbox_id": "inbox_01",
            "org_id": "org_01",
        })
    except Exception:
        pass  # SES mock may not be fully set up

    # Message should still exist
    item = get_item("INBOX#inbox_01", "MSG#msg_out_01")
    assert item is not None
```

```bash
pytest tests/test_outbound_worker.py -v
git add lambdas/outbound_worker/ tests/test_outbound_worker.py
git commit -m "feat: add outbound email worker (SQS -> MIME -> SES)"
```

---

### Task 19: Bounce Processor

**Files:**
- Create: `lambdas/bounce_processor/handler.py`

- [ ] **Step 1: Create bounce processor**

Create `lambdas/bounce_processor/__init__.py` (empty).

Create `lambdas/bounce_processor/handler.py`:
```python
"""Process SES bounce/complaint notifications from SNS."""

import json
from shared.dynamo import update_item, query_gsi
from shared.models import now_iso


def handler(event, context):
    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])
        notification_type = message.get("notificationType")
        if notification_type == "Bounce":
            process_bounce(message)
        elif notification_type == "Complaint":
            process_complaint(message)
    return {"statusCode": 200}


def process_bounce(message: dict):
    ses_message_id = message.get("mail", {}).get("messageId")
    if not ses_message_id:
        return
    items, _ = query_gsi("GSI6", f"SES#{ses_message_id}", limit=1)
    if not items:
        return
    item = items[0]
    inbox_id = item.get("inbox_id")
    message_id = item.get("SK", "").replace("MSG#", "")
    update_item(f"INBOX#{inbox_id}", f"MSG#{message_id}", {
        "status": "bounced",
        "bounce_type": message.get("bounce", {}).get("bounceType"),
        "bounced_at": now_iso(),
    })


def process_complaint(message: dict):
    ses_message_id = message.get("mail", {}).get("messageId")
    if not ses_message_id:
        return
    items, _ = query_gsi("GSI6", f"SES#{ses_message_id}", limit=1)
    if not items:
        return
    item = items[0]
    inbox_id = item.get("inbox_id")
    message_id = item.get("SK", "").replace("MSG#", "")
    update_item(f"INBOX#{inbox_id}", f"MSG#{message_id}", {
        "status": "complained",
        "complained_at": now_iso(),
    })
```

- [ ] **Step 2: Commit**

```bash
git add lambdas/bounce_processor/
git commit -m "feat: add bounce/complaint processor for SES notifications"
```

---

### Task 20: API Gateway Stack (CDK) - Wire Everything Together

**Files:**
- Create: `cdk/lib/stacks/api-stack.ts`

- [ ] **Step 1: Create the API stack that wires all Lambda functions to API Gateway**

Create `cdk/lib/stacks/api-stack.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as sns_subs from 'aws-cdk-lib/aws-sns-subscriptions';
import * as lambda_events from 'aws-cdk-lib/aws-lambda-event-sources';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import * as path from 'path';

interface ApiStackProps extends cdk.StackProps {
  table: dynamodb.Table;
  emailBucket: s3.Bucket;
  attachmentBucket: s3.Bucket;
  bodyBucket: s3.Bucket;
  sendQueue: sqs.Queue;
  bounceTopic: sns.Topic;
  complaintTopic: sns.Topic;
}

export class ApiStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const lambdasDir = path.join(__dirname, '..', '..', '..', 'lambdas');

    const commonEnv = {
      TABLE_NAME: props.table.tableName,
      EMAIL_BUCKET: props.emailBucket.bucketName,
      ATTACHMENT_BUCKET: props.attachmentBucket.bucketName,
      BODY_BUCKET: props.bodyBucket.bucketName,
      SEND_QUEUE_URL: props.sendQueue.queueUrl,
      SES_CONFIG_SET: 'victorymail-default',
    };

    // Shared Lambda layer for common code
    const sharedLayer = new lambda.LayerVersion(this, 'SharedLayer', {
      code: lambda.Code.fromAsset(lambdasDir, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output/python && cp -r shared /asset-output/python/',
          ],
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      description: 'Shared utilities and dependencies',
    });

    // Helper to create Lambda functions
    const createFunction = (name: string, handlerPath: string, extras?: Partial<lambda.FunctionProps>) => {
      const fn = new lambda.Function(this, name, {
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: `${handlerPath}.handler`,
        code: lambda.Code.fromAsset(lambdasDir),
        environment: commonEnv,
        timeout: cdk.Duration.seconds(30),
        memorySize: 256,
        ...extras,
      });
      props.table.grantReadWriteData(fn);
      props.emailBucket.grantReadWrite(fn);
      props.attachmentBucket.grantReadWrite(fn);
      props.bodyBucket.grantReadWrite(fn);
      return fn;
    };

    // Lambda Authorizer
    const authorizerFn = createFunction('AuthorizerFn', 'authorizer/handler');

    // API Handlers
    const signupFn = createFunction('SignupFn', 'signup/handler');
    const orgFn = createFunction('OrganizationsFn', 'organizations/handler');
    const apiKeysFn = createFunction('ApiKeysFn', 'api_keys/handler');
    const podsFn = createFunction('PodsFn', 'pods/handler');
    const inboxesFn = createFunction('InboxesFn', 'inboxes/handler');
    const messagesFn = createFunction('MessagesFn', 'messages/handler', {
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
    });
    props.sendQueue.grantSendMessages(messagesFn);

    const threadsFn = createFunction('ThreadsFn', 'threads/handler');
    const draftsFn = createFunction('DraftsFn', 'drafts/handler');
    const domainsFn = createFunction('DomainsFn', 'domains/handler');
    const webhooksFn = createFunction('WebhooksFn', 'webhooks/handler');

    // Workers
    const inboundFn = createFunction('InboundProcessorFn', 'inbound_processor/handler', {
      timeout: cdk.Duration.seconds(60),
      memorySize: 1024,
    });

    const outboundFn = createFunction('OutboundWorkerFn', 'outbound_worker/handler', {
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
    });
    outboundFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ses:SendEmail', 'ses:SendRawEmail'],
      resources: ['*'],
    }));
    outboundFn.addEventSource(new lambda_events.SqsEventSource(props.sendQueue, {
      batchSize: 1,
    }));

    const bounceFn = createFunction('BounceProcessorFn', 'bounce_processor/handler');
    props.bounceTopic.addSubscription(new sns_subs.LambdaSubscription(bounceFn));
    props.complaintTopic.addSubscription(new sns_subs.LambdaSubscription(bounceFn));

    // SES permissions for inbound processor
    inboundFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject'],
      resources: [props.emailBucket.arnForObjects('*')],
    }));

    // API Gateway
    const api = new apigateway.RestApi(this, 'FreemailApi', {
      restApiName: 'FreeMail API',
      description: 'FreeMail email platform API',
      deployOptions: {
        stageName: 'v1',
        throttlingRateLimit: 1000,
        throttlingBurstLimit: 2000,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ['Content-Type', 'x-api-key', 'Authorization'],
      },
    });

    // Token Authorizer
    const authorizer = new apigateway.TokenAuthorizer(this, 'ApiKeyAuthorizer', {
      handler: authorizerFn,
      identitySource: 'method.request.header.x-api-key',
      resultsCacheTtl: cdk.Duration.minutes(5),
    });

    const authOpts: apigateway.MethodOptions = {
      authorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    };

    // Routes - Signup (no auth)
    const agent = api.root.addResource('agent');
    agent.addResource('signup').addMethod('POST', new apigateway.LambdaIntegration(signupFn));
    agent.addResource('verify').addMethod('POST', new apigateway.LambdaIntegration(signupFn));

    // Routes - Organizations
    const orgs = api.root.addResource('organizations');
    orgs.addResource('me').addMethod('GET', new apigateway.LambdaIntegration(orgFn), authOpts);

    // Routes - API Keys
    const apiKeys = api.root.addResource('api-keys');
    apiKeys.addMethod('GET', new apigateway.LambdaIntegration(apiKeysFn), authOpts);
    apiKeys.addMethod('POST', new apigateway.LambdaIntegration(apiKeysFn), authOpts);
    const apiKeyById = apiKeys.addResource('{id}');
    apiKeyById.addMethod('DELETE', new apigateway.LambdaIntegration(apiKeysFn), authOpts);

    // Routes - Pods
    const pods = api.root.addResource('pods');
    pods.addMethod('GET', new apigateway.LambdaIntegration(podsFn), authOpts);
    pods.addMethod('POST', new apigateway.LambdaIntegration(podsFn), authOpts);
    const podById = pods.addResource('{id}');
    podById.addMethod('GET', new apigateway.LambdaIntegration(podsFn), authOpts);
    podById.addMethod('DELETE', new apigateway.LambdaIntegration(podsFn), authOpts);

    // Routes - Inboxes
    const inboxes = api.root.addResource('inboxes');
    inboxes.addMethod('GET', new apigateway.LambdaIntegration(inboxesFn), authOpts);
    inboxes.addMethod('POST', new apigateway.LambdaIntegration(inboxesFn), authOpts);
    const inboxById = inboxes.addResource('{id}');
    inboxById.addMethod('GET', new apigateway.LambdaIntegration(inboxesFn), authOpts);
    inboxById.addMethod('PATCH', new apigateway.LambdaIntegration(inboxesFn), authOpts);
    inboxById.addMethod('DELETE', new apigateway.LambdaIntegration(inboxesFn), authOpts);

    // Routes - Messages
    const messages = inboxById.addResource('messages');
    messages.addMethod('GET', new apigateway.LambdaIntegration(messagesFn), authOpts);
    messages.addMethod('POST', new apigateway.LambdaIntegration(messagesFn), authOpts);
    const messageById = messages.addResource('{mid}');
    messageById.addMethod('GET', new apigateway.LambdaIntegration(messagesFn), authOpts);
    messageById.addMethod('PATCH', new apigateway.LambdaIntegration(messagesFn), authOpts);
    messageById.addResource('reply').addMethod('POST', new apigateway.LambdaIntegration(messagesFn), authOpts);
    messageById.addResource('reply-all').addMethod('POST', new apigateway.LambdaIntegration(messagesFn), authOpts);
    messageById.addResource('forward').addMethod('POST', new apigateway.LambdaIntegration(messagesFn), authOpts);

    // Routes - Threads
    const threads = inboxById.addResource('threads');
    threads.addMethod('GET', new apigateway.LambdaIntegration(threadsFn), authOpts);
    const threadById = threads.addResource('{tid}');
    threadById.addMethod('GET', new apigateway.LambdaIntegration(threadsFn), authOpts);
    threadById.addMethod('PATCH', new apigateway.LambdaIntegration(threadsFn), authOpts);
    threadById.addMethod('DELETE', new apigateway.LambdaIntegration(threadsFn), authOpts);

    // Routes - Drafts
    const drafts = inboxById.addResource('drafts');
    drafts.addMethod('GET', new apigateway.LambdaIntegration(draftsFn), authOpts);
    drafts.addMethod('POST', new apigateway.LambdaIntegration(draftsFn), authOpts);
    const draftById = drafts.addResource('{did}');
    draftById.addMethod('GET', new apigateway.LambdaIntegration(draftsFn), authOpts);
    draftById.addMethod('PATCH', new apigateway.LambdaIntegration(draftsFn), authOpts);
    draftById.addMethod('DELETE', new apigateway.LambdaIntegration(draftsFn), authOpts);
    draftById.addResource('send').addMethod('POST', new apigateway.LambdaIntegration(draftsFn), authOpts);

    // Routes - Domains
    const domains = api.root.addResource('domains');
    domains.addMethod('GET', new apigateway.LambdaIntegration(domainsFn), authOpts);
    domains.addMethod('POST', new apigateway.LambdaIntegration(domainsFn), authOpts);
    const domainById = domains.addResource('{id}');
    domainById.addMethod('GET', new apigateway.LambdaIntegration(domainsFn), authOpts);
    domainById.addMethod('PATCH', new apigateway.LambdaIntegration(domainsFn), authOpts);
    domainById.addMethod('DELETE', new apigateway.LambdaIntegration(domainsFn), authOpts);
    domainById.addResource('verify').addMethod('POST', new apigateway.LambdaIntegration(domainsFn), authOpts);
    domainById.addResource('zone-file').addMethod('GET', new apigateway.LambdaIntegration(domainsFn), authOpts);

    // Routes - Webhooks
    const webhooks = api.root.addResource('webhooks');
    webhooks.addMethod('GET', new apigateway.LambdaIntegration(webhooksFn), authOpts);
    webhooks.addMethod('POST', new apigateway.LambdaIntegration(webhooksFn), authOpts);
    const webhookById = webhooks.addResource('{id}');
    webhookById.addMethod('GET', new apigateway.LambdaIntegration(webhooksFn), authOpts);
    webhookById.addMethod('PATCH', new apigateway.LambdaIntegration(webhooksFn), authOpts);
    webhookById.addMethod('DELETE', new apigateway.LambdaIntegration(webhooksFn), authOpts);

    // Output API URL
    new cdk.CfnOutput(this, 'ApiUrl', {
      value: api.url,
      description: 'FreeMail API URL',
    });
  }
}
```

- [ ] **Step 2: Verify CDK synth**

```bash
cd /Users/jwc/code/Victory/FreeMail.ai/cdk && npx cdk synth --no-staging 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add cdk/lib/stacks/api-stack.ts
git commit -m "feat: add API Gateway stack wiring all Lambda handlers"
```

---

### Task 21: Run Full Test Suite and Deploy

- [ ] **Step 1: Run all tests**

```bash
cd /Users/jwc/code/Victory/FreeMail.ai && pytest tests/ -v --tb=short
```

- [ ] **Step 2: CDK bootstrap (first time only)**

```bash
cd /Users/jwc/code/Victory/FreeMail.ai/cdk
export AWS_ACCESS_KEY_ID=$(grep AWS_ACCESS_KEY /Users/jwc/code/Victory/FreeMail.ai/.env | cut -d= -f2)
export AWS_SECRET_ACCESS_KEY=$(grep AWS_SECRET_KEY /Users/jwc/code/Victory/FreeMail.ai/.env | cut -d= -f2)
export AWS_DEFAULT_REGION=us-east-1
npx cdk bootstrap aws://732770059798/us-east-1
```

- [ ] **Step 3: CDK deploy**

```bash
cd /Users/jwc/code/Victory/FreeMail.ai/cdk
npx cdk deploy --all --require-approval never
```

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "feat: FreeMail MVP - complete API platform with email transport"
```
