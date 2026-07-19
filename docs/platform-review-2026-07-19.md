# AgentComms Top-Down Review — 2026-07-19

Status: consolidated findings from a 9-agent deep review of `develop` at commit `d860561`.
Supersedes and extends `docs/platform-review.md` (2026-06-17).

Reviewed territories: core, adapters, legacy lambdas, CDK infra, dev surface (CLI/SDKs/MCP),
console+landing, tests/tooling/CI, docs/hygiene, cross-cutting security, whole-system architecture.

---

## Executive summary

The AgentComms core is genuinely well-built: a clean single-table data model, a coherent
`ChannelAdapter` contract, and a repository that keeps DynamoDB access in one place. The Phase 5
cutover is real — the legacy VictoryMail generation is dark (gated behind `deployLegacy=false`) and
there is **no live double-write** between generations.

But the platform is **not safe to hold out as production-ready or self-hostable today.** Three
classes of problem dominate:

1. **A live credential is leaked in the public repo, and tenant isolation has holes.** These are
   exploitable now.
2. **Two headline features don't actually work end-to-end** — the Kinesis event bus has no consumer
   (registered webhooks never fire), and outbound send runs synchronously in the request Lambda with
   no queue/DLQ despite orphaned async infrastructure being provisioned.
3. **The public-facing surface still describes the retired FreeMail product** — nearly all customer
   docs, the console app, and the monitoring config point at `victorymail.dev`.

Credit where due: the prior review's two top findings — hard-coded AWS account and the email S3-prefix
bug — are **fixed** (`cdk/bin/app.ts:25-34`, `adapters/email/ingest.py:56-61`).

---

## P0 — Do these before anything else

### 1. Revoke the leaked live API key and purge it from history
`docs/YOUR_INSTANCE.md` and `docs/TESTING_PLAN.md` (both git-tracked, public repo) contain a live
org-scoped key `ak_live_REDACTED` (the live literal is in git history/the two source docs; org "JWC Personal", full org
access; literal redacted here) alongside the live API base URL and a real agent id. **Anyone who clones the repo owns that
org.** Revoke now, purge from files and git history, rotate the org's vault contents, then move all
internal infra identifiers (account id, REST API ids, Route53 zone, cert/CloudFront/S3 names — see
security report) out of tracked files. Reverse the `docs/PUBLIC_RELEASE.md:22` guidance that
greenlights exposing the account id.

### 2. Close the cross-tenant authorization holes (IDOR)
Four per-agent handlers skip the ownership gate — `repo.get_agent(org_id=caller.org_id, agent_id=…)` —
that every sibling handler enforces. Messages are keyed `PK=AGT#{agent_id}` with no org binding, and
org-scoped keys receive an execute-api policy of `{apiId}/*`, so agent_ids (non-secret ULIDs, one of
which is leaked above) are the only thing standing between tenants.

- `core/api/messages_handler.py:53-162` — read any org's full inbox; POST branch **sends outbound
  mail from the victim's provisioned channel**. (Corroborated independently by the security agent.)
- `core/api/ai_handler.py:186-217` — read + a cross-tenant **write** (rewrites labels on foreign
  messages). `core/ai/search.py:24,47` takes `org_id` but never uses it. (Corroborated.)
- `core/api/slack_native_handler.py:65-106` and `telegram_native_handler.py:50-81` — call
  `Caller.from_event` never; use the victim's stored OAuth token to act **as the victim's bot** on
  Slack/Telegram.
- Related: `list_thread_messages(thread_key)` (`threads_handler.py:71`, `ai_handler.py:126`) queries
  GSI5 globally; thread_keys derive from email Message-ID/References headers (guessable/leakable).

**Fix structurally, not per-handler:** add one `require_agent(caller, agent_id)` helper in
`_common.py`, bind `org_id` into the message/thread key or assert it in `Repo`, add `Caller.from_event`
to the native handlers, and add a regression test (org-A key → 403/404 on org-B agent).

