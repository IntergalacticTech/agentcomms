# AgentComms Phase 2: Channel Ports + Org-Scoped Features — Implementation Plan

> **Fidelity note:** This is a B-fidelity plan (per conversation with user 2026-04-17). It lists file layouts, key code skeletons, and commit boundaries, but does not expand every TDD step verbatim like Phase 1 does. Follow the same TDD rhythm as Phase 1 (fail → red → implement → green → commit). Expand tasks to full fidelity before execution if desired.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Spec:** `docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md`
**Predecessor:** Phase 1 complete and merged (tag `phase1-complete`).

**Goal:** Port the already-partially-built work in `lambdas/{sms,sms_processor,vault,personas,push}/` into the new `adapters/` + `core/api/` structure, and add the org-scoped features that Phase 1 deliberately deferred (Domains, AI, Vault, Personas). At Phase 2 exit, the hub supports 3 channels (email, SMS, push) and all the non-channel agent primitives.

**Architecture:** SMS becomes an `adapters/sms/` adapter on the Phase 1 `ChannelAdapter` contract (not a set of standalone Lambdas). Push becomes `adapters/push/`. Vault and Personas move to `core/api/{vault,personas}/` as org-scoped features (not channels). Domains moves to `core/api/domains/` as an org-scoped feature (tied to the email adapter for DKIM verification).

**Tech Stack:** Same as Phase 1 + AWS End User Messaging v2 SDK + Bedrock runtime SDK + KMS for vault encryption.

---

## File structure (created/moved in Phase 2)

```
adapters/sms/
├── manifest.toml
├── adapter.py                # SmsAdapter(ChannelAdapter) using AWS End User Messaging v2
├── normalize.py              # SNS inbound SMS → ParsedSms → UnifiedMessage
├── ingest.py                 # Lambda: SNS → adapter.ingest → repo
├── outbound.py               # Lambda: SQS → adapter.send
├── stack.py                  # (TypeScript companion: cdk/lib/adapters/sms-adapter-stack.ts)
└── tests/

adapters/push/
├── manifest.toml
├── adapter.py                # PushAdapter(ChannelAdapter) using SNS Mobile Push
├── normalize.py              # delivery receipts → UnifiedMessage updates
├── outbound.py               # Lambda: SQS → adapter.send
├── stack.py                  # cdk/lib/adapters/push-adapter-stack.ts
└── tests/

core/api/
├── domains_handler.py        # /v1/domains/* — org-scoped, SES identity lifecycle
├── vault_handler.py          # /v1/vault/* — KMS-wrapped secrets, TOTP code generation
├── personas_handler.py       # /v1/personas/* — identity profiles, linkable to agents
└── ai_handler.py             # /v1/agents/{id}/ai/* — Bedrock wrappers

core/ai/                      # Bedrock SDK wrappers
├── __init__.py
├── bedrock_client.py         # thin boto3 wrapper + retry/backoff
├── categorize.py             # classification against per-inbox label taxonomy
├── extract.py                # structured extraction via tool_use
├── summarize.py
└── search.py                 # keyword search over messages (semantic deferred to Phase 3)

core/vault/                   # vault encryption helpers
├── __init__.py
├── kms.py                    # KMS encrypt/decrypt for secret blobs
└── totp.py                   # RFC 6238 TOTP code generator

cdk/lib/adapters/
├── sms-adapter-stack.ts
└── push-adapter-stack.ts

cdk/lib/stacks/
└── agentcomms-ai-stack.ts    # optional: IAM grants for Bedrock models; one per env

lambdas/{sms,sms_processor,vault,personas,push}/    # REMOVED at end of Phase 2
```

---

## Task 1: Port SMS to `adapters/sms/`

**Pre-read:** `lambdas/sms/handler.py`, `lambdas/sms_processor/handler.py`, `lambdas/shared/rate_limit.py`. Understand the existing AWS End User Messaging v2 wiring.

