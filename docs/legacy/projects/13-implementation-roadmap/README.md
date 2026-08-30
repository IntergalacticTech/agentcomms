# Implementation Roadmap

This roadmap replaces the earlier year-long sequence with a launch-first plan aligned to the current strategy:

- launch **FreeMail** as a free SaaS product first
- use `victorymail.dev` for initial deployment and testing
- keep AI features paid-only
- use AWS Marketplace as the path beyond Pro, not the initial go-to-market channel

---

## Planning Assumptions

- The product is greenfield.
- The fastest credible path is better than a complete feature matrix.
- Custom domains are a launch differentiator, not a later add-on.
- Marketplace work should start only after the free SaaS product is usable.
- IMAP/SMTP, multi-region, and enterprise packaging are post-launch work.

---

## Implementation Stack

The launch stack is intentionally narrow:

- **Backend and platform workers:** Python 3.12 on AWS Lambda
- **Infrastructure:** TypeScript with AWS CDK v2
- **Console and MCP tooling:** TypeScript, React, and Vite
- **Launch SDKs:** Python and Node.js

PHP/Laravel is not the launch backend. It would add a second operational model without improving the AWS-native serverless path that already fits the product.

---

## Engineering Quality Gates

- GitHub Actions is the only supported deployment path
- AWS access from CI must use GitHub OIDC
- backend coverage gate: **85% minimum**
- critical Python modules target **90%+** coverage
- frontend coverage gate: **80% minimum**
- every merge to `main` deploys staging and runs smoke tests
- production requires protected-environment approval and deploys a commit already proven in staging

---

## Roadmap Overview

```
Phase 0   Foundation and AWS setup            1 week
Phase 1   Free SaaS MVP                       3-5 weeks
Phase 2   Public beta hardening              1-2 weeks
Phase 3   Pro tier and paid AI               2-4 weeks
Phase 4   Marketplace migration path         2-4 weeks
Phase 5   Scale and enterprise               after traction
```

Target: public free SaaS beta as soon as Phase 2 is complete.

---

## Phase 0: Foundation

**Goal**: make the repo deployable and verify the temporary domain.

### Work

- initialize CDK and repo structure
- configure CI for lint, test, synth, and deploy
- configure GitHub OIDC roles for staging and production
- verify `victorymail.dev` in SES
- create VPC, DynamoDB, S3, Redis, SES, and API skeleton stacks
- create basic frontend app shell for console
- create shared Lambda packaging and local tooling
- create the initial pytest, Vitest, Playwright, and CDK test harnesses

### Exit Criteria

- infrastructure can deploy to a dev environment
- SES inbound and outbound are configured for `victorymail.dev`
- API skeleton and console skeleton are reachable

---

## Phase 1: Free SaaS MVP

**Goal**: ship the minimum product a real user can sign up for and use.

### Workstream A: Accounts and auth

- Cognito user pool
- email/password signup and login
- account verification
- user-to-organization mapping
- API key creation during onboarding

### Workstream B: Core email platform

- org, inbox, message, thread, domain, and key models in DynamoDB
- send pipeline through SES
- inbound pipeline through SES -> S3 -> Lambda
- message/thread retrieval APIs
- attachments upload/download
- Redis-based auth cache and rate limiting

### Workstream C: Launch differentiators

- self-service custom domains
- webhook registration and delivery
- `wait` endpoint
- `otp` endpoint
- MCP server

### Workstream D: Launch usability

- developer console for signup, keys, inboxes, domains, usage
- OpenAPI spec
- Python SDK
- Node SDK
- quickstart docs

### Workstream E: Release readiness

- API contract tests against OpenAPI
- integration tests for inbound, outbound, webhook, and domain verification flows
- frontend unit tests for onboarding and core console screens
- Playwright smoke tests for signup, inbox creation, and domain onboarding
- staging deployment and smoke workflow in GitHub Actions

### MVP Exit Criteria

- a new user can sign up without AWS Marketplace
- a free user can create inboxes and send/receive mail
- a free user can add at least one custom domain
- webhook and wait/OTP flows work end to end
- MCP server can create an inbox and retrieve email

---

## Phase 2: Public Beta Hardening