### 3. Sanitize inbound email before rendering (console XSS)
`console/src/pages/MessagePage.tsx:92-96` renders attacker-controlled `body_html` via
`dangerouslySetInnerHTML` with no sanitizer, and auth tokens live in `localStorage`
(`AuthContext.tsx:38-65`) — together, one email → account takeover. Sanitize with DOMPurify or a
sandboxed iframe + CSP, sanitize server-side at ingest, and move tokens to httpOnly cookies. (The
console is not deployed by default, which limits blast radius today — but fix before it ships.)

---

## P1 — Architectural gaps (features that silently don't work)

- **Event bus is write-only → webhooks never deliver.** `agentcomms-events` Kinesis is `grantWrite`
  to every handler; nothing is `grantRead`, there's no `KinesisEventSource`, no WS API, and
  `webhooks_handler.py` is pure CRUD. Customers register webhooks that never fire (gen1 had
  `lambdas/webhook_worker`; gen2 dropped it). Build the consumer/fan-out Lambda or cut the feature +
  stream. (rev-infra, rev-arch)
- **Outbound has two designs; the live one is unsafe, the async one is orphaned.** Live send is
  synchronous in the API Lambda (`messages_handler.py:131`) — no buffer/retry/DLQ, a slow vendor
  stalls the request. Meanwhile every adapter ships an SQS worker + CDK queue that **no producer
  enqueues to**, and the two families use divergent envelope shapes. Pick one path. (rev-adapters, rev-arch)
- **No DLQs anywhere in gen2** — SNS→ingest and all four outbound SQS queues. Failed inbound
  email/SMS is lost with no recovery. This is a regression from the legacy `queue-stack`. (rev-infra, rev-arch)
- **Plugin boundary is broken: `core/` imports `adapters/`.** The native handlers do
  `from adapters.slack/telegram/push …` directly, contradicting the registry contract
  (`core/adapters/base.py:9`). Third-party adapters can't satisfy native routes. (rev-arch)
- **"Core does persistence" is fiction.** `base.py` promises adapters never touch Dynamo/Kinesis, but
  no `core.persist_and_publish()` exists — each ingest handler reimplements persist+publish (email via
  providers, sms/slack/telegram via raw boto3). Five divergent paths where idempotency can drift.
  (rev-arch, rev-adapters)
- **Slack OAuth is unusable** — `redirect_uri`/`return_url` conflation means the token exchange returns
  `bad_redirect_uri`; no agent can complete a Slack bridge. (`adapters/slack/oauth.py:146-231`) (rev-adapters)
- **SES send + `sesv2:DeleteEmailIdentity` granted on `*` to all 13 handler Lambdas** — any handler
  bug can send as any domain or delete email identities platform-wide.
  (`agentcomms-api-stack.ts:156-169`) (rev-infra)

---

## P1 — Product-readiness (the retired product is still the public face)

- **Console targets the retired `api.victorymail.dev` and a resource model that no longer exists**
  (`/inboxes` vs live `/v1/agents/*`). It authenticates and functions against nothing. Retire it or
  rebuild against the live API. (rev-frontend)
