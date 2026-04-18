# BYOC Implementation Plan

**Status:** Design complete. This doc is the concrete execution plan that turns `docs/byoc.md` into a shipped product. 4 weeks to first customer, 6 weeks to AWS Marketplace listing live.

Read `docs/byoc.md` first for the customer-facing shape. This document is for the engineer implementing it.

---

## Week 1: Containerize the Lambdas

**Goal**: Every handler in `lambdas/` ships as a tagged OCI image on Amazon ECR Public instead of a zip asset.

### Tasks

1. **Add a multi-stage Dockerfile per handler** that:
   - Builds off `public.ecr.aws/lambda/python:3.12`
   - Copies the handler directory + `shared/` + pinned third-party deps
   - Runs `compileall` to strip `.py` and ship only `.pyc`
   - Sets `CMD ["handler.handler"]`

2. **Create one ECR Public repo per handler** (17 total):
   ```
   public.ecr.aws/freemail/inboxes:1.0.0
   public.ecr.aws/freemail/messages:1.0.0
   public.ecr.aws/freemail/outbound_worker:1.0.0
   public.ecr.aws/freemail/inbound_processor:1.0.0
   public.ecr.aws/freemail/domains:1.0.0
   public.ecr.aws/freemail/authorizer:1.0.0
   public.ecr.aws/freemail/webhooks:1.0.0
   public.ecr.aws/freemail/webhook_worker:1.0.0
   public.ecr.aws/freemail/billing:1.0.0
   public.ecr.aws/freemail/search:1.0.0
   public.ecr.aws/freemail/ai:1.0.0
   public.ecr.aws/freemail/metrics:1.0.0
   public.ecr.aws/freemail/vault:1.0.0
   public.ecr.aws/freemail/personas:1.0.0
   public.ecr.aws/freemail/push:1.0.0
   public.ecr.aws/freemail/sms:1.0.0
   public.ecr.aws/freemail/sms_processor:1.0.0
   ```

3. **Add a GitHub Actions job** `byoc-container-build.yml` that:
   - Triggers on a tag matching `byoc-v*`
   - Builds + pushes all 17 images in parallel
   - Updates a `manifest.json` in a public S3 bucket with the tag → image digest map

4. **Add `freemail_license.py`** to the shared layer:
   - Module-level cold-start function that reads `LICENSE_KEY` env var
   - HTTPS POST to `https://license.victorymail.dev/v1/verify` with `{license_key, account_id, region, version, service}`
   - 1-hour cache in `/tmp/.license_cache.json`
   - 24-hour grace period on network failure using cached response
   - If invalid: every handler's entry-point wraps itself and returns `503 X-FreeMail-License: invalid`

**Verification**: After Week 1, `docker pull public.ecr.aws/freemail/inboxes:1.0.0` should work from any AWS account, and invoking the handler with no license key should produce a 503.

---

## Week 2: License Service + CDK Package

### Tasks

1. **Add a `license` Lambda** to the existing FreeMail hosted stack (new `lambdas/license/handler.py`), exposing:
   - `POST /v1/verify` → returns `{valid, expires_at, tier, pricing_mode, last_checked}`
   - `GET /v1/licenses` (admin only) → lists active BYOC licenses
   - Backed by a `LICENSE#{key_id}` partition on the existing victorymail DynamoDB table.

2. **Add a `license.victorymail.dev` custom domain** pointing at the main API Gateway with a new `/license/*` resource tree.

3. **Create the `@freemail/byoc-cdk` npm package** as a new directory `byoc-cdk/` at the repo root:
   ```
   byoc-cdk/
     package.json               ("name": "@freemail/byoc-cdk", "private": true for now)
     tsconfig.json
     src/
       index.ts                 (exports FreemailByocStack)
       freemail-byoc-stack.ts   (the CDK L2 construct)
       license-check.ts         (helper for cold-start IAM)
     README.md                  (customer-facing usage)
   ```
   The `FreemailByocStack` construct:
   - Accepts `licenseKey`, `version`, `domains`, `stage`, `updateChannel`
   - Provisions: DynamoDB, S3 buckets, SQS FIFO queues, Lambda functions (container-backed, pinned to `public.ecr.aws/freemail/*:${version}`), API Gateway, SES verified identities, Cognito user pool
   - Wires environment variables for every handler
   - Outputs the API Gateway URL

4. **Publish the package to `npm` as private (`publishConfig.access: "restricted"`)** while we iterate. When ready for GA, flip to `access: "public"`.

**Verification**: A fresh AWS account with `npm install @freemail/byoc-cdk` + a 30-line CDK app should produce a deployed FreeMail stack.

---

## Week 3: Marketplace Listing + Update Path