**Deliverables:**
- `adapters/sms/adapter.py` implementing `ChannelAdapter`:
  - `provision(agent, config={"country":"US"})`: calls `pinpoint-sms-voice-v2` `RequestPhoneNumber` to get a 10DLC long code. Returns `channel_id` + `{phone_e164, ten_dlc_status}`. Initial status = `provisioning` until the brand/campaign registration path completes asynchronously.
  - `teardown(channel)`: `ReleasePhoneNumber`.
  - `health_check(channel)`: `GetPhoneNumber` and check it's still owned by the account.
  - `ingest(payload)`: parses the SNS inbound-SMS JSON; looks up channel by `ADDR#sms#{destination_phone_e164}` via GSI2; builds `UnifiedMessage(channel=sms, is_dm=True, channel_native={message_segments, carrier_id})`.
  - `send(channel, message)`: `SendTextMessage` via End User Messaging. Handles segmentation implicitly.
- `adapters/sms/manifest.toml`:
  ```toml
  [adapter]
  channel = "sms"
  class = "adapters.sms.adapter:SmsAdapter"
  modes = ["provision"]
  cdk_stack = "SmsAdapterStack"
  min_hub_version = "0.1"

  [ssm_secrets]
  end_user_messaging_arn = "PLAIN"
  ten_dlc_brand_id = "PLAIN"
  ten_dlc_campaign_id = "PLAIN"
  ```
- `adapters/sms/ingest.py` + `outbound.py` — structurally identical to Phase 1's email handlers; swap EmailAdapter for SmsAdapter.
- `cdk/lib/adapters/sms-adapter-stack.ts` — creates SNS topic for inbound SMS, SQS queue for outbound, two Lambdas, IAM grants for `sms-voice:*`.
- Tests under `adapters/sms/tests/`: normalize roundtrip from recorded SNS fixture, provision+teardown (mocked boto3), send (mocked).

**Commit:** `feat(phase2): port SMS into adapters/sms/ with AWS End User Messaging v2`

**Retire:** `lambdas/sms/` and `lambdas/sms_processor/` — deleted in Task 7 after all Phase 2 tests pass.

---

## Task 2: Port Push to `adapters/push/`

**Pre-read:** `lambdas/push/handler.py`.

**Deliverables:**
- `adapters/push/adapter.py`:
  - `provision(agent, config={})`: creates an SNS Platform Application per agent (or reuses a shared one — choice documented in adapter docstring). Returns `channel_id` + `{platform_application_arns: {apns, fcm}}`.
  - Push is **outbound-primary**. `ingest()` is used only for delivery receipts (Mobile Push → SNS → Lambda); returns `UnifiedMessage(direction=outbound, status=delivered|failed)` — an update, not a new message. The core persistence layer handles updates by matching on `external_id`.
  - `send(channel, message)`: needs `to` = target device endpoint ARN (passed in `message.to` as a dict or string). Publishes to the endpoint ARN.
  - Additional helper API route (outside the generic `ChannelAdapter`): `POST /v1/agents/{id}/push/devices` — register a device token → SNS CreatePlatformEndpoint → store endpoint ARN as a "device" sub-item under the channel. This is wired in Task 6 as a special native sub-surface.
- Manifest + ingest/outbound Lambdas + CDK fragment same shape as Email/SMS.
- Tests: device registration, outbound publish, delivery-receipt update.

**Commit:** `feat(phase2): port Push into adapters/push/ with SNS Mobile Push (APNs + FCM)`

**Retire:** `lambdas/push/` — deleted in Task 7.

---

## Task 3: Port Vault to `core/api/vault_handler.py` + `core/vault/`

**Pre-read:** `lambdas/vault/handler.py`, `lambdas/shared/models.py` (vault item shape).

**Key design:** Vault is **org-scoped**, not channel-scoped. Entries can be tagged with `persona_id` (Task 4) and `agent_id` for filtering, but they're not channels.

