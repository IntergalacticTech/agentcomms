# FreeMail Build Plan

## Project Context

**Product**: `FreeMail`
**Public brand**: `FreeMail`
**Current deployment/test domain**: `victorymail.dev`
**Target public domain**: `freemail.dev` when acquired
**AWS Account**: `732770059798`
**Primary region**: `us-east-1`
**IaC**: AWS CDK (TypeScript)
**App runtimes**: Python 3.12 for Lambda, TypeScript for CDK and frontend
**SES status**: Production access granted, 50K/day send quota, 14/sec send rate

### Naming Decision

`FreeMail` is the product name.

- Use `victorymail.dev` for initial deployment, SES verification, staging, and early production testing.
- Keep AWS resource names prefixed with `victorymail` until the public domain is finalized.
- Treat `freemail.dev` as the customer-facing brand/domain target.
- Legacy references to `AgentMail` in older docs are design inheritance, not the final product identity.

### What Already Exists

- Route53 hosted zone for `victorymail.dev`
- SES production access in the AWS account
- Prior SES identity history for another domain
- No infrastructure deployed yet for this project

---

## Product Strategy

### Launch Thesis

Launch **FreeMail as a free SaaS product first**, then layer paid and enterprise paths after real usage appears.

### Core Commercial Decisions

1. The initial product is **direct SaaS**, not Marketplace-first.
2. The free tier should be **more generous than current agent-email competitors**, especially on **custom domains**.
3. **AI features are paid-only** because Bedrock/OpenSearch are the first meaningful marginal-cost drivers.
4. The self-serve paid tier is **Pro**. Anything above Pro should be pushed toward **AWS Marketplace** rather than a large matrix of SaaS plans.
5. Marketplace is the path for:
   - customers who exceed Pro-level mailbox/domain/throughput needs
   - customers who need procurement through AWS
   - customers who want committed spend, private offers, or enterprise controls

### Product Wedge

The launch wedge is not "best AI email platform." It is:

- free API-first inboxes for agents
- custom domains available at the free tier
- low-friction onboarding
- inexpensive upgrade path
- clear migration path to AWS Marketplace when usage grows

---

## Technical Stack Decision

FreeMail should launch with a deliberately small two-language stack:

- **Backend, API handlers, email workers, billing logic:** Python 3.12 on AWS Lambda
- **Infrastructure as code:** TypeScript with AWS CDK v2
- **Developer console, MCP server, and Node SDK:** TypeScript on Node 20+
- **Launch SDKs:** Python and Node.js
- **Deferred until justified by usage:** Go SDK, containerized services, and any PHP/Laravel backend

### Why Python Is the Right Launch Backend

Python fits the current architecture better than Laravel for three reasons:

1. The planned system is already Lambda, SES, SQS, DynamoDB, and Bedrock oriented.
2. Python has stronger off-the-shelf support for MIME parsing, AWS automation, and AI-related tooling.
3. Avoiding a second backend stack keeps launch speed, hiring profile, CI setup, and test tooling simpler.

Laravel is not banned forever, but it should not be the launch path. If FreeMail later needs a containerized back-office app or a long-lived relational service, that can be evaluated separately without changing the initial architecture.

---

## Quality and Delivery Standards

FreeMail should be shipped through GitHub Actions only. No manual console changes should be part of the normal deployment path.

### Required Test Gates

- backend unit and integration suites must run in CI on every pull request
- backend coverage must fail below **85%** overall
- security-sensitive and platform-critical Python modules should target **90%+** coverage
- frontend unit coverage should fail below **80%**
- staging smoke tests must pass before any production promotion
- every bug fix requires a regression test
- CDK stacks must pass synth and assertion tests before merge

### Deployment Rules

- use GitHub Actions with AWS OIDC federation, not long-lived AWS access keys
- auto-deploy staging on merge to `main`
- require a protected GitHub environment approval for production
- promote a previously staged commit to production instead of deploying an unverified SHA
- run API and console smoke tests after every staging and production deploy

---

## Launch Scope

### In Scope for Initial Launch

- account signup and auth
- API key issuance
- inbox CRUD
- send email
- receive email
- threading
- attachments
- webhooks
- wait-for-email / OTP extraction
- custom domains
- MCP server
- free tier quota enforcement
- Pro tier billing
- basic developer console

### Explicitly Paid-Only at Launch

- semantic search
- AI categorization
- structured extraction
- any Bedrock-backed workflow

### Deferred Until After Launch

- IMAP/SMTP
- multi-region
- enterprise SSO/SAML
- SOC 2 / HIPAA packaging
- dedicated infrastructure options
- self-hosting
- advanced analytics

---

## Phase Overview

```
Phase 0   Foundation and domain verification
Phase 1   Free SaaS MVP launch
Phase 2   Pro tier and paid AI
Phase 3   AWS Marketplace migration path
Phase 4   Scale and enterprise features
```

The sequence is intentional:

- Launch usefulness first
- Launch free SaaS second
- Add paid AI only when the base product is working
- Add Marketplace only after there are users worth migrating

---

## Phase 0: Foundation

**Goal**: Stand up the base AWS project, verify `victorymail.dev` in SES, and create a deployable skeleton.

### Work

- Initialize CDK app in `cdk/`
- Create base stacks:
  - `network-stack.ts`
  - `data-stack.ts`
  - `cache-stack.ts`
  - `email-stack.ts`
  - `api-stack.ts`
  - `compute-stack.ts`
  - `auth-stack.ts`
- Create Lambda package structure
- Bootstrap CDK in `us-east-1`
- Verify `victorymail.dev` in SES with DKIM/SPF/DMARC/MX
- Set up GitHub Actions for lint, test, synth, and staged deployment via OIDC
- Enable branch protection with required CI checks
- Configure dev/staging/prod CDK context
- Create the initial unit, integration, and smoke test harnesses