**Goal**: make the free SaaS product stable enough for external usage.

### Work

- load test send/receive and webhook paths
- tighten alarms and dashboards
- add abuse detection and quota enforcement
- add retention jobs for free-tier cleanup
- improve onboarding and quickstart docs
- fix staging issues found during beta onboarding

### Exit Criteria

- public beta users can onboard without operator help
- free tier cost ceiling is visible in dashboards
- no obvious operational blockers remain
- staging deploys are boring and repeatable

---

## Phase 3: Pro Tier and Paid AI

**Goal**: add the smallest paid layer needed to monetize expensive usage.

### Work

- Stripe billing for a single `Pro` plan
- plan-aware quotas for inboxes, domains, and throughput
- AI feature gating:
  - semantic search
  - categorization
  - extraction
- Bedrock/OpenSearch cost metering per org
- upgrade flow from free to Pro
- billing portal and subscription lifecycle handling
- regression coverage for billing, entitlement, and paid AI gating

### Important Principle

Do not introduce additional self-serve tiers before there is clear demand.

At this stage the commercial model is:

- `Free`
- `Pro`
- everything above Pro goes to Marketplace

### Exit Criteria

- free users can upgrade to Pro
- Pro users can access AI features
- AI cost and quota enforcement are production-ready

---

## Phase 4: Marketplace Migration Path

**Goal**: support customers who outgrow Pro or require AWS procurement.

### Work

- finalize Marketplace dimensions and contract structure
- implement fulfillment flow with `ResolveCustomer`
- store `CustomerAWSAccountId` and `LicenseArn`
- entitlement sync and caching
- hourly `BatchMeterUsage`
- SaaS-to-Marketplace migration flow
- private offers before public listing

### Current Marketplace Rules

- use Marketplace after Pro, not before launch
- do not depend on automatic free-trial conversion
- do not publish until dimensions are frozen
- keep migration low-friction: same org, same inboxes, same domains, same API keys where possible

### Exit Criteria

- an existing Pro customer can migrate to Marketplace
- private offers are operational
- metering has reconciliation and retry coverage

---

## Phase 5: Scale and Enterprise

**Goal**: build only what demand justifies.

### Candidate Items

- IMAP/SMTP
- multi-region deployment
- dedicated IP pools
- SSO/SAML
- audit logs
- compliance packaging
- dedicated infrastructure options
- self-hosting

These are explicitly not on the critical launch path.

---

## Suggested Execution Order

1. CDK/bootstrap/domain verification
2. auth and organization model
3. send and receive pipelines
4. messages, threads, attachments
5. webhooks
6. custom domains
7. wait and OTP
8. MCP server
9. console and SDKs
10. public beta
11. Pro billing
12. paid AI
13. Marketplace migration

---

## Launch Risks

### 1. Free tier abuse

Mitigation:

- hard quotas
- send throttles
- domain verification before custom-domain send/receive
- disposable account detection

### 2. Deliverability damage from bad users

Mitigation:

- per-org throttles
- suppression handling
- bounce/complaint monitoring
- fast suspension path

### 3. Launch scope creep

Mitigation:

- no IMAP/SMTP before beta
- no Business/Scale SaaS tiers before demand
- no Marketplace blocking launch

### 4. AI costs expanding before monetization

Mitigation:

- AI features remain off on free
- Pro gating before Bedrock rollout
- per-org AI accounting before public enablement

---

## Success Metrics

### Launch Metrics

- time to first inbox: under 5 minutes from signup
- time to first sent email: under 10 minutes from signup
- free user custom-domain success rate: above 80 percent after DNS setup begins
- public beta onboarding without human intervention

### Business Metrics

- external beta users actively sending and receiving mail
- at least a few users hitting free-tier ceilings
- clear demand signal for Pro before Marketplace buildout

### Operational Metrics

- send/receive flows stable under load
- webhook success rate healthy
- free-tier cost per active org bounded

---

## Deferred Decisions

These stay open until there is usage data:

- exact Free and Pro pricing
- exact free and Pro quota levels
- whether Pro includes bundled AI credits or AI is separately metered
- exact Marketplace public tier names
- timing for public `freemail.dev` cutover
