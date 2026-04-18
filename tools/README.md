# Migration Tools

Operator-only scripts for the FreeMail → AgentComms data migration.
All tools require Python 3.11+ and the dependencies in `tools/requirements.txt`.

```
pip install -r tools/requirements.txt
```

> **IMPORTANT:** Always run with `--dry-run` first. Never run against production
> without a successful dry-run pass.

---

## Tools

### `migrate_victorymail_to_agentcomms.py`

Migrates DynamoDB items from the legacy `victorymail` table into the new
`agentcomms` table. Idempotent (uses `attribute_not_exists(PK)` guards).

**When to run:** Phase 5 production cutover, T+10m in the runbook.

```bash
# Dry-run (no writes)
python tools/migrate_victorymail_to_agentcomms.py --dry-run

# Live run
python tools/migrate_victorymail_to_agentcomms.py \
  --source-table victorymail \
  --dest-table agentcomms \
  --region us-east-1
```

---

### `migrate_s3_rekey.py`

Copies S3 objects between buckets. Supports two modes:

- **Re-key mode** (default): reads the `victorymail` DynamoDB table to build a
  `ses_message_id → (org_id, agent_id, msg_id)` map, then copies each raw inbound
  email from `inbound/{ses_message_id}` to `{org_id}/{agent_id}/email/{msg_id}`.
  Unmapped objects go to `unmapped/{original_key}`.

- **Passthrough mode** (`--passthrough`): copies objects preserving the original key
  (equivalent to `aws s3 sync`). Used for bodies and attachments buckets.

**When to run:** Phase 5 production cutover, T+25m in the runbook via `migrate_s3_objects.sh`.

```bash
# Re-key raw-email bucket (dry-run)
python tools/migrate_s3_rekey.py \
  --source-bucket victorymail-raw-email \
  --dest-bucket agentcomms-raw-inbound-prod-732770059798 \
  --dry-run

# Passthrough bodies bucket
python tools/migrate_s3_rekey.py \
  --source-bucket victorymail-bodies \
  --dest-bucket agentcomms-bodies-prod-732770059798 \
  --passthrough
```

Options:
- `--source-bucket` — source S3 bucket (required)
- `--dest-bucket` — destination S3 bucket (required)
- `--source-table` — DynamoDB table for cross-reference (default: `victorymail`)
- `--region` — AWS region (default: `us-east-1`)
- `--passthrough` — copy without key transformation
- `--dry-run` — count what would be copied; no writes
- `--parallelism N` — concurrent S3 copy operations (default: 8)
- `--json` — NDJSON output

---

### `migrate_s3_objects.sh`

Thin bash orchestrator that runs all 3 bucket migrations in order:
1. `victorymail-raw-email` → `agentcomms-raw-inbound-prod-{account}` (re-keyed)
2. `victorymail-bodies` → `agentcomms-bodies-prod-{account}` (passthrough)
3. `victorymail-attachments` → `agentcomms-attachments-prod-{account}` (passthrough)

**When to run:** Phase 5 production cutover, T+25m.

```bash
# Dry-run all 3 buckets
DRY_RUN="--dry-run" ./tools/migrate_s3_objects.sh

# Live run
./tools/migrate_s3_objects.sh
```

---

### `migrate_stripe_customers.py`

Reads all active Stripe subscriptions and applies the AgentComms pricing migration:

| Current plan | Action |
|---|---|
| Free ($0) | No change |
| Starter ($5/mo) | Cancel sub at period end; apply 6-month 100%-off coupon for Developer tier |
| Pro ($25/mo) | Migrate to Developer tier ($19/mo); no proration |
| Enterprise | No change (custom contracts) |

Requires the Stripe secret key (`--stripe-key` or `STRIPE_SECRET_KEY` env var).
Every API call uses `idempotency_key="agentcomms-migration-{customer_id}-{action}"`.
All calls are logged to `/tmp/stripe-migration-{timestamp}.log`.

**When to run:** Phase 5 production cutover, T+75m (after DNS flip confirmed).

```bash
# Dry-run (no Stripe writes)
python tools/migrate_stripe_customers.py \
  --stripe-key sk_live_... \
  --dry-run

# Test against single customer
python tools/migrate_stripe_customers.py \
  --stripe-key sk_live_... \
  --customer-id cus_xxx \
  --dry-run

# Live run
python tools/migrate_stripe_customers.py \
  --stripe-key sk_live_...
```

Options:
- `--stripe-key` — Stripe secret key (or `STRIPE_SECRET_KEY` env var)
- `--dry-run` — print actions; no Stripe writes
- `--json` — NDJSON output
- `--customer-id CUST` — limit to one customer for testing
- `--halt-on-error` / `--no-halt-on-error` — stop vs. continue on Stripe errors (default: halt)

**Stripe SDK requirement:** `stripe>=8.0` (see `tools/requirements.txt`).

---

### `check_migration_integrity.py`

Post-migration integrity spot-check. Compares item counts and samples between
the `victorymail` and `agentcomms` DynamoDB tables.

**When to run:** Phase 5 cutover, T+55m and T+90m.

```bash
python tools/check_migration_integrity.py
```

---

### `seed_first_org.py`

One-time seed script to create the first organization in a fresh AgentComms
deployment. Not part of the migration path.

---

## Running Tests

```bash
pytest tests/tools/ -v
```

Tests use `moto` for AWS mocking and `unittest.mock` for Stripe. No real AWS or
Stripe credentials are needed.
