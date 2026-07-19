# Platform Review

Status: review based on the repository state on 2026-06-17.

## Executive Summary

AgentComms has a strong product direction: a unified communications inbox for agents, with channel adapters, SDKs, a console, and infrastructure as code. The best technical asset is the newer AgentComms core: `core/data/repo.py` keeps DynamoDB access behind a repository, `core/data/models.py` defines normalized cross-channel entities, and the adapter contract makes channels independently replaceable.

The platform is not yet cleanly self-hostable or cloud-portable. The repo currently contains two product generations: older FreeMail/VictoryMail stacks and newer AgentComms stacks. The CDK app deploys both generations into a hard-coded AWS account, and several docs still describe the older hosted FreeMail surface. That makes the current "one command deploy" story risky for external users.

The Azure path is feasible, but it is not just an IaC translation. Azure does not currently provide a generally available SES-equivalent inbound/catch-all email service through Azure Communication Services Email. A feature-complete Azure-native deployment must either use Microsoft 365/Graph mail ingestion, ACS Email inbound private preview if available, or a custom SMTP ingress service on Azure infrastructure.

## High Priority Findings

### 1. Self-hosting deploys are hard-coded to one AWS account

`cdk/bin/app.ts` hard-codes account `732770059798` and `us-east-1` for both the older VictoryMail stacks and the newer AgentComms stacks. The CLI bootstrap path deploys `AgentCommsData`, `AgentCommsEvents`, `AgentCommsApi`, and `AgentCommsAdapters`, but those stacks still resolve to the hard-coded account in the app.

Impact: users following `AGENT.md` may believe they are deploying into their account, while the CDK app is anchored to the maintainer account. This blocks real BYOC and makes Azure parity premature.

Recommendation:

- Replace hard-coded `env` values with `CDK_DEFAULT_ACCOUNT`, `CDK_DEFAULT_REGION`, CLI options, or context.
- Split older VictoryMail stacks from the AgentComms app entrypoint.
- Add a self-host synth test that asserts no production account ID is present in the synthesized template.

### 2. Agent-scoped and channel-scoped API keys are not wired correctly through API Gateway

`core/api/authorizer_lambda.py` passes `event.get("path")` and `event.get("httpMethod")` into `authorize()`, but API Gateway TOKEN authorizers generally provide `authorizationToken` and `methodArn`, not the full request path and method. The CDK stack uses `TokenAuthorizer`, and the tests exercise `authorize()` directly rather than the Lambda authorizer event shape.

Impact: non-org API keys are likely denied for valid requests, or scope enforcement will be incomplete if later moved into handlers inconsistently.

Recommendation:

- Switch to a REQUEST authorizer with path and method identity sources, or parse method/stage/path from `methodArn`.
- Add tests for `authorizer_lambda.lambda_handler()` using realistic API Gateway authorizer events.
- Decide whether path-level scope lives in the authorizer or in handler-level ownership checks, then make it consistent.

### 3. New AgentComms inbound email wiring appears broken

`cdk/lib/adapters/email-adapter-stack.ts` stores SES inbound mail in S3 with `objectKeyPrefix: 'inbound/'`. `adapters/email/ingest.py` fetches the object with `mail.messageId` only, without the `inbound/` prefix.

Impact: inbound email in the newer AgentComms stack will not find raw MIME objects unless SES writes without the prefix or the handler is patched.

Recommendation:

- Set the handler key to `f"inbound/{message_id}"`, or make the prefix configurable.
- Add an integration-style test that builds an SNS SES notification, writes `inbound/{messageId}` to S3, and verifies a message record is persisted.

### 4. Product identity is inconsistent across docs, code, and domains

The root README is AgentComms, while `docs/README.md`, `docs/quickstart.md`, `ARCHITECTURE.md`, old Lambda names, stack names, and domains still refer to FreeMail, VictoryMail, `victorymail.dev`, and `api.victorymail.dev`.

Impact: this weakens public launch readiness, creates support ambiguity, and increases migration risk.

Recommendation:

- Declare AgentComms as the canonical name.
- Move legacy VictoryMail/FreeMail docs into a `docs/legacy/` folder or mark them explicitly as historical.
- Update quickstart, hosted URLs, SDK names, key prefixes, email addresses, and screenshots in one coordinated pass.

