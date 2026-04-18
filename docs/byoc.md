# BYOC — Run FreeMail in Your Own AWS Account

**Status:** Design complete, implementation in progress. Expected GA: Q3 2026.

BYOC (Bring Your Own Cloud) lets you deploy the entire FreeMail stack into your own AWS account and pay a flat monthly license fee via AWS Marketplace. Your email data never leaves your account. You continue to pay AWS directly for the underlying infrastructure.

Designed for:

- **Regulated industries** — healthcare, banking, defense, insurance
- **Data-sovereign deployments** — EU-only, UK-only, APAC-only requirements
- **Large AWS enterprises** — burn down existing EDP commitments via Marketplace
- **Air-gapped environments** — private VPCs with no egress to third-party SaaS

BYOC sits alongside (not instead of) the hosted Enterprise tier. Hosted Enterprise is for customers who want us to operate the platform. BYOC is for customers who cannot let email data leave their account.

---

## How It Works

You install a thin public CDK package (`@freemail/byoc-cdk`) into your own CDK app. That package provisions the full FreeMail stack — API Gateway, Lambdas, DynamoDB, S3, SES, SQS — into your account using **pre-built Lambda container images** that we publish to Amazon ECR Public at `public.ecr.aws/freemail/*`.

```typescript
import * as cdk from "aws-cdk-lib";
import { FreemailByocStack } from "@freemail/byoc-cdk";

const app = new cdk.App();

new FreemailByocStack(app, "FreemailByoc", {
  env: { account: "123456789012", region: "us-east-1" },
  licenseKey: process.env.FREEMAIL_LICENSE_KEY!,
  version: "1.2.3",
  domains: ["mycorp.com"],
  stage: "prod",
});
```

You never see FreeMail's source code. The Lambdas inside the container images are compiled Python with stripped metadata — you inspect and audit them the same way you would any third-party image.

## License Validation

Every Lambda container performs a license check at **cold start**:

1. Reads the `LICENSE_KEY` environment variable set by the CDK stack.
2. Calls `POST https://license.victorymail.dev/v1/verify` with the license key, AWS account ID, region, and container version.
3. Caches the response in `/tmp` for one hour.
4. If invalid, every API request returns `503 Service Unavailable` with a `X-FreeMail-License: invalid` header.

A 24-hour grace period covers transient network failures. If your license expires or is canceled, the platform stops serving requests within 24 hours.

## Update Path

BYOC supports two update modes:

**Manual updates.** Bump the `version` prop in your CDK stack and run `cdk deploy`. New container images are pulled, rolling deploy across all Lambda functions. Zero downtime. You control timing.

**Automatic updates.** Opt in with `updateChannel: "stable"` (or `"canary"`, `"beta"`). A small `freemail-updater` Lambda in your stack runs daily via EventBridge, checks the latest image tag in ECR, and redeploys if newer. We recommend automatic updates for BYOC Starter; Pro and Enterprise customers typically want explicit version control.

Major version bumps (e.g. `1.x` → `2.x`) require explicit pinning — no auto-update across breaking changes. We publish a migration guide for every major version.

## Pricing

| Tier | Price | Included |
|---|---|---|
| **BYOC Trial** | Free, 30 days | Full Starter features via CloudFormation Quick Launch |
| **BYOC Starter** | $99/mo | 1M messages/mo, unlimited inboxes, 1 domain, email support (48h) |
| **BYOC Pro** | $499/mo | Unlimited messages, unlimited domains, priority support (24h), SOC 2 deployment help |
| **BYOC Enterprise** | From $2,500/mo | Dedicated Slack, quarterly reviews, named CSM, custom regions, EU sovereign |

All tiers bill through AWS Marketplace. You continue to pay AWS directly for the infrastructure. At 1M messages/month your AWS cost is roughly $150 (mostly SES); the BYOC Starter license fee represents a ~2× markup on that infrastructure cost.

## What's Provisioned in Your Account

- **API Gateway** — REST API with Lambda integrations
- **Lambda functions** (as container images) — `inbound_processor`, `outbound_worker`, `messages`, `inboxes`, `threads`, `drafts`, `domains`, `webhooks`, `search`, `ai`, `metrics`, `signup`, `billing`, `authorizer`, `webhook_worker`
- **DynamoDB** — single-table design with 6 GSIs
- **S3 buckets** — raw email, attachments, body storage
- **SQS FIFO queues** — outbound send, webhook delivery
- **SES** — verified sending identity for your domains, receipt rule set
- **IAM roles** — least-privilege Lambda execution roles
- **CloudWatch** — log groups and alarms
- **Route53** (optional) — if you manage your domain there

Everything is defined in CDK constructs you can read and audit. The CDK package is open source; the Lambda images are compiled closed source.

## Getting Started

1. **Subscribe** via AWS Marketplace at `https://aws.amazon.com/marketplace/pp/prodview-freemail-byoc` (coming soon).
2. **Receive your license key** via AWS SNS notification after the subscription becomes active.
3. **Install the CDK package:** `npm install @freemail/byoc-cdk`.
4. **Add a stack** to your CDK app (see example above).
5. **Deploy:** `cdk deploy FreemailByoc` with `FREEMAIL_LICENSE_KEY` set.
6. **Verify:** `curl https://your-api-id.execute-api.us-east-1.amazonaws.com/v1/health`.

## FAQ

**Does our SOC 2 cover a BYOC deployment?**
No. Our SOC 2 report covers our hosted platform. A BYOC deployment runs in your account; your own controls apply. We provide a BYOC Deployment Hardening Guide that maps our controls to CIS benchmarks so you can operationalize equivalent controls. BYOC Pro and Enterprise tiers include help with this.

**Can we inspect the Lambda source code?**
The container images are compiled Python with stripped metadata. You can inspect what they do via CloudWatch logs, IAM boundaries, and by reading the open-source CDK package that wires them together. Enterprise customers can request a source escrow agreement via legal.

**What happens if we cancel our subscription?**
The license API stops returning valid responses for your key. Within 24 hours (the grace window), every Lambda starts returning 503 on cold start. The infrastructure stays in your account — you can delete it via `cdk destroy`.

**Can we run BYOC in multiple regions?**
Starter and Pro run in a single region. Multi-region with DynamoDB Global Tables is an Enterprise feature.

**Does BYOC include AI features (categorize, extract, summarize)?**
Yes, via Amazon Bedrock in the region where Bedrock is available. If your chosen region does not have Bedrock Claude Haiku, the Lambdas fall back to cross-region invocation in `us-east-1` with a warning in CloudWatch.

**Can we white-label the API (remove FreeMail branding)?**
Not in the standard product. Enterprise customers can request a custom build with their own brand — 2-week lead time, $25,000 NRE fee.

**What about data residency for EU customers?**
Deploy the stack in `eu-central-1` (Frankfurt) or `eu-west-1` (Ireland). All customer data stays in-region. BYOC Enterprise can provision in any AWS region that supports SES and Bedrock.

**Do we still get product updates?**
Yes. New versions are published to ECR continuously. You opt into manual or automatic updates. BYOC Pro gets early access to canary builds.

---

For questions or to request early access, contact `sales@victorymail.dev`.