**Deliverables:**
- `core/vault/kms.py` — thin KMS encrypt/decrypt wrapper. Per-org Customer Managed Key (CMK) if present, else account-default key.
- `core/vault/totp.py` — RFC 6238 TOTP code generation. Input: base32-encoded seed. Output: 6-digit code for the current 30s window. No seed ever leaves the vault item; only the generated code does.
- `core/api/vault_handler.py` — routes:
  - `POST /v1/vault` → `{type: "totp"|"password"|"secret", label, seed?, value?, tags?}` → generate `vault_id`, KMS-encrypt, write to DynamoDB `PK=ORG#{org_id}` `SK=VLT#{vault_id}`.
  - `GET /v1/vault` → list (metadata only, no decrypted payload).
  - `GET /v1/vault/{id}` → return metadata + decrypted value (requires org-level API key).
  - `GET /v1/vault/{id}/totp` → return current 6-digit code. Does NOT leak the seed.
  - `DELETE /v1/vault/{id}`.
  - `GET /v1/vault?label=...` or `?tag=agent_id:agt_X` → filtered list.
- DynamoDB model: `VaultItem` in `core/data/models.py` with fields `vault_id, org_id, type, label, encrypted_blob, kms_key_id, tags, created_at`.
- Tests in `tests/api/test_vault.py`: CRUD roundtrip, TOTP generation matches `pyotp` reference, KMS encryption intercepted by moto.

**Commit:** `feat(phase2): port Vault — TOTP + secret storage, KMS-wrapped, org-scoped`

**Retire:** `lambdas/vault/` — deleted in Task 7.

---

## Task 4: Port Personas to `core/api/personas_handler.py`

**Pre-read:** `lambdas/personas/handler.py`, `sdks/python/freemail/resources/personas.py`.

**Key design:** Personas are **org-scoped identity profiles** (name, address, DOB, phone, email, free-form metadata). Agents reference them. Bedrock-backed generation ("give me a plausible 34-y-o software engineer in Denver") is optional.

**Deliverables:**
- DynamoDB model: `Persona` in `core/data/models.py` — `persona_id, org_id, name, address?, dob?, phone?, email?, metadata`. Stored at `PK=ORG#{org_id} SK=PER#{persona_id}`.
- Routes:
  - `POST /v1/personas` — create, optional `generate: true` triggers Bedrock (Haiku) to fill missing fields.
  - `GET /v1/personas` — list with pagination.
  - `GET /v1/personas/{id}`.
  - `PATCH /v1/personas/{id}`.
  - `DELETE /v1/personas/{id}`.
  - `POST /v1/agents/{agent_id}/personas` — associate a persona with an agent (adds `persona_id` to Agent.metadata).
- Tests: CRUD roundtrip, generate mocks Bedrock and asserts the prompt shape.

**Commit:** `feat(phase2): port Personas — org-scoped identity profiles linkable to agents`

**Retire:** `lambdas/personas/` — deleted in Task 7.

---

## Task 5: Domains CRUD (`core/api/domains_handler.py`)

**Pre-read:** `lambdas/domains/handler.py` (current FreeMail implementation), `docs/custom-domains.md`.

**Key design:** Domains are **org-scoped** and tightly coupled to the email adapter (SES identity lifecycle). The Phase 1 email adapter's `provision()` assumed a domain was available; this handler is how it gets registered.

**Deliverables:**
- DynamoDB: existing `Domain` model (Phase 1 placeholder; expand if needed).
- Routes under `/v1/domains`:
  - `POST /v1/domains` — register a custom domain. Calls SES `CreateEmailIdentity` with Easy DKIM 2048-bit. Returns DNS records for the customer to publish (3 DKIM CNAMEs, 1 SPF TXT, 1 MX, 1 DMARC TXT).
  - `GET /v1/domains` — list.
  - `GET /v1/domains/{id}` — includes verification status (`pending_dns` | `pending_dkim` | `verified` | `failed`).
  - `POST /v1/domains/{id}/verify` — triggers an immediate verification poll (vs. the scheduled 5-min poll).
  - `GET /v1/domains/{id}/zone-file` — returns DNS records in bind/zone-file format (preserves current FreeMail behavior).
  - `DELETE /v1/domains/{id}` — calls SES `DeleteEmailIdentity`. Blocked if any agent has an email channel on this domain (409).
