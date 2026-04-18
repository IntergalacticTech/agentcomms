# FreeMail Roadmap

**Last updated:** 2026-04-13

This document lists features that are **designed but not yet shipped**. It's honest about timing — nothing here should be assumed to be callable today. See `docs/api-reference.md` for the current shipped API surface.

---

## Positioning

FreeMail is evolving from "email for AI agents" to **the complete identity and communications layer for AI agents**. The strategic gap: every current competitor owns one slice (email, SMS, OTP vault, or persona) — none bundle them. We intend to.

## Shipped Today

| Feature | Status | Doc |
|---|---|---|
| REST API for inboxes, messages, threads, drafts, attachments | ✅ Live | [api-reference.md](./api-reference.md) |
| Send / receive via SES with DKIM/SPF/DMARC | ✅ Live | [api-reference.md](./api-reference.md#messages) |
| Wait for message / Extract OTP (long-poll) | ✅ Live | [api-reference.md](./api-reference.md#wait--extract-otp) |
| **Platform domain pool** (`victorymail.dev`, `karmascale.net`, `karmascale.org`) | ✅ Live | [quickstart.md](./quickstart.md#pick-a-different-platform-domain) |
| Custom domains (paid tiers) with real SES DKIM tokens | ✅ Live | [custom-domains.md](./custom-domains.md) |
| AI categorize / extract / summarize (Starter+) | ✅ Live | [api-reference.md](./api-reference.md#ai-features) |
| Search, Metrics, Webhooks | ✅ Live | [api-reference.md](./api-reference.md) |
| Python + Node SDKs, MCP server, OpenClaw skill | ✅ Live | [sdks.md](./sdks.md) |
| 4-tier pricing (Free / Starter $5 / Pro $25 / Enterprise) | ✅ Live | [billing.md](./billing.md) |

## Planned — Tier 1 (next 2-3 weeks)

### SMS OTP Receive (via AWS End User Messaging)

- Per-inbox optional phone number on 10DLC long code ($1/mo fixed)
- Inbound SMS → SNS → Lambda → stored in the same single-table design with `channel: "sms"` on message items
- Reuse `/inboxes/{id}/wait` and `/inboxes/{id}/extract-otp` with a `channel` filter
- **Why first:** #1 adjacent agent use case. Every service that registers an agent sends either email *or* SMS, and we own the email half today. Adding SMS makes us the only platform that captures both.
- **Status:** Designed. 10DLC brand registration is the gating path (~1 week).
- **Pricing:** Starter gets 25 SMS OTPs/mo included; Pro gets 500; overage ~$0.008/msg.

### Secret Vault (TOTP + passwords)

- New `/vault` resource: `POST /vault`, `GET /vault/{id}`, `DELETE /vault/{id}`, `GET /vault?label=...`
- KMS-wrapped S3 storage, per-org CMK
- `GET /vault/{id}/totp` returns the current 6-digit code computed server-side from a stored TOTP seed (seed itself is never leaked)
- **Why:** Agents that register for services need to store resulting credentials. 1Password/Bitwarden are human-shaped; Infisical/Doppler are dev-ops-shaped. Nobody offers an agent-first vault API.
- **Status:** Designed. ~1 week of implementation.
- **Pricing:** Starter 25 secrets, Pro 500, Enterprise unlimited.

### Mobile Push Notifications (SNS Mobile Push)

- Per-inbox device registration via `POST /inboxes/{id}/devices`
- Publish via SNS Mobile Push (APNs + FCM)
- **Why:** Essentially free at our scale (1M/mo free tier).
- **Status:** ~1-2 days of implementation.
- **Pricing:** Included on all paid tiers.

## Planned — Tier 2 (1-2 months)

### Persistent Persona / Profile API

- New `/personas` resource scoped to org
- JSON profile: name, address, DOB, phone, email — plus free-form metadata
- Optional Bedrock-backed generation ("give me a plausible 34-year-old software engineer from Denver")
- Link personas to inboxes (one-to-many); inbox inherits persona's email; vault entries can be tagged by persona
- **Why:** Every agent session that touches the same external service needs a consistent "who am I." Today agents regenerate profiles per-run. Nobody offers this.
- **Status:** Designed. ~1 week.

### Two-way SMS (outbound send)

- Builds on SMS OTP receive. Same 10DLC phone number can both receive and send
- `client.sms.send(inbox_id, to, body)` in SDKs
- **Pricing passthrough:** ~$0.00947/msg all-in on 10DLC; Pro includes N/day.

### Voice OTP Fallback

- Outbound TTS call for sites that only deliver codes by voice
- Same v2 End User Messaging API as SMS
- ~$0.013/min; Pro gets 10 calls/mo included.

## Planned — Tier 3 (1+ quarter)

### WhatsApp (via End User Messaging Social)

- Meta WABA onboarding (~2 weeks), template approval (manual, per-template)
- Per-conversation fees set by Meta (~$0.025 US marketing, ~$0.0135 US auth)
- Strategic for international agents in markets where WhatsApp is SMS.
- **Pricing:** Passthrough on Pro; bundled on Enterprise.

### BYOC — Bring Your Own Cloud (via AWS Marketplace)

- Run the full FreeMail stack inside the customer's AWS account
- Source code not visible to the purchaser — SHA-pinned Lambda container images on public ECR (`public.ecr.aws/freemail/*`)
- License key validation at Lambda cold start; 24-hour grace period
- Two offer types on Marketplace: SaaS Contract (monthly license) + CloudFormation Quick Launch (trial deploy)
- **Tiers:** Trial free 30d, Starter $99/mo, Pro $499/mo, Enterprise $2,500+/mo
- **Why:** Compliance-heavy buyers (healthcare, banking, defense, sovereign-data) cannot let email data leave their account. Zero COGS for us; flat license fee via AWS Marketplace billing.
- **Status:** Full design in [byoc.md](./byoc.md). Implementation ~4 weeks for first customer, ~6 weeks for Marketplace-live.

### Advanced Observability (OpenSearch + BI exports)

- Full-text message search beyond the current DynamoDB-scan-backed `/search`
- Message body vector embeddings for "find similar" queries
- Time-series aggregations beyond the current `/metrics/query` (retention, cohort analysis)

## Explicitly NOT on the roadmap

- **Chime SDK Messaging** — wrong tool, it's for building Slack-likes
- **Amazon Connect as the primary surface** — too heavyweight for agent-as-a-service
- **A Laravel/PHP backend** — Python 3.12 Lambdas stay
- **IMAP/SMTP bridges for legacy clients** — not an agent use case
- **Multi-region replication** before BYOC ships — enterprise-tier only

---

For questions or to request a specific capability, open an issue at <https://github.com/IntergalacticTech/freemail/issues>.
