# AgentComms Phase 5: Migration & Cutover — Implementation Plan

> **Fidelity note:** B-fidelity. Follow the Phase 1 TDD rhythm.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Spec:** `docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md` §6
**Predecessors:** Phases 1–4 complete. `agentcomms-*` CDK stacks are running parallel to `victorymail-*` stacks in production AWS account <AWS_ACCOUNT_ID>.

**Goal:** Migrate the live FreeMail data to AgentComms, cut DNS over, rewire Stripe, and run the dual-service window. At Phase 5 exit, `api.agentcomms.dev` is authoritative, all existing customers are migrated with zero data loss, and `api.victorymail.dev` is on a 90-day sunset clock.

**Architecture:** One-shot Python migration script transforms `victorymail` DynamoDB items into `agentcomms` schema. S3 objects are re-keyed via `aws s3 sync`. DNS flip via Route 53 weighted routing. Stripe customer records updated via API. Old `api.victorymail.dev` starts returning 301 redirects with `Sunset` and `Deprecation` headers.

**Tech Stack:** Same as prior phases. New: `stripe` SDK for customer updates.

---

## File structure (created in Phase 5)

```
tools/
├── migrate_victorymail_to_agentcomms.py     # ⭐ the migration script
├── migrate_stripe_customers.py              # Stripe product migration
├── migrate_s3_objects.sh                    # S3 sync helpers
├── check_migration_integrity.py             # post-migration spot-checks
└── rollback_to_victorymail.py               # one-shot rollback (up to 24h after cutover)

cdk/lib/stacks/
└── sunset-redirect-stack.ts                 # api.victorymail.dev → 301 → api.agentcomms.dev

MIGRATION.md                                 # customer-facing before/after diff
```

---

## Task 1: Write the migration script (idempotent, re-runnable)

**File:** `tools/migrate_victorymail_to_agentcomms.py`

**Core algorithm** (per Spec §6.3):

```python
# pseudocode; see spec §6.3 for the full data mapping
for org in scan(victorymail_table, entity="organization"):
    copy_item_as_is(agentcomms_table, org)

for api_key in scan(victorymail_table, entity="api_key"):
    copy_item_as_is(agentcomms_table, api_key)

for inbox in scan(victorymail_table, entity="inbox"):
    agent = Agent(
        agent_id="agt_" + inbox.inbox_id[4:],
        org_id=inbox.org_id,
        name=inbox.display_name or inbox.address,
        metadata={"migrated_from_inbox": inbox.inbox_id, **({"pod": inbox.pod_id} if inbox.pod_id else {})},
    )
    put_if_not_exists(agentcomms_table, agent.to_dynamodb_item())

    channel = Channel(
        channel_id="chan_em_" + inbox.inbox_id[4:],
        agent_id=agent.agent_id,
        org_id=inbox.org_id,
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": inbox.address, "domain_id": inbox.domain_id},
        address_index_value=inbox.address,
        status=ChannelStatus.ACTIVE,
    )
    put_if_not_exists(agentcomms_table, channel.to_dynamodb_item())

for msg in scan(victorymail_table, entity="message"):
    agent_id = "agt_" + inbox_id_for_message(msg)[4:]
    new_msg = UnifiedMessage(
        message_id=msg.msg_id,
        agent_id=agent_id,
        org_id=msg.org_id,
        channel_id="chan_em_" + inbox_id_for_message(msg)[4:],
        channel=ChannelType.EMAIL,
        direction=msg.direction,
        status=msg.status,
        from_=Party(address=msg.from_address, display_name=msg.from_display_name),
        to=[Party(address=a) for a in msg.to_addresses],
        subject=msg.subject,
        body_text=msg.body_text,
        body_html=msg.body_html,
        thread_key="thr_" + msg.thread_id[4:] if msg.thread_id else None,
        is_dm=True,  # every email to a FreeMail inbox was a DM by definition
        received_at=msg.created_at,
        channel_native={
            "message_id_header": msg.message_id_header,
            "in_reply_to": msg.in_reply_to,
            "references": msg.references or [],
            "spf_pass": msg.spf_pass,
            "dkim_pass": msg.dkim_pass,
            "dmarc_pass": msg.dmarc_pass,
        },
        external_id=msg.message_id_header,
    )
    put_if_not_exists(agentcomms_table, new_msg.to_dynamodb_item())

for thread in scan(victorymail_table, entity="thread"):
    new_thread = Thread(
        thread_key="thr_" + thread.thread_id[4:],
        agent_id="agt_" + thread.inbox_id[4:],
        org_id=thread.org_id,
        channel=ChannelType.EMAIL,
        native_thread_id=thread.thread_id,  # preserve
        subject=thread.subject,
        last_message_at=thread.last_message_at,
        message_count=thread.message_count,
        participants=thread.participants,
    )
    put_if_not_exists(agentcomms_table, new_thread.to_dynamodb_item())

# Domains: preserve as-is (org-scoped, same shape).
# Webhooks: migrate per-inbox webhooks to per-agent webhooks.
# Drafts, Lists, Attachments: structural port.
```

