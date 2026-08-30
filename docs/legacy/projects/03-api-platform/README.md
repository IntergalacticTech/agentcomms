# API Platform

This document is the source of truth for the FreeMail application runtime. FreeMail launches as a REST-first API on API Gateway and AWS Lambda, with Python as the primary backend language.

---

## Canonical Implementation Choice

- **Backend language:** Python 3.12
- **API runtime:** API Gateway REST API + Lambda
- **Validation and shared models:** Pydantic v2
- **Operational tooling:** AWS Lambda Powertools, boto3, pytest
- **Specification:** OpenAPI 3.1
- **Launch SDKs:** Python and Node.js
- **Non-launch choices:** Laravel/PHP backend, GraphQL, and Go SDK

### Why Python

Python is the better launch fit than Laravel because the product is already centered on SES, SQS, DynamoDB, and Lambda workers. Email parsing, AWS integrations, and AI-adjacent tooling are all stronger and simpler in Python, and using one backend stack keeps the platform easier to test and deploy.

---

## Runtime Shape

```text
Client (SDK / HTTP / MCP / Console)
        |
   Route 53 / CloudFront
        |
   API Gateway (REST)
        |
   Lambda authorizer + Python Lambda handlers
        |
   +-----------+-----------+-----------+-----------+
   | DynamoDB  |    S3     |   Redis   |    SQS    |
   | metadata  | email/raw | auth/cache| async work|
   +-----------+-----------+-----------+-----------+
        |
       SES
```

### Launch Request Flow

1. Requests arrive through API Gateway.
2. Authentication is resolved through API keys for programmatic clients or Cognito-backed user sessions for the console.
3. Python handlers validate input, enforce quotas, and write durable state to DynamoDB and S3.
4. Async work such as email sending, webhook delivery, and post-processing runs through SQS-backed workers.

---

## Launch API Surface

The initial REST surface should cover:

- account signup and organization bootstrap
- API key management
- inbox CRUD
- message send, list, and retrieval
- thread listing and retrieval
- attachments
- custom domains
- webhooks
- `wait` and `otp`
- usage and quota visibility

AI endpoints stay behind paid plans and should not complicate the initial public beta surface.

---

## Design Rules

1. **REST over GraphQL.** Machine clients need predictable, stable resource paths more than flexible query graphs.
2. **Resource-group Lambdas.** Group routes by domain area such as inboxes, messages, domains, and webhooks instead of one function per endpoint.
3. **OpenAPI is the contract.** The spec drives request validation, SDK generation, and contract tests.
4. **Async by default for expensive work.** Send, receive, webhook retry, and AI pipelines should not block synchronous API requests.
5. **No separate admin backend.** The console uses the same core API as customer code.

---

## Testing Expectations for the API

- unit tests on Python handlers and shared services
- contract tests to keep implementation aligned with OpenAPI
- integration tests for DynamoDB, S3, SQS, SES, and domain flows
- staging smoke tests for signup, inbox creation, send/receive, and webhook delivery

The CI/CD policy and coverage thresholds live in [Projects/11-cicd/README.md](../11-cicd/README.md).

---

## Deferred

- GraphQL
- IMAP/SMTP compatibility
- PHP/Laravel application server
- Go SDK
- multi-region routing
