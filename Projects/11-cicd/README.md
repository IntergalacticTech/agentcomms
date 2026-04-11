# CI/CD, Testing, and Delivery

This document is the implementation source of truth for FreeMail engineering. It defines the stack, the minimum testing bar, and how code moves to AWS.

---

## Canonical Stack

FreeMail launches with a narrow, intentionally pragmatic stack:

- **Backend, API handlers, workers, and metering:** Python 3.12 on AWS Lambda
- **Infrastructure as code:** TypeScript with AWS CDK v2
- **Developer console:** React + TypeScript + Vite
- **MCP server and Node tooling:** TypeScript on Node 20+
- **Launch SDKs:** Python and Node.js

### Why Python Over Laravel

Python is the better fit for the launch architecture because:

1. The system is already designed around Lambda, SES, SQS, DynamoDB, and Bedrock.
2. Python has better day-one ergonomics for MIME parsing, AWS workers, and AI-adjacent integrations.
3. Using Python plus TypeScript avoids splitting the backend and test stack across three ecosystems.

Laravel is not ruled out forever, but it should not be introduced unless the platform later grows a separate containerized application that clearly benefits from it.

---

## Delivery Principles

- GitHub Actions is the only supported deployment path.
- AWS access from CI uses GitHub OIDC federation.
- No long-lived AWS deploy keys should live in GitHub secrets.
- Staging deploys automatically from `main`.
- Production requires a protected GitHub environment and explicit approval.
- Production deployments must promote a commit already verified in staging.

---

## Repository Shape

The planned repository layout should map directly to the chosen stack:

```text
/
├── api/                 # OpenAPI specification
├── cdk/                 # TypeScript CDK app and infrastructure tests
├── lambdas/             # Python Lambda handlers and shared packages
├── console/             # React + TypeScript developer console
├── mcp/                 # TypeScript MCP server
├── sdks/
│   ├── python/
│   └── node/
├── tests/
│   ├── integration/
│   ├── e2e/
│   └── load/
└── .github/workflows/
```

Go SDK support can be added later if demand appears. It is not required for launch.

---

## Testing Strategy

### Required Test Layers

| Layer | Tooling | Purpose | Required In |
|-------|---------|---------|-------------|
| Python unit tests | `pytest`, `pytest-cov`, `moto` | business logic, handlers, MIME parsing, quotas, metering | every PR |
| Python integration tests | `pytest`, LocalStack, DynamoDB Local | send/receive, webhook, domain, queue, storage flows | every PR |
| API contract tests | OpenAPI lint + schema validation | keep implementation and SDKs aligned with the spec | every PR |
| Frontend unit tests | `vitest`, Testing Library | onboarding, inbox, domain, and usage console flows | every PR |
| Browser smoke tests | Playwright | signup, inbox creation, send/receive basics, custom domain flow | after staging deploy |
| Infrastructure tests | CDK synth + assertion tests | prevent accidental AWS drift and broken stacks | every PR |
| Load tests | k6 or Artillery | verify cost and performance assumptions | scheduled + pre-release |

### Coverage Gates

- backend coverage must fail below **85%**
- critical Python packages should maintain **90%+** coverage
- frontend coverage must fail below **80%**
- every bug fix must include a regression test
- new API endpoints must include unit coverage and at least one integration-path assertion

Critical packages include:

- auth and API key validation
- quota enforcement
- MIME parsing and thread resolution
- billing and Marketplace metering
- webhook signing and retry logic

### Definition Of Done For New Features

A feature is not done until:

- unit tests cover the business logic
- integration tests cover the AWS interaction path
- OpenAPI and SDK artifacts are updated if the public API changed
- dashboards and alarms exist for the new production path if it is operationally significant

---

## GitHub Actions Workflows

### `ci.yml`

Runs on every pull request and on pushes to `main`.

Required jobs:

- `python-quality`: `ruff`, `mypy`, dependency install sanity, `pytest --cov`
- `frontend-quality`: `pnpm lint`, `pnpm tsc --noEmit`, `pnpm vitest --coverage`
- `integration-tests`: LocalStack + DynamoDB Local + Python integration suite
- `cdk-synth`: `npm test` plus `cdk synth`
- `openapi-sdk-check`: lint the OpenAPI spec and verify generated SDKs are current

These jobs should be branch-protection requirements.

### `deploy-staging.yml`

Runs automatically on merge to `main`.

Required behavior:

- assume the staging deploy role with GitHub OIDC
- deploy CDK stacks to the staging environment
- build and deploy the console
- run Playwright and API smoke tests against staging
- fail loudly and notify if deployment or smoke tests fail

### `deploy-production.yml`

Runs manually with protected-environment approval.

Required behavior:

- deploy a commit that already passed through staging
- assume the production deploy role with GitHub OIDC
- deploy infrastructure and application artifacts
- run post-deploy smoke tests
- support rollback for Lambda aliases or prior stack state

### `sdk-publish.yml`

Release-driven workflow that:

- generates Python and Node SDKs from OpenAPI
- runs SDK tests
- publishes only from tagged releases

---

## Environment Model

Use three environments:

- `dev` for ad hoc engineer testing
- `staging` for merge-based integration and smoke tests
- `production` for customer traffic

Each environment should have:

- separate AWS stacks
- separate Cognito configuration
- separate SES configuration sets where needed
- separate console deployment targets

---

## Security And Secrets

- AWS deploy access comes from GitHub OIDC roles
- third-party secrets stay in GitHub environment secrets or AWS Secrets Manager
- production workflows require environment protection rules
- no manual infrastructure drift is acceptable; fixes must be codified in CDK

---

## What This Means For Launch

For the initial FreeMail release, the engineering organization should optimize for:

- Python backend velocity
- TypeScript infrastructure and frontend consistency
- aggressive automated test coverage from day one
- predictable staging deploys on every merge
- minimal manual release work