### Exit Criteria

- `cdk synth` succeeds
- `victorymail.dev` is verified in SES
- API placeholder can deploy on `api-dev.victorymail.dev`
- CI can deploy a dev or staging skeleton without manual AWS credentials

---

## Phase 1: Free SaaS MVP Launch

**Goal**: Ship a usable public beta of FreeMail as a free SaaS product.

### MVP Capabilities

- user signup/login
- organization creation
- API key management
- inbox creation on platform domain
- inbound email receive pipeline
- outbound send pipeline
- thread listing and message retrieval
- attachments upload/download
- webhooks
- custom domain onboarding
- long-poll wait endpoint
- OTP extraction endpoint
- MCP server
- basic usage/quota enforcement
- basic docs + quickstart

### Implementation Priorities

#### 1. Authentication and onboarding

- Cognito user pool
- email/password auth
- org-to-user mapping
- console route protection
- create-first-org flow
- generate first API key during onboarding

#### 2. Core email platform

- DynamoDB single-table model for orgs, inboxes, messages, threads, domains, keys
- S3 buckets for raw MIME, bodies, attachments, exports
- SES inbound via receipt rules
- SQS-backed outbound worker
- Redis for auth cache, rate limiting, and routing cache

#### 3. Developer-facing features needed at launch

- OpenAPI spec
- Python SDK
- Node SDK
- MCP server package
- webhook signing
- wait-for-email and OTP extraction

#### 4. Free tier enforcement

Working assumptions for launch:

- generous free tier
- at least one custom domain on free
- AI disabled on free
- hard blocks instead of overage billing on free

#### 5. Testable launch quality

- `pytest` covers the shared domain logic, Lambda handlers, and queue workers
- integration tests cover SES/S3/SQS/DynamoDB flows using local AWS emulators
- console flows have `vitest` coverage and Playwright smoke coverage
- OpenAPI and generated SDKs stay in sync through CI

### Exit Criteria

- A new user can sign up in the console
- A new org can create an inbox and send/receive email
- A free user can attach one custom domain
- Wait and OTP flows work from API and MCP
- Public beta can onboard external testers
- staging deployments run automatically from GitHub Actions

---

## Phase 2: Pro Tier and Paid AI

**Goal**: Add the minimum paid layer needed to monetize expensive features without distracting from launch.

### Pro Tier Principles

- Keep pricing simple
- Compete below or near current market pricing
- Unlock more inboxes, more domains, and higher throughput
- Unlock AI as a paid feature set
- Avoid adding extra self-serve tiers before there is demand

### Work

- Stripe integration for a single `Pro` plan
- billing portal
- plan-aware quota enforcement
- Pro-level throughput and domain limits
- Bedrock-backed AI endpoints:
  - categorization
  - extraction
  - semantic search
- cost guardrails for AI usage
- per-org AI usage accounting

### Exit Criteria

- Users can upgrade from Free to Pro
- Pro users can access AI features
- AI usage is bounded and observable
- Gross margin risk from Bedrock is visible in dashboards

---

## Phase 3: AWS Marketplace Migration Path

**Goal**: Enable customers above Pro to move to AWS Marketplace without changing product shape.

### Marketplace Positioning

Marketplace is not the first sales channel.

It is the channel for:

- higher mailbox counts
- higher custom-domain counts
- higher send/receive throughput
- heavier AI workloads
- procurement-led customers

### Work

- finalize Marketplace metering dimensions
- implement fulfillment flow
- store `CustomerAWSAccountId` and `LicenseArn`
- implement entitlement sync
- implement hourly metering
- implement SaaS-to-Marketplace migration flow
- create at least one private offer path before public listing

### Canonical Marketplace Integration Rules

- Treat `CustomerAWSAccountId` and `LicenseArn` as the long-term primary identifiers
- Store `CustomerIdentifier` and `ProductCode` for compatibility/reference
- Do not publish a listing until metering dimensions are frozen
- Do not rely on Marketplace free trials auto-converting to paid

### Exit Criteria

- A Pro customer can migrate to Marketplace without data loss
- Metering is auditable and retry-safe
- Private offers are operational

---

## Phase 4: Scale and Enterprise

**Goal**: Add features that matter only after the product has active usage and clear demand.

### Candidate Work

- IMAP/SMTP
- multi-region architecture
- deliverability pools and dedicated IP options
- enterprise audit logs
- SSO/SAML
- compliance packaging
- dedicated infrastructure options

This phase is intentionally open-ended. It should be prioritized from real customer demand, not pre-launch ambition.

---

## Immediate Build Order

If work starts now, the recommended execution order is:

1. CDK bootstrap, SES verification, base infrastructure
2. auth + org model + API keys
3. inbox CRUD + inbound + outbound
4. messages, threads, attachments
5. webhooks
6. custom domains
7. wait/OTP endpoints
8. MCP server
9. free tier quotas + console polish
10. external beta launch
11. Pro billing
12. paid AI
13. Marketplace migration

---

## Current Open Questions

These are intentionally left unresolved for now:

- final public domain for production branding
- exact free and Pro pricing
- exact quota levels for inboxes, domains, and throughput
- whether Pro bundles AI credits or bills AI separately
- exact Marketplace public tier names

None of these should block Phase 0 or Phase 1.

---

## Non-Negotiable Planning Corrections

The repo should now assume:

- FreeMail is the product name
- `victorymail.dev` is the temporary deployment/test domain
- free SaaS launches before Marketplace
- AI is paid-only
- Marketplace is the upgrade path beyond Pro
- long-poll design must use a technically valid API Gateway approach
- Marketplace implementation must use current AWS guidance for identifiers and free-trial behavior