- **Nearly all of `docs/` still documents FreeMail** — `api-reference.md` (172 victorymail refs / 0
  agentcomms), quickstart, sdks, webhooks, billing, plus root `ARCHITECTURE.md` (39 KB anchor doc) and
  `BUILD_PLAN.md`. A new contributor following the quickstart POSTs to a dead endpoint with the wrong
  key prefix. De-FreeMail the customer docs or move them to `docs/legacy/`; fix the README status
  table (shows Phase 5 "Upcoming" — it's done). (rev-docs)
- **Monitoring is blind to production.** `.exterminator/config.yaml` watches only `VictoryMail-*`
  resources (all dead); the live `AgentComms*` stack has no monitoring, and a `zero_ingest_alert`
  fires perpetually on a retired endpoint. Regenerate via the `exterminator-creator` skill. (rev-tests)
- **CI runs 45 live tests against the retired endpoint.** `tests/e2e/test_live_api.py` +
  duplicate/competing CI workflows (`ci.yml` vs `test.yml`) make the primary job red every push. Delete
  the live/legacy tests, retire `ci.yml`. (rev-tests)
- **SDK first-hour bugs:** both SDKs mis-parse the `{"error":"<string>"}` body — the Python SDK raises
  `AttributeError` on every 4xx/5xx; agent update (`PATCH`/`PUT`) is a dead route on every surface.
  Both SDKs are versioned 1.0.0. (rev-devsurface)

---

## P2 — Correctness, cost, hygiene (representative, not exhaustive)

- `find_message_by_id` uses `Limit=100` before filtering with no pagination → all AI-by-message-id ops
  404 on agents with >100 messages. (`repo.py:105-122`)
- Label persistence writes a top-level attr but reads `channel_native.labels` → categorization never
  persists. (`ai_handler.py:57` vs `repo.py:124-135`)
- No pagination cursor on any list endpoint → silent truncation past the limit.
- Email attachments are parsed then dropped; large bodies stored inline risk the 400 KB DynamoDB item
  limit (provisioned bodies/attachments S3 buckets are never written). Email replies set no
  In-Reply-To/References → broken threading.
- Telegram webhook secret == the public URL path segment; Push hardcodes `APNS_SANDBOX`.
- API keys have no revocation/expiry field; `extract()` validates against a caller-supplied JSON schema
  (remote `$ref` SSRF / ReDoS).
- Inbound email is accepted with no SPF/DKIM/DMARC/virus gating; From and threading headers are trusted.
- IAM: Bedrock policy hardcodes `us-east-1`; no `logRetention` on any Lambda; 7 GSIs all
  `ProjectionType.ALL` (~8× write cost); `deploy.yml` uses `cdk deploy --all` (re-synths legacy).
- `pytest.ini` shadows `pyproject.toml`, silently excluding adapter tests from the default run;
  Python version drift (venv 3.14 / CI 3.12 / lambdas 3.12).
- `core/providers/` is ~10% built (blob+events only, one consumer) — the `docs/azure-native-setup.md`
  portability story is far off. Either finish the seam or mark it experimental.

**Note on the repo-root `.env`:** it holds a live `AKIA…` key, but it is correctly **gitignored** (not
in the public repo). Rotation is good hygiene but this is not a public leak like the `ak_live_` key above.

---

## Retirement plan (large, clean deletions available)

- **`lambdas/` (~5,800 LOC) is entirely dead post-cutover** and cannot even synth from a clean checkout
  (references uncommitted handlers). Before deleting, make an explicit keep/drop decision on the four
  features with **no `core/` equivalent**: billing/Stripe, search, mailing lists, usage metrics. Port
  keepers first, then delete `lambdas/` + the nine legacy stack files + the `deployLegacy` branch in one
  commit. (rev-lambdas)
- Archive pre-pivot planning corpora off the public branch: `Projects/` (56 files), `openclaw/`,
  `docs/byoc*`, `openapi.yaml`.
- Delete migration one-shots (`tools/migrate_*`, `rollback_to_victorymail.py`,
  `finalize_agentcomms_dns.py`, `purge_migrated_test_orgs.py`) after archiving; keep `seed_first_org.py`,
  `smoke_test_live.sh`, `add_spdx_headers.py`.
- Drop the dead `Thread` model (`models.py:387-431`) and the unused `search(org_id=…)` param.

---

## Verification notes

- **Resolved a reviewer conflict:** the dev-surface agent flagged `agentcomms bootstrap` as deploying
  nonexistent stacks. `cdk list` confirms `AgentCommsAdapters-{Email,Sms,Push,Slack,Telegram}` **do**
  synthesize (created as sibling stacks via a template-literal name a literal grep missed). The
  `buildBootstrapStacks` list is correct; **not a bug.**
- Fixed since the prior review and re-confirmed: hard-coded account (`bin/app.ts:25-34`), email S3
  prefix (`ingest.py:56-61`).