**Requirements:**
- Idempotent: every write uses a `ConditionExpression="attribute_not_exists(PK)"` guard. Re-running the script is safe.
- Progress: emit NDJSON per 100 items. Final summary counts per entity type.
- Integrity spot-check: at end, randomly sample 50 messages per entity type, re-read both tables, compare normalized forms.
- Runtime budget: target < 15 minutes at current scale (small). If it exceeds 30 min, parallelize scans by org_id.

**Testing:**
- Unit-test each migration function against moto fixtures — seed a victorymail-shape table with known items, run migration, assert agentcomms-shape output.
- Add a dry-run mode (`--dry-run`) that counts what would be written but does not write.

**Commit:** `feat(phase5): migration script victorymail → agentcomms (idempotent, dry-run supported)`

---

## Task 2: S3 migration

**File:** `tools/migrate_s3_objects.sh`

For each of the 3 old buckets (`victorymail-raw-email`, `victorymail-bodies`, `victorymail-attachments`), sync to the new bucket with a re-keying pass where required:

```bash
# raw-email: old key was /inbound/{message-id}, new key is /{org_id}/{agent_id}/{channel}/{msg_id}
# Use a Python re-keying script (bash aws s3 sync can't transform keys)
python tools/migrate_s3_rekey.py \
  --source-bucket victorymail-raw-email \
  --dest-bucket agentcomms-raw-inbound-prod-<AWS_ACCOUNT_ID> \
  --key-map-script map_raw_email_key.py

# bodies, attachments: keep same key structure (already {org_id}/{msg_id}/...)
aws s3 sync s3://victorymail-bodies s3://agentcomms-bodies-prod-<AWS_ACCOUNT_ID>
aws s3 sync s3://victorymail-attachments s3://agentcomms-attachments-prod-<AWS_ACCOUNT_ID>
```

**Steps:**
1. Write `tools/migrate_s3_rekey.py` — streams objects with ContinuationToken, applies a Python key-transform function, writes to the new bucket. Skips objects already present in dest.
2. Run against a test sub-account bucket pair first; verify integrity via random-sample checksums.
3. Run in production during the Week-3 migration window.

**Commit:** `feat(phase5): S3 object migration with re-keying (raw-email) + passthrough sync (bodies, attachments)`

---

## Task 3: Integrity check script

**File:** `tools/check_migration_integrity.py`

Spot-check the migration by:
1. Count items per entity type in both tables. Ratio of (agentcomms / victorymail) must be 1.0 for `organization` and `api_key`, exactly 1.0 for `inbox → agent+channel` (one of each per inbox), 1.0 for `message → message`, and so on.
2. For 100 random messages, re-read both old and new versions, normalize, compare. Any delta → log and fail.
3. Check GSI3 (unified inbox) returns the same message count per agent as the old inbox's message listing.
4. Emit NDJSON report.

**Commit:** `feat(phase5): post-migration integrity check script`

---

## Task 4: Stripe customer migration

**File:** `tools/migrate_stripe_customers.py`

Per Spec §7.3:
- Existing Free tier customers → new Free (no Stripe change).
- Existing Starter $5 → new Free + 6-month complimentary Developer credit applied as a Stripe coupon.
- Existing Pro $25 → new Developer tier at $19, grandfathered 6 months (price override via subscription item) then normal pricing.
- Existing Enterprise/Business → no change (custom contract).

**Steps:**
1. List all active Stripe subscriptions.
2. For each, identify the current plan.
3. Apply the mapping: create new products/prices in Stripe, create coupons, migrate subscriptions, backdate if needed.
4. For each customer: send the personal migration email (Task 6).

**Requirements:**
- Dry-run mode that outputs the exact Stripe API calls that would be made.
- Real run logs every API call + response to a timestamped log file.
- Halt-on-error: any non-2xx response from Stripe stops the script and prompts for manual intervention.

**Commit:** `feat(phase5): Stripe customer migration script (Free→Free, Starter→Free+credit, Pro→Dev+grandfather)`

---

## Task 5: Sunset redirect stack

**File:** `cdk/lib/stacks/sunset-redirect-stack.ts`