- Scheduled Lambda: `core/api/domains_poller.py` — runs every 5 min, polls `GetEmailIdentity` for pending domains, updates status, fires `domain.verified` event to Kinesis.
- Tests: create roundtrip, verification polling, zone-file output format, delete blocked by active channels.

**Commit:** `feat(phase2): Domains CRUD + async DKIM verification polling`

---

## Task 6: AI features (`core/api/ai_handler.py` + `core/ai/`)

**Pre-read:** `lambdas/ai/handler.py`, `docs/ai-features.md` (if present).

**Key design:** AI is **optional on self-host** (deployer provides Bedrock access); **metered on hosted**. The Phase 1 spec promised 4 operations: categorize, extract, summarize, search.

**Deliverables:**
- `core/ai/bedrock_client.py` — wraps boto3 `bedrock-runtime.invoke_model` with retry + cost logging. Honors env var `AGENTCOMMS_BEDROCK_REGION` (defaults to us-east-1).
- `core/ai/categorize.py` — takes a message, a label taxonomy, returns `{label, confidence}`. Model routing: Haiku by default; Sonnet if `config.complex=true`.
- `core/ai/extract.py` — takes a message + JSON schema, uses tool_use mode, returns validated JSON.
- `core/ai/summarize.py` — short and long summary variants.
- `core/ai/search.py` — Phase 2 ships **keyword search only** (DynamoDB scan + filter on body_text). Semantic search is deferred to Phase 3 (OpenSearch Serverless).
- Routes:
  - `POST /v1/agents/{id}/ai/categorize { message_id, labels? }`
  - `POST /v1/agents/{id}/ai/extract   { message_id, schema }`
  - `POST /v1/agents/{id}/ai/summarize { message_id | thread_key, length?: short|long }`
  - `POST /v1/agents/{id}/ai/search    { query, channel?, limit?, since? }`
- Tests: mock `invoke_model`, assert prompt shape, assert parsing paths for valid/invalid JSON.

**Commit:** `feat(phase2): AI features — categorize/extract/summarize/search via Bedrock`

---

## Task 7: Decommission old `lambdas/*` entries

**Steps:**
1. Confirm all Phase 2 tests pass.
2. Confirm staging CDK deploy succeeds with new adapter stacks, and victorymail stacks are NOT referencing the old lambda directories (the old CDK `api-stack.ts` might).
3. Remove from CDK any references to `lambdas/{sms,sms_processor,vault,personas,push}`.
4. `git rm -r lambdas/{sms,sms_processor,vault,personas,push}`.
5. Run full test suite + CDK synth; fix anything that broke.
6. Commit: `chore(phase2): retire ported lambdas/* (sms, push, vault, personas)`.

---

## Task 8: End-to-end Phase 2 integration test

**File:** `tests/e2e/test_phase2_roundtrip.py`

Exercises:
1. Provision agent with email + sms + push in one `POST /v1/agents` call.
2. Inbound SMS via simulated SNS → appears on unified inbox.
3. Create a persona, associate with agent.
4. Create a TOTP vault entry; fetch the current code; assert it's 6 digits.
5. Register a custom domain → verify stays `pending_dns` until simulated DNS record presence.
6. AI categorize a message → assert label populated.

**Commit:** `test(phase2): E2E roundtrip with email+sms+push+vault+personas+domain+AI`

---

## Phase 2 exit criteria

- [ ] 3 channels live: email, sms, push (Phase 1 email + Phase 2 SMS + push)
- [ ] Vault, Personas, Domains, AI routes respond per spec
- [ ] `lambdas/{sms,sms_processor,vault,personas,push}/` removed from repo
- [ ] All tests pass; CDK synth clean
- [ ] E2E test in Task 8 passes
- [ ] Phase 1 endpoints remain unchanged (no regressions)

---

*End Phase 2 plan. Estimated calendar: 2 weeks; most work is mechanical porting + one round-trip test per channel.*
