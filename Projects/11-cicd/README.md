# CI/CD and Infrastructure as Code

AgentMail's infrastructure is defined entirely in AWS CDK (TypeScript), deployed through GitHub Actions, and promoted through three environments: dev, staging, and production. There are no manual AWS console changes. Every resource -- from DynamoDB tables to Lambda functions to SES configuration sets -- is codified, version-controlled, and reproducible.

This document covers the CDK stack architecture, repository layout, CI pipeline, deployment strategies (including canary releases), multi-region deployment, testing strategy, and environment management.

---

## Table of Contents

- [CDK Stack Architecture](#cdk-stack-architecture)
- [Repository Structure](#repository-structure)
- [CI Pipeline](#ci-pipeline)
- [Deployment Strategy](#deployment-strategy)
- [Multi-Region Deployment](#multi-region-deployment)
- [Testing Strategy](#testing-strategy)
- [Environment Management](#environment-management)
- [Secrets Management](#secrets-management)

---

## CDK Stack Architecture

The infrastructure is divided into 10 CDK stacks, each responsible for a distinct layer of the platform. Stacks have explicit dependencies -- CDK deploys them in the correct order.

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentMailApp (CDK App)                    │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  NetworkStack │  │  DataStack   │  │  CacheStack  │      │
│  │  (VPC, SGs)   │  │  (DynamoDB,  │  │  (Redis)     │      │
│  │               │  │   S3)        │  │              │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                  │              │
│  ┌──────┴─────────────────┴──────────────────┴──────┐       │
│  │                    EmailStack                     │       │
│  │  (SES config, receipt rules, sending config)      │       │
│  └──────────────────────┬───────────────────────────┘       │
│                         │                                   │
│  ┌──────────────────────┴───────────────────────────┐       │
│  │                     ApiStack                      │       │
│  │  (API Gateway, authorizer, route config)          │       │
│  └──────────────────────┬───────────────────────────┘       │
│                         │                                   │
│  ┌──────────────────────┴───────────────────────────┐       │
│  │                   ComputeStack                    │       │
│  │  (Lambda functions, layers, SQS queues)           │       │
│  └──────────────────────┬───────────────────────────┘       │
│                         │                                   │
│  ┌──────────────────────┴───────────────────────────┐       │
│  │                   EventsStack                     │       │
│  │  (Kinesis streams, WebSocket API, event rules)    │       │
│  └──────────────────────┬───────────────────────────┘       │
│                         │                                   │
│  ┌──────────────────────┴───────────────────────────┐       │
│  │                     AiStack                       │       │
│  │  (OpenSearch Serverless, Bedrock config,          │       │
│  │   Step Functions, embedding pipeline)             │       │
│  └──────────────────────┬───────────────────────────┘       │
│                         │                                   │
│  ┌──────────────────────┴───────────────────────────┐       │
│  │                 MarketplaceStack                   │       │
│  │  (Metering pipeline, lifecycle handlers, SNS)     │       │
│  └──────────────────────┬───────────────────────────┘       │
│                         │                                   │
│  ┌──────────────────────┴───────────────────────────┐       │
│  │               ObservabilityStack                  │       │
│  │  (Dashboards, alarms, X-Ray, log groups)          │       │
│  └──────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### Stack Details

| Stack | Resources | Dependencies | Outputs |
|-------|-----------|-------------|---------|
| **NetworkStack** | VPC (2 AZs, private + public subnets), Security Groups, VPC Endpoints (DynamoDB, S3, SES, SQS, Kinesis, Secrets Manager) | None | VPC ID, subnet IDs, SG IDs |
| **DataStack** | DynamoDB single table (on-demand), 4 S3 buckets (raw-email, attachments, bodies, exports), S3 lifecycle policies, DynamoDB Streams | NetworkStack | Table name, table ARN, bucket names, stream ARN |
| **CacheStack** | ElastiCache Redis cluster (cluster mode enabled, 2 shards, 1 replica each), parameter group, subnet group | NetworkStack | Redis endpoint, Redis port |
| **EmailStack** | SES email identities (platform domain), SES receipt rule set (catch-all), SES configuration sets (default + per-org template), SNS topics for bounce/complaint/delivery events, SES IP pool configuration | DataStack | Receipt rule set name, SNS topic ARNs, default config set name |
| **ApiStack** | API Gateway REST API (regional), custom domain mapping, usage plans, API keys (for rate limiting), WAF WebACL | NetworkStack, CacheStack | API endpoint URL, API ID |
| **ComputeStack** | Lambda functions (authorizer, 12 API handlers, inbound-router, send-worker, webhook-delivery), Lambda layers (shared utilities, AWS SDK), SQS queues (send queue, webhook queue, DLQs), IAM roles per function | All above stacks | Function ARNs, queue URLs |
| **EventsStack** | Kinesis Data Stream (4 shards), WebSocket API (API Gateway), connection management Lambda, ws-fanout Lambda, EventBridge rules | ComputeStack, CacheStack | Kinesis stream ARN, WebSocket endpoint |
| **AiStack** | OpenSearch Serverless collection (vector search), Bedrock model access, Step Functions state machine (orchestration), embedding Lambda, categorizer Lambda, extractor Lambda | DataStack, ComputeStack | OpenSearch endpoint, state machine ARN |
| **MarketplaceStack** | Metering Lambda (hourly), aggregation DynamoDB table, DLQ for failed metering, SNS subscription for lifecycle events, fulfillment Lambda (ResolveCustomer) | DataStack, ComputeStack | Metering function ARN |
| **ObservabilityStack** | CloudWatch dashboards (platform + tenant template), CloudWatch alarms (P0/P1/P2), SNS topics for alarm routing, X-Ray sampling rules, log groups with retention policies | All stacks | Dashboard URLs, alarm ARNs |

### CDK Configuration

```typescript
// cdk/bin/agentmail.ts
import * as cdk from 'aws-cdk-lib';
import { NetworkStack } from '../lib/network-stack';
import { DataStack } from '../lib/data-stack';
import { CacheStack } from '../lib/cache-stack';
import { EmailStack } from '../lib/email-stack';
import { ApiStack } from '../lib/api-stack';
import { ComputeStack } from '../lib/compute-stack';
import { EventsStack } from '../lib/events-stack';
import { AiStack } from '../lib/ai-stack';
import { MarketplaceStack } from '../lib/marketplace-stack';
import { ObservabilityStack } from '../lib/observability-stack';

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: app.node.tryGetContext('region') || 'us-east-1',
};

const stage = app.node.tryGetContext('stage') || 'dev';
const prefix = `agentmail-${stage}`;

const network = new NetworkStack(app, `${prefix}-network`, { env, stage });
const data = new DataStack(app, `${prefix}-data`, { env, stage, vpc: network.vpc });
const cache = new CacheStack(app, `${prefix}-cache`, { env, stage, vpc: network.vpc, securityGroups: network.securityGroups });
const email = new EmailStack(app, `${prefix}-email`, { env, stage, table: data.table, buckets: data.buckets });
const api = new ApiStack(app, `${prefix}-api`, { env, stage, vpc: network.vpc, cache: cache.redis });
const compute = new ComputeStack(app, `${prefix}-compute`, {
  env, stage,
  vpc: network.vpc,
  table: data.table,
  buckets: data.buckets,
  cache: cache.redis,
  api: api.restApi,
  emailConfig: email.config,
});
const events = new EventsStack(app, `${prefix}-events`, { env, stage, vpc: network.vpc, cache: cache.redis, compute: compute });
const ai = new AiStack(app, `${prefix}-ai`, { env, stage, vpc: network.vpc, table: data.table, buckets: data.buckets });
const marketplace = new MarketplaceStack(app, `${prefix}-marketplace`, { env, stage, table: data.table, compute: compute });
new ObservabilityStack(app, `${prefix}-observability`, {
  env, stage,
  functions: compute.functions,
  api: api.restApi,
  table: data.table,
  queues: compute.queues,
  stream: events.kinesisStream,
  cache: cache.redis,
});
```

---

## Repository Structure

```
/
├── api/
│   ├── openapi.yaml                    # OpenAPI 3.1 specification (source of truth)
│   └── examples/                       # Request/response examples for docs
│       ├── create-inbox.json
│       ├── send-message.json
│       └── ...
│
├── cdk/
│   ├── bin/
│   │   └── agentmail.ts                # CDK app entry point
│   ├── lib/
│   │   ├── network-stack.ts
│   │   ├── data-stack.ts
│   │   ├── cache-stack.ts
│   │   ├── email-stack.ts
│   │   ├── api-stack.ts
│   │   ├── compute-stack.ts
│   │   ├── events-stack.ts
│   │   ├── ai-stack.ts
│   │   ├── marketplace-stack.ts
│   │   ├── observability-stack.ts
│   │   └── constructs/                 # Reusable L3 constructs
│   │       ├── lambda-function.ts      # Standard Lambda with tracing, logging, layers
│   │       ├── sqs-with-dlq.ts         # SQS queue + DLQ pair
│   │       └── monitored-fargate.ts    # Fargate service with alarms
│   ├── test/
│   │   ├── network-stack.test.ts
│   │   ├── data-stack.test.ts
│   │   ├── snapshot/                   # CDK snapshot tests
│   │   └── ...
│   ├── cdk.json
│   ├── cdk.context.json
│   └── tsconfig.json
│
├── lambdas/
│   ├── authorizer/
│   │   ├── index.py                    # API Gateway Lambda authorizer
│   │   ├── requirements.txt
│   │   └── tests/
│   ├── api-handlers/
│   │   ├── inboxes/
│   │   │   ├── create.py
│   │   │   ├── get.py
│   │   │   ├── list.py
│   │   │   ├── update.py
│   │   │   ├── delete.py
│   │   │   └── tests/
│   │   ├── messages/
│   │   │   ├── send.py
│   │   │   ├── get.py
│   │   │   ├── list.py
│   │   │   └── tests/
│   │   ├── threads/
│   │   │   ├── get.py
│   │   │   ├── list.py
│   │   │   └── tests/
│   │   ├── drafts/
│   │   │   ├── create.py
│   │   │   ├── update.py
│   │   │   ├── delete.py
│   │   │   ├── send.py
│   │   │   └── tests/
│   │   ├── domains/
│   │   │   ├── create.py
│   │   │   ├── verify.py
│   │   │   ├── list.py
│   │   │   └── tests/
│   │   ├── webhooks/
│   │   │   ├── create.py
│   │   │   ├── update.py
│   │   │   ├── delete.py
│   │   │   ├── list.py
│   │   │   └── tests/
│   │   ├── search/
│   │   │   ├── semantic.py
│   │   │   └── tests/
│   │   ├── ai/
│   │   │   ├── categorize.py
│   │   │   ├── extract.py
│   │   │   └── tests/
│   │   ├── metrics/
│   │   │   ├── get.py
│   │   │   └── tests/
│   │   ├── organizations/
│   │   │   ├── create.py
│   │   │   ├── get.py
│   │   │   ├── update.py
│   │   │   └── tests/
│   │   ├── api-keys/
│   │   │   ├── create.py
│   │   │   ├── list.py
│   │   │   ├── revoke.py
│   │   │   └── tests/
│   │   ├── pods/
│   │   │   ├── create.py
│   │   │   ├── get.py
│   │   │   ├── list.py
│   │   │   └── tests/
│   │   └── lists/
│   │       ├── update_allow.py
│   │       ├── update_block.py
│   │       └── tests/
│   ├── inbound-processor/
│   │   ├── router.py                   # SES inbound notification handler
│   │   ├── mime_parser.py              # MIME parsing utilities
│   │   ├── thread_resolver.py          # Thread computation
│   │   ├── requirements.txt
│   │   └── tests/
│   ├── send-worker/
│   │   ├── handler.py                  # SQS → SES SendRawEmail
│   │   ├── mime_builder.py             # MIME message construction
│   │   ├── requirements.txt
│   │   └── tests/
│   ├── ws-fanout/
│   │   ├── handler.py                  # Kinesis → WebSocket push
│   │   ├── requirements.txt
│   │   └── tests/
│   ├── ai-pipeline/
│   │   ├── categorizer.py              # Bedrock categorization
│   │   ├── extractor.py                # Bedrock data extraction
│   │   ├── embedder.py                 # Bedrock embedding generation
│   │   ├── requirements.txt
│   │   └── tests/
│   ├── marketplace/
│   │   ├── metering.py                 # Hourly metering submission
│   │   ├── lifecycle.py                # SNS lifecycle handler
│   │   ├── fulfillment.py              # ResolveCustomer handler
│   │   ├── requirements.txt
│   │   └── tests/
│   └── shared/
│       ├── dynamo_client.py            # DynamoDB helper (single table patterns)
│       ├── s3_client.py                # S3 helper (presigned URLs, etc.)
│       ├── redis_client.py             # Redis connection pooling
│       ├── logger.py                   # Structured JSON logger
│       ├── metrics.py                  # EMF metric publisher
│       ├── auth.py                     # API key validation
│       ├── errors.py                   # Standard error types
│       └── models.py                   # Pydantic models for entities
│
├── services/
│   ├── webhook-delivery/
│   │   ├── Dockerfile
│   │   ├── handler.py                  # Long-running webhook delivery (ECS)
│   │   ├── requirements.txt
│   │   └── tests/
│   ├── imap-server/
│   │   ├── Dockerfile
│   │   ├── config/                     # Stalwart configuration
│   │   ├── plugins/                    # Custom storage backend
│   │   └── tests/
│   └── smtp-relay/
│       ├── Dockerfile
│       ├── config/                     # Haraka configuration
│       ├── plugins/                    # AgentMail auth, rewrite, queue plugins
│       └── tests/
│
├── sdks/
│   ├── python/
│   │   ├── agentmail/                  # Generated + hand-tuned Python SDK
│   │   ├── tests/
│   │   ├── setup.py
│   │   └── pyproject.toml
│   ├── node/
│   │   ├── src/                        # Generated + hand-tuned TypeScript SDK
│   │   ├── tests/
│   │   ├── package.json
│   │   └── tsconfig.json
│   └── go/
│       ├── agentmail/                  # Generated Go SDK
│       ├── go.mod
│       └── go.sum
│
├── tests/
│   ├── integration/                    # Integration tests (DynamoDB local, LocalStack)
│   │   ├── test_inbox_crud.py
│   │   ├── test_message_flow.py
│   │   ├── test_webhook_delivery.py
│   │   ├── conftest.py                 # Fixtures: DynamoDB local, S3 mock
│   │   └── docker-compose.yml          # DynamoDB local + LocalStack
│   ├── e2e/                            # End-to-end tests (staging environment)
│   │   ├── test_full_flow.py
│   │   ├── test_inbound_email.py
│   │   ├── test_webhook_e2e.py
│   │   └── conftest.py                 # Staging API key, endpoints
│   └── load/
│       ├── artillery.yml               # Artillery load test config
│       ├── scenarios/
│       │   ├── create-inboxes.yml
│       │   ├── send-messages.yml
│       │   ├── mixed-workload.yml
│       │   └── webhook-delivery.yml
│       └── processors/
│           └── custom-functions.js
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                      # PR checks: lint, test, CDK synth
│   │   ├── deploy-staging.yml          # Auto-deploy to staging on merge to main
│   │   ├── deploy-prod.yml             # Manual approval → canary deploy to production
│   │   ├── sdk-publish.yml             # Publish SDKs to PyPI, npm, GitHub
│   │   └── load-test.yml              # Weekly load tests on staging
│   ├── CODEOWNERS
│   └── pull_request_template.md
│
├── scripts/
│   ├── generate-sdks.sh                # OpenAPI Generator SDK generation
│   ├── seed-dev.sh                     # Seed dev environment with test data
│   ├── run-integration-tests.sh        # Start DynamoDB local + run tests
│   └── check-ses-limits.sh             # Check SES sending limits
│
├── docs/
│   ├── api-reference/                  # Generated from OpenAPI spec
│   └── architecture/                   # Architecture diagrams (draw.io source)
│
├── .env.example                        # Environment variable template
├── Makefile                            # Common commands (make test, make deploy, etc.)
└── pyproject.toml                      # Root Python config (monorepo tools)
```

---

## CI Pipeline

### Pull Request Checks (`ci.yml`)

Every pull request triggers the full CI pipeline. All checks must pass before merge.

```yaml
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Python lint
        run: |
          pip install ruff mypy
          ruff check lambdas/ services/ tests/
          ruff format --check lambdas/ services/ tests/
          mypy lambdas/ --ignore-missing-imports
      - name: CDK lint
        working-directory: cdk
        run: |
          npm ci
          npx eslint lib/ bin/ test/
      - name: OpenAPI lint
        run: |
          npx @redocly/cli lint api/openapi.yaml

  unit-test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install pytest pytest-cov moto boto3 pydantic
          pip install -r lambdas/shared/requirements.txt
      - name: Run unit tests
        run: |
          pytest lambdas/ -v --cov=lambdas --cov-report=xml \
            --ignore=lambdas/shared/tests/integration
        env:
          AWS_DEFAULT_REGION: us-east-1
          AWS_ACCESS_KEY_ID: testing
          AWS_SECRET_ACCESS_KEY: testing
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
          fail_ci_if_error: false

  integration-test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    services:
      dynamodb-local:
        image: amazon/dynamodb-local:latest
        ports:
          - 8000:8000
      localstack:
        image: localstack/localstack:3.0
        ports:
          - 4566:4566
        env:
          SERVICES: s3,sqs,ses,kinesis,secretsmanager
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install pytest boto3 pydantic requests
          pip install -r lambdas/shared/requirements.txt
      - name: Run integration tests
        run: |
          pytest tests/integration/ -v --timeout=60
        env:
          DYNAMODB_ENDPOINT: http://localhost:8000
          AWS_ENDPOINT_URL: http://localhost:4566
          AWS_DEFAULT_REGION: us-east-1
          AWS_ACCESS_KEY_ID: testing
          AWS_SECRET_ACCESS_KEY: testing

  cdk-synth:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: CDK synth
        working-directory: cdk
        run: |
          npm ci
          npx cdk synth --context stage=dev --quiet
      - name: CDK snapshot test
        working-directory: cdk
        run: |
          npm test
      - name: CDK diff (informational)
        working-directory: cdk
        run: |
          npx cdk diff --context stage=staging 2>&1 || true
        env:
          AWS_DEFAULT_REGION: us-east-1
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}

  sdk-test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Generate SDKs
        run: |
          bash scripts/generate-sdks.sh
      - name: Test Python SDK
        working-directory: sdks/python
        run: |
          pip install -e ".[test]"
          pytest tests/ -v
      - name: Test Node.js SDK
        working-directory: sdks/node
        run: |
          npm ci
          npm test
```

### CI Pipeline Duration Targets

| Job | Target | Max Allowed |
|-----|--------|-------------|
| lint | < 2 minutes | 5 minutes |
| unit-test | < 5 minutes | 10 minutes |
| integration-test | < 10 minutes | 15 minutes |
| cdk-synth | < 3 minutes | 5 minutes |
| sdk-test | < 5 minutes | 10 minutes |
| **Total (parallel)** | **< 10 minutes** | **15 minutes** |

All jobs run in parallel. Total CI time is bounded by the slowest job (integration-test).

---

## Deployment Strategy

### Staging Deployment (`deploy-staging.yml`)

Automatically triggered on every merge to `main`. Full CDK deploy to the staging environment.

```yaml
# .github/workflows/deploy-staging.yml
name: Deploy Staging

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          cd cdk && npm ci
          pip install -r lambdas/shared/requirements.txt

      - name: CDK deploy
        working-directory: cdk
        run: |
          npx cdk deploy --all \
            --context stage=staging \
            --require-approval never \
            --outputs-file ../cdk-outputs.json
        env:
          AWS_DEFAULT_REGION: us-east-1
          AWS_ACCESS_KEY_ID: ${{ secrets.STAGING_AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.STAGING_AWS_SECRET_ACCESS_KEY }}

      - name: Run smoke tests
        run: |
          API_URL=$(jq -r '.["agentmail-staging-api"].ApiEndpoint' cdk-outputs.json)
          python tests/e2e/smoke_test.py --api-url "$API_URL" --api-key "${{ secrets.STAGING_API_KEY }}"

      - name: Notify Slack
        if: always()
        uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {
              "text": "Staging deploy ${{ job.status }}: ${{ github.sha }}"
            }
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_DEPLOY_WEBHOOK }}
```

### Production Deployment (`deploy-prod.yml`)

Manual trigger with required approval. Uses canary deployment for Lambda functions and API Gateway.

```yaml
# .github/workflows/deploy-prod.yml
name: Deploy Production

on:
  workflow_dispatch:
    inputs:
      commit_sha:
        description: 'Commit SHA to deploy (must be deployed to staging first)'
        required: true
      confirm:
        description: 'Type "deploy-prod" to confirm'
        required: true

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Validate confirmation
        run: |
          if [ "${{ github.event.inputs.confirm }}" != "deploy-prod" ]; then
            echo "Confirmation failed. Type 'deploy-prod' to proceed."
            exit 1
          fi

      - name: Verify staging deployment
        run: |
          # Check that this SHA was successfully deployed to staging
          # (Query deployment tracking DynamoDB table or GitHub deployment API)
          echo "Verifying ${{ github.event.inputs.commit_sha }} is deployed to staging..."

  deploy:
    needs: validate
    runs-on: ubuntu-latest
    timeout-minutes: 45
    environment:
      name: production
      url: https://api.agentmail.dev
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.inputs.commit_sha }}

      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          cd cdk && npm ci
          pip install -r lambdas/shared/requirements.txt

      - name: CDK deploy (canary)
        working-directory: cdk
        run: |
          npx cdk deploy --all \
            --context stage=prod \
            --context canary=true \
            --require-approval never \
            --outputs-file ../cdk-outputs.json
        env:
          AWS_DEFAULT_REGION: us-east-1
          AWS_ACCESS_KEY_ID: ${{ secrets.PROD_AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.PROD_AWS_SECRET_ACCESS_KEY }}

      - name: Monitor canary (10 minutes)
        run: |
          echo "Monitoring canary deployment for 10 minutes..."
          for i in $(seq 1 10); do
            sleep 60
            # Check error rates, latency, and alarm states
            python scripts/check-canary-health.py \
              --region us-east-1 \
              --stage prod \
              --threshold-error-rate 1.0 \
              --threshold-p99-latency 2000
            echo "Canary check $i/10 passed"
          done

      - name: Promote canary
        if: success()
        run: |
          echo "Canary healthy. Promoting to full deployment."
          # CodeDeploy automatically promotes after canary period

      - name: Rollback on failure
        if: failure()
        run: |
          echo "Canary failed. Initiating rollback."
          python scripts/rollback-deployment.py --stage prod --region us-east-1
```

### Lambda Canary Deployment

Lambda functions use AWS CodeDeploy for traffic shifting:

```typescript
// cdk/lib/constructs/lambda-function.ts (simplified)
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as codedeploy from 'aws-cdk-lib/aws-codedeploy';

export class MonitoredLambdaFunction extends Construct {
  constructor(scope: Construct, id: string, props: MonitoredLambdaFunctionProps) {
    super(scope, id);

    const fn = new lambda.Function(this, 'Function', {
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      tracing: lambda.Tracing.ACTIVE,
      // ... other props
    });

    const alias = new lambda.Alias(this, 'Live', {
      aliasName: 'live',
      version: fn.currentVersion,
    });

    // Canary deployment (production only)
    if (props.stage === 'prod') {
      const deploymentGroup = new codedeploy.LambdaDeploymentGroup(this, 'DeploymentGroup', {
        alias: alias,
        deploymentConfig: codedeploy.LambdaDeploymentConfig.LINEAR_10PERCENT_EVERY_1MINUTE,
        autoRollback: {
          failedDeployment: true,
          stoppedDeployment: true,
          deploymentInAlarm: true,
        },
        alarms: [
          // Rollback if error rate exceeds 1% during canary
          new cloudwatch.Alarm(this, 'ErrorAlarm', {
            metric: alias.metricErrors({
              period: Duration.minutes(1),
            }),
            threshold: 1,
            evaluationPeriods: 1,
          }),
          // Rollback if P99 latency exceeds 3 seconds
          new cloudwatch.Alarm(this, 'LatencyAlarm', {
            metric: alias.metricDuration({
              period: Duration.minutes(1),
              statistic: 'p99',
            }),
            threshold: 3000,
            evaluationPeriods: 1,
          }),
        ],
      });
    }
  }
}
```

**Canary timeline (10-minute full rollout):**
```
T+0min:  10% traffic → new version, 90% → old version
T+1min:  20% → new, 80% → old   (alarm check)
T+2min:  30% → new, 70% → old   (alarm check)
T+3min:  40% → new, 60% → old   (alarm check)
T+4min:  50% → new, 50% → old   (alarm check)
T+5min:  60% → new, 40% → old   (alarm check)
T+6min:  70% → new, 30% → old   (alarm check)
T+7min:  80% → new, 20% → old   (alarm check)
T+8min:  90% → new, 10% → old   (alarm check)
T+9min:  100% → new              (alarm check)
T+10min: Deployment complete. Old version retained for rollback.
```

If any alarm fires during the canary, CodeDeploy automatically routes 100% of traffic back to the old version within 60 seconds.

### API Gateway Canary

API Gateway supports canary releases at the stage level:

```typescript
// 10% of traffic routes to canary stage for 10 minutes
const deployment = new apigateway.Deployment(this, 'Deployment', {
  api: restApi,
});

const stage = new apigateway.Stage(this, 'ProdStage', {
  deployment,
  stageName: 'prod',
  tracingEnabled: true,
  metricsEnabled: true,
  loggingLevel: apigateway.MethodLoggingLevel.ERROR,
});

// Canary settings
stage.node.defaultChild as apigateway.CfnStage;
(stage.node.defaultChild as apigateway.CfnStage).addPropertyOverride('CanarySetting', {
  PercentTraffic: 10,
  StageVariableOverrides: {
    lambdaAlias: 'canary',
  },
});
```

### DynamoDB Changes

DynamoDB schema changes follow strict rules:

| Change Type | Strategy | Risk |
|------------|----------|------|
| **Add GSI** | CDK adds GSI. DynamoDB backfills asynchronously. Non-breaking. | Low -- existing queries unaffected |
| **Remove GSI** | Mark as deprecated in code first. Remove all queries using it. Deploy code. Then remove GSI in next deployment. | Medium -- ensure no code references |
| **Add attribute** | Just start writing it. DynamoDB is schema-less. Readers handle missing attributes with defaults. | Low |
| **Rename attribute** | Never. Add new attribute, backfill, migrate readers, then stop writing old attribute. | High -- requires careful migration |
| **Change key schema** | Never on existing table. Create new table, migrate data, switch traffic. | Critical -- requires downtime planning |

---

## Multi-Region Deployment

### Strategy

Each region gets its own CDK deployment with shared configuration but independent resources:

```
us-east-1 (primary)              eu-west-1 (EU region)
├── NetworkStack                 ├── NetworkStack
├── DataStack                    ├── DataStack
│   ├── DynamoDB (global table)  │   ├── DynamoDB (global table replica)
│   └── S3 (CRR source)         │   └── S3 (CRR destination)
├── CacheStack                   ├── CacheStack
├── EmailStack                   ├── EmailStack
│   └── SES (us-east-1)         │   └── SES (eu-west-1)
├── ApiStack                     ├── ApiStack
│   └── api-us.agentmail.dev    │   └── api-eu.agentmail.dev
├── ComputeStack                 ├── ComputeStack
├── EventsStack                  ├── EventsStack
├── AiStack                      ├── AiStack
├── MarketplaceStack             ├── MarketplaceStack
└── ObservabilityStack           └── ObservabilityStack

                Route 53
        (latency-based routing)
         api.agentmail.dev
              │
    ┌─────────┴──────────┐
    ▼                    ▼
 us-east-1          eu-west-1
```

### Parameterized Stacks

```typescript
// Region-specific configuration
const regionConfig: Record<string, RegionConfig> = {
  'us-east-1': {
    sesInboundEnabled: true,   // SES inbound supported
    isPrimary: true,
    replicaRegions: ['eu-west-1'],
    certificateArn: 'arn:aws:acm:us-east-1:ACCOUNT:certificate/xxx',
  },
  'eu-west-1': {
    sesInboundEnabled: true,   // SES inbound supported
    isPrimary: false,
    replicaRegions: [],
    certificateArn: 'arn:aws:acm:eu-west-1:ACCOUNT:certificate/yyy',
  },
};
```

### Cross-Region Data Replication

| Service | Replication Method | Lag |
|---------|-------------------|-----|
| DynamoDB | Global Tables (active-active) | < 1 second (typically < 250ms) |
| S3 | Cross-Region Replication (CRR) | Minutes (async) |
| ElastiCache | Global Datastore | < 1 second |
| OpenSearch | Manual index replication (snapshot/restore) | Hours (acceptable for search) |

---

## Testing Strategy

### Testing Pyramid

```
                    ╱╲
                   ╱  ╲
                  ╱ E2E ╲           5-10 tests, staging only
                 ╱________╲         (full API flow with real SES)
                ╱          ╲
               ╱ Integration ╲      50-100 tests, CI + staging
              ╱________________╲    (DynamoDB local, LocalStack)
             ╱                  ╲
            ╱    Unit Tests      ╲  200-500 tests, CI
           ╱______________________╲ (moto mocks, pure functions)
          ╱                        ╲
         ╱     CDK Snapshot Tests   ╲  10-20 tests, CI
        ╱____________________________╲ (synthesized CloudFormation)
```

### Unit Tests

- **Scope**: Individual Lambda handler functions, utility modules, business logic
- **Mocking**: AWS services mocked with `moto` (DynamoDB, S3, SQS, SES, Kinesis)
- **Location**: `lambdas/*/tests/`
- **Runner**: `pytest`
- **Coverage target**: 80% line coverage
- **Run time**: < 5 minutes

### Integration Tests

- **Scope**: Multi-service interactions (e.g., create inbox → send message → verify in DynamoDB → verify in S3)
- **Infrastructure**: DynamoDB Local + LocalStack (S3, SQS, SES, Kinesis) via Docker Compose
- **Location**: `tests/integration/`
- **Runner**: `pytest`
- **Run time**: < 10 minutes

### End-to-End Tests

- **Scope**: Full API flows against the staging environment
- **Infrastructure**: Real AWS services in the staging account
- **Tests**:
  - Create organization → generate API key → create inbox → send message → verify delivery
  - Receive inbound email (send via SES to staging inbox) → verify webhook delivery
  - AI categorization flow → verify category stored on message
  - Webhook registration → trigger event → verify delivery with HMAC signature
- **Location**: `tests/e2e/`
- **Runner**: `pytest` (triggered after staging deploy)
- **Run time**: < 5 minutes

### Load Tests

- **Tool**: Artillery (https://artillery.io)
- **Schedule**: Weekly on staging (Sunday 02:00 UTC), on-demand before major releases
- **Scenarios**:
  - **Create inboxes**: 100 inboxes/second for 5 minutes (30,000 total)
  - **Send messages**: 500 messages/second for 10 minutes (300,000 total)
  - **Mixed workload**: Realistic mix of CRUD, send, search at 200 req/sec for 30 minutes
  - **Webhook delivery**: Generate 1,000 events/second, verify delivery latency
- **Success criteria**:
  - P99 latency < 500ms for all CRUD endpoints
  - P99 latency < 2s for send message
  - P99 latency < 3s for semantic search
  - Error rate < 0.1%
  - Zero throttling errors

```yaml
# tests/load/artillery.yml
config:
  target: "https://api-staging.agentmail.dev"
  phases:
    - name: "Warm up"
      duration: 60
      arrivalRate: 10
    - name: "Ramp up"
      duration: 120
      arrivalRate: 10
      rampTo: 200
    - name: "Sustained load"
      duration: 600
      arrivalRate: 200
    - name: "Cool down"
      duration: 60
      arrivalRate: 200
      rampTo: 0
  defaults:
    headers:
      Authorization: "Bearer {{ $processEnvironment.STAGING_API_KEY }}"
      Content-Type: "application/json"

scenarios:
  - name: "Mixed workload"
    weight: 100
    flow:
      - post:
          url: "/v1/inboxes"
          json:
            display_name: "Load Test Agent {{ $randomNumber(1, 100000) }}"
          capture:
            - json: "$.id"
              as: "inbox_id"
      - get:
          url: "/v1/inboxes/{{ inbox_id }}"
      - post:
          url: "/v1/inboxes/{{ inbox_id }}/messages"
          json:
            to: ["loadtest@example.com"]
            subject: "Load test {{ $timestamp }}"
            body: "This is a load test message."
      - get:
          url: "/v1/inboxes/{{ inbox_id }}/messages"
      - think: 1
```

---

## Environment Management

### AWS Account Structure

```
AWS Organizations
├── Management Account (billing, organization policies)
├── Dev Account (111111111111)
│   └── agentmail-dev-* stacks
│   └── Developer sandbox access (IAM Identity Center)
├── Staging Account (222222222222)
│   └── agentmail-staging-* stacks
│   └── CI/CD deployment role only
├── Production Account (333333333333)
│   └── agentmail-prod-* stacks
│   └── CI/CD deployment role only (manual approval gate)
│   └── Break-glass emergency access (logged, alerted)
└── Security Account (444444444444)
    └── CloudTrail aggregation
    └── GuardDuty master
    └── Config aggregation
```

### Environment Configuration

| Setting | Dev | Staging | Production |
|---------|-----|---------|-----------|
| DynamoDB mode | On-demand | On-demand | On-demand (provisioned at scale) |
| Lambda memory | 256 MB | 512 MB | 512 MB - 1024 MB |
| Lambda concurrency | Account default | 200 reserved | 1000 reserved |
| Redis nodes | 1 shard, no replica | 2 shards, 1 replica | 2 shards, 2 replicas |
| OpenSearch | 2 OCU (minimum) | 4 OCU | 8-20 OCU (auto-scaling) |
| SES mode | Sandbox | Production | Production |
| API Gateway throttle | 100 req/sec | 1000 req/sec | 10,000 req/sec |
| Kinesis shards | 1 | 2 | 4-16 (auto-scaling) |
| CloudWatch alarms | Disabled | P1 + P2 only | P0 + P1 + P2 |
| X-Ray sampling | 100% | 20% | 5% |
| Log retention | 7 days | 30 days | 30 days hot, 90 days S3 |
| Custom domain | dev.agentmail.dev | staging.agentmail.dev | api.agentmail.dev |
| Canary deployment | No | No | Yes |
| WAF | Disabled | Enabled (count mode) | Enabled (block mode) |
| Budget alert | $100/month | $500/month | $5,000/month |

---

## Secrets Management

All secrets are stored in AWS Secrets Manager and injected into Lambda/ECS at runtime:

| Secret | Path | Consumers |
|--------|------|-----------|
| SES SMTP credentials | `/agentmail/{stage}/ses/smtp` | send-worker Lambda |
| Redis auth token | `/agentmail/{stage}/redis/auth` | All Lambdas, ECS services |
| OpenSearch credentials | `/agentmail/{stage}/opensearch/auth` | AI Lambdas, search handler |
| Marketplace product code | `/agentmail/{stage}/marketplace/product-code` | Metering Lambda |
| Slack webhook URLs | `/agentmail/{stage}/slack/webhooks` | Alarm notification Lambda |
| PagerDuty integration key | `/agentmail/{stage}/pagerduty/key` | SNS → PagerDuty integration |
| TLS certificates (IMAP/SMTP) | `/agentmail/{stage}/tls/imap`, `/agentmail/{stage}/tls/smtp` | ECS IMAP/SMTP services |
| Platform API master key | `/agentmail/{stage}/api/master-key` | E2E tests, admin operations |

Secrets are cached in Lambda execution environments for the lifetime of the warm container (typically 5-15 minutes). The shared Redis client also caches secrets to avoid Secrets Manager API calls on every invocation.

### Secret Rotation

| Secret | Rotation Period | Method |
|--------|----------------|--------|
| Redis auth token | 90 days | Secrets Manager automatic rotation + ElastiCache AUTH update |
| TLS certificates | Annually (or 90 days if Let's Encrypt) | Automated renewal via ACM or certbot |
| Marketplace product code | Never (static) | N/A |
| Platform API master key | 90 days | Manual rotation with dual-write period |