### 5. CDK tests perform real Lambda asset bundling

Running `npx jest --runInBand` from `cdk/` passed, but it pulled the SAM Python 3.12 image and installed Python dependencies during unit tests.

Impact: CDK tests are slow, network-dependent, and brittle in CI. They test bundling side effects more than template intent.

Recommendation:

- Add a test mode for CDK constructs that uses stub Lambda assets.
- Keep bundling verification in a separate integration test or CI job.
- Add an `npm test` script in `cdk/package.json`; Jest tests exist but `npm test` currently fails.

## Architecture Assessment

### Strengths

- The normalized `UnifiedMessage` model and adapter contract are the right shape for a multi-channel agent inbox.
- Single-table data access is mostly centralized in `Repo`, which makes testing and future provider adapters easier.
- The stack uses managed services well for the AWS target: Lambda, DynamoDB, S3, SQS/SNS/Kinesis, SES, Cognito, CloudWatch, and Bedrock.
- The CLI emits structured NDJSON, which is good for agent-driven setup and automation.
- Tests cover core models, adapters, API handlers, and CDK templates, even if the local environment needs tightening.

### Risks

- There are two infrastructure generations in the same CDK app.
- Runtime provider calls are spread through adapters and handlers via direct `boto3` usage.
- Several docs describe target state as if it is implemented.
- Security boundaries rely on a mix of authorizer checks and handler ownership checks.
- Some operational features are stated but not yet complete: SES polling, smoke tests, deploy resume, marketplace BYOC, and cloud-neutral setup.

## Azure Native Direction

Azure support should be implemented as a provider port, not a fork. Keep the domain model, API shape, adapter contract, SDKs, and console. Replace the runtime provider layer and IaC:

- AWS CDK becomes Azure Bicep or Azure Developer CLI templates.
- Lambda becomes Azure Functions or Container Apps jobs.
- DynamoDB becomes Cosmos DB for NoSQL.
- S3 becomes Blob Storage.
- SQS/SNS/Kinesis becomes Service Bus, Event Grid, and Event Hubs.
- KMS/SSM/Secrets Manager becomes Key Vault.
- Cognito becomes Microsoft Entra External ID or Azure AD B2C.
- Bedrock/OpenSearch becomes Azure OpenAI plus Azure AI Search.
- SES outbound becomes Azure Communication Services Email.
- SES inbound needs a product decision: Graph mailbox ingestion, ACS private preview, or custom SMTP ingress.

See `docs/azure-native-setup.md` for a concrete setup plan.

## Recommended Roadmap

### Week 1: Make AWS self-hosting honest

- Parameterize CDK account, region, stage, and domains.
- Remove VictoryMail stacks from the AgentComms bootstrap entrypoint.
- Fix the email S3 prefix issue.
- Add realistic authorizer Lambda event tests.
- Add `cdk` and CLI test scripts that work from `npm test`.

### Week 2: Create provider seams

- Introduce provider interfaces for table, blob, queue, event publish, secrets, email send, SMS, push, and AI.
- Move direct `boto3` calls out of API handlers where possible.
- Keep AWS implementations as the first provider.

### Week 3: Azure foundation

- Add `infra/azure/` with Bicep modules for Cosmos DB, Storage, Functions, Service Bus, Event Grid, Key Vault, Application Insights, ACS Email/SMS, Static Web Apps, and API Management.
- Add Azure runtime config and managed identity permissions.
- Build Azure provider implementations behind the same interfaces.

### Week 4: Inbound email decision and prototype

- If ACS inbound private preview is available, wire Event Grid to an Azure Function.
- If not, prototype Microsoft Graph change notifications for a shared mailbox, or a custom SMTP receiver on Azure Container Apps/AKS.
- Keep the AWS SES path as the reference implementation until Azure inbound is proven.

## Verification Performed

- `pytest tests/core/test_authorizer.py tests/api/test_agents.py adapters/email/tests/test_adapter.py -q` failed because `moto` is not installed in the local Python environment.
- `cd cdk && npm test -- --runInBand` failed because `cdk/package.json` has no `test` script.
- `cd cdk && npx jest --runInBand` passed: 5 suites, 21 tests. The run took about 116 seconds because CDK tests bundled Lambda assets through Docker.