### Tasks

1. **Register as an AWS Marketplace seller** at Marketplace Management Portal. Takes ~1 week for AWS to approve tax forms + bank details.

2. **Create a SaaS Contract listing**:
   - Product title: "FreeMail — Identity & Communications Layer for AI Agents (BYOC)"
   - Tiers: BYOC Trial (30-day free), BYOC Starter ($99/mo), BYOC Pro ($499/mo), BYOC Enterprise (Private Offer, $2,500+/mo)
   - Fulfillment URL: `https://console.victorymail.dev/byoc/fulfillment?token={x-amzn-marketplace-token}` — this is where we collect the customer's AWS account ID and issue a license key
   - SNS topic for `aws-marketplace:saas-contract` events to trigger license lifecycle

3. **Create a CloudFormation Quick Launch listing** as the secondary path:
   - Single-click "Launch in my AWS account" that deploys a minimal trial stack
   - Expires after 30 days unless upgraded to a SaaS Contract subscription
   - Uses the same `@freemail/byoc-cdk` constructs internally

4. **Build the auto-updater Lambda**:
   - EventBridge scheduled every 24h
   - Checks `public.ecr.aws/freemail/manifest.json` for the latest tag in the channel
   - If newer than currently deployed, calls `lambda:UpdateFunctionCode` with the new image URI
   - Emits a CloudWatch metric + SNS notification per successful update

**Verification**: A test customer account can discover us via Marketplace, subscribe to the $99 Starter tier, receive a license key via email, deploy our CDK stack, and have a working FreeMail instance — all without us touching anything.

---

## Week 4: Hardening + First Customer

### Tasks

1. **Hardening checklist**:
   - License service: 99.9% availability target, multi-AZ, cached responses
   - Container images: base image security scan (ECR scanning)
   - Cold-start cost: measure and tune memory allocation per handler
   - Version skew: ensure `freemail_license.py` runs the same code path across old/new images
   - Error budget: if the license service goes down, existing deployments get a 24h grace period

2. **BYOC onboarding docs** at `docs/byoc.md`:
   - Sign up flow diagram
   - CDK quickstart with working example
   - Upgrade + downgrade flow
   - Troubleshooting common issues (license expired, version pin, etc.)

3. **First customer**: Find a friendly design partner (someone we know, ideally a regulated-industry buyer) and walk them through a real deployment. Their feedback drives Week 5-6 fixes.

---

## Weeks 5-6: Polish + Public GA

### Tasks

1. **Marketplace review** (AWS takes 1-2 weeks after submission)
2. **Documentation** — expand troubleshooting, add migration/upgrade guides, publish a reference architecture diagram
3. **Support tooling** — internal runbook for a customer whose license expired / CDK drift / version mismatch / SES verification stuck
4. **Metering (feature-flagged)** — even in flat-fee mode, emit usage counters so we can enable CCP later with one config flip
5. **Announce GA** — blog post, AWS Marketplace listing goes public, SDK clients pick up `@freemail/byoc-cdk` in their docs

---

## Dependencies We Can't Control

- **AWS Marketplace seller registration**: 1 week turnaround after we submit tax forms
- **Marketplace listing review**: 1-2 weeks of back-and-forth with AWS reviewers
- **ECR Public rate limits**: anonymous pulls are rate-limited; we'll need to recommend customers use the ECR pull-through cache in their own account for production deploys

## Decisions Still Needed (Deferred Until Week 1 Starts)

1. **Signed container images?** Sigstore/cosign would prove image provenance. Worth ~1 day of extra wiring if enterprise customers ask.
2. **Multi-region trial deploys?** CloudFormation Quick Launch can only deploy into one region at a time. If we want `eu-central-1` trial deploys we need a second Marketplace listing.
3. **Customer success tooling**: do we offer "we'll deploy it for you" as a paid onboarding add-on, or fully self-serve?
4. **Private offer vs. public pricing for Enterprise**: default to Private Offer per our plan, but evaluate whether a "$2,500 public" tier would drive Marketplace discoverability.
5. **Container signing key custody**: if we sign with cosign, where does the private key live? KMS preferred.

---

## What We Are NOT Building in BYOC v1

- Multi-region replication (Enterprise-tier feature, Week 8+)
- EU sovereign / data residency (Enterprise-tier, Week 8+)
- Custom domain federation (one domain per BYOC stack)
- Embedded AI models (still uses Bedrock)
- Source escrow (Enterprise legal flow only)
- White-labeling (Enterprise NRE $25k)
- Kubernetes / ECS deployment targets (Lambda only)
- Non-AWS cloud support

See `docs/byoc.md` for the customer-facing scope.