Creates:
- CloudFront distribution for `api.victorymail.dev` with a Lambda@Edge function that:
  - Returns 301 to `api.agentcomms.dev/{same-path-if-mappable}` when the path can be mapped. Path mapping table:
    - `/v1/inboxes/{id}/messages` → `/v1/agents/agt_{id[4:]}/email/messages` (best-effort)
    - `/v1/inboxes/{id}/send` → `/v1/agents/agt_{id[4:]}/messages`
    - ...(table enumerated from Spec §6.5)
  - Returns `Deprecation: true` and `Sunset: {now+90d}` headers on every response.
  - Returns 410 Gone after the Change Date (Week 13).
- Route 53 alias for `api.victorymail.dev` → CloudFront distribution.

**Commit:** `feat(phase5): sunset redirect stack for api.victorymail.dev`

---

## Task 6: Customer communications

**Deliverables (human-authored; Phase 5 includes collecting and sending):**
- Personal email to each paying Stripe customer ~10 days before cutover. Template at `docs/customer-emails/pivot-announcement.md`. Variables: customer name, current plan, migrated plan, migration date, your migration call offer.
- Public blog post at `agentcomms.dev/blog/pivot`. Draft at `landing/blog/pivot.md`, published at Week 3.
- `MIGRATION.md` at repo root — the endpoint-by-endpoint before/after diff. Auto-generate from `openapi.yaml` diffs where possible.

**Commit:** `docs(phase5): customer emails, migration guide, pivot blog post draft`

---

## Task 7: Production cutover runbook

**File:** `docs/runbooks/pivot-cutover.md`

Step-by-step runbook for the production migration window (T-0 to T+2 hours):

```
T-24h: Freeze customer config changes (merge freeze on victorymail).
T-1h:  Announce maintenance window to customers.
T:     Begin migration.
T+5m:  tools/migrate_victorymail_to_agentcomms.py --dry-run → expect zero errors
T+10m: tools/migrate_victorymail_to_agentcomms.py  (real run)
T+25m: tools/migrate_s3_objects.sh
T+55m: tools/check_migration_integrity.py → expect all green
T+60m: DNS cutover:
       - Route 53: api.victorymail.dev → point at sunset-redirect-stack CloudFront
       - Route 53: api.agentcomms.dev → point at agentcomms api stack
T+65m: Smoke test: agentcomms bootstrap --doctor against prod; hit each channel's health endpoint
T+75m: tools/migrate_stripe_customers.py (after agentcomms is live and confirmed)
T+90m: Post-cutover integrity check: re-run tools/check_migration_integrity.py
T+120m: If any step failed and we're past 60m from cutover, engage rollback
         (tools/rollback_to_victorymail.py). Otherwise: done.
```

**Commit:** `docs(phase5): pivot-cutover runbook`

---

## Task 8: Rollback script

**File:** `tools/rollback_to_victorymail.py`

For the first 24 hours post-cutover, rollback is "flip DNS back." After that, any new writes to agentcomms would need to be mirror-back-written to victorymail.

**Steps:**
1. `aws route53 change-resource-record-sets` → point api.agentcomms.dev back at no-op (returning 503), point api.victorymail.dev CloudFront distribution to the OLD victorymail API.
2. Scan agentcomms table for items with `created_at > cutover_timestamp`.
3. Reverse-transform each and write to victorymail table.
4. Log what was written so it's traceable.

**Caveat (documented in the script header):** after Week 4, rollback is not feasible without data loss. The runbook reflects this.

**Commit:** `feat(phase5): rollback_to_victorymail script (24h-safe)`

---

## Task 9: Dual-run monitoring

For the 90-day sunset window, CloudWatch dashboards + alarms:
- Rate of 301s on `api.victorymail.dev` (should decay from ~100% of prior traffic to < 5% as customers update SDKs).
- Rate of non-2xx responses on `api.agentcomms.dev` (baseline, spike detection).
- 410 rate after Change Date transition.

**File:** `cdk/lib/stacks/agentcomms-sunset-monitoring-stack.ts`

**Commit:** `feat(phase5): sunset-window CloudWatch monitoring`

---

## Phase 5 exit criteria

- [ ] Migration script runs clean against production data in dry-run mode
- [ ] Migration script runs clean in production (live)
- [ ] Post-migration integrity check passes (all deltas = 0)
- [ ] DNS cutover successful; `api.agentcomms.dev` authoritative
- [ ] `api.victorymail.dev` returns 301s with `Sunset` and `Deprecation` headers
- [ ] Every paying Stripe customer received a personal email
- [ ] Stripe subscriptions migrated per plan
- [ ] Rollback script exists and was tested against staging
- [ ] Runbook tested dry-run in a staging pair of accounts

---

*End Phase 5 plan. Estimated calendar: 2 weeks of prep + a 2-hour production cutover window. High-risk phase — invest extra time in dry runs.*
