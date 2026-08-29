# AgentComms cutover runbook

> **Classification:** Operator-internal. Do not share publicly.
> **Last updated:** 2026-04-17
> **Estimated elapsed time:** ~2 hours for data migration + DNS flip

---

## Overview

This runbook covers the one-time production cutover from victorymail
(`api.victorymail.dev`) to AgentComms (`api.agentcomms.dev`). It is
designed for zero-data-loss and reversible within 24 hours.

**Responsible roles:**
- **Operator** — the engineer executing this runbook (solo is fine; pair is better)
- **Spotter** — monitors dashboards and error queues during the migration window

---

## Preflight (T-24 hours)

All steps must be completed before the cutover maintenance window opens.

- [ ] **Merge freeze**: create a branch protection rule on `main`/`develop` blocking new merges until post-cutover
- [ ] **Phase 1–4 tests green**: `pytest tests/ -q` passes on `phase1-foundation` with zero failures
- [ ] **Migration dry-run passes**:
  ```bash
  python tools/migrate_victorymail_to_agentcomms.py \
    --source-table victorymail \
    --dest-table agentcomms-staging \
    --dry-run --json | tee /tmp/migrate-dryrun.log
  ```
  Review log for unexpected `entity_unknown` events or error counts > 0
- [ ] **Integrity checker passes against staging**:
  ```bash
  python tools/check_migration_integrity.py \
    --source-table victorymail \
    --dest-table agentcomms-staging
  ```
- [ ] **Customer announcement sent**: `docs/customer-emails/pivot-announcement.md` sent to
  every paying customer (email list from CRM, not just active API keys)
- [ ] **DNS pre-staging** (do NOT make live yet):
  - Route 53 record for `api.agentcomms.dev` created and pointing at AgentComms API GW
  - Route 53 record for `console.agentcomms.dev` created and pointing at AgentComms console CloudFront
  - TTL on `api.victorymail.dev` reduced to **60 seconds** (reduces DNS propagation wait during cutover)
- [ ] **Sunset-redirect stack deployed to AWS** (but Route 53 not yet flipped):
  ```bash
  cd cdk
  cdk deploy SunsetRedirectStack \
    --context targetApiUrl=https://api.agentcomms.dev \
    --context sunsetDate=2026-10-17T00:00:00Z \
    --context hostedZoneId=$VICTORYMAIL_HOSTED_ZONE_ID \
    --context legacyHostname=api.victorymail.dev
  ```
  Verify the CloudFront distribution is DEPLOYED but the Route 53 alias record
  has **not** been flipped yet (the stack creates the Route 53 record — check that
  `api.victorymail.dev` still resolves to the old API GW for now, then comment out
  the `ARecord` construct from the stack before this deploy)
- [ ] **Stripe API key** loaded in operator shell: `export STRIPE_API_KEY=sk_live_...`
- [ ] **AWS credentials** point at prod account <AWS_ACCOUNT_ID>:
  ```bash
  aws sts get-caller-identity --query Account --output text
  # must print: <AWS_ACCOUNT_ID>
  ```
- [ ] **AgentComms smoke test passes**:
  ```bash
  bash tools/smoke_test_agentcomms.sh --base-url https://execute-api.us-east-1.amazonaws.com/prod
  ```
- [ ] **Rollback DNS batch file filled in**:
  Edit `tools/rollback-dns-batch.json`, replace `REPLACE_WITH_ORIGINAL_CLOUDFRONT_DOMAIN`
  with the current `api.victorymail.dev` CloudFront domain (found via
  `aws cloudfront list-distributions | jq '.DistributionList.Items[] | select(.Aliases.Items[] | contains("api.victorymail.dev")) | .DomainName'`)

---

## T-2 hours (prep)

- [ ] Post on status page: "Scheduled maintenance: 60-minute window starting at T+0. API downtime < 15 minutes."
- [ ] Notify internal Slack: `#engineering` and `#customer-success`
- [ ] Confirm agentcomms CloudWatch log groups are healthy (no elevated error rates)
- [ ] Confirm victorymail DynamoDB table has no in-flight writes (check CloudWatch DDB metrics)
- [ ] Record victorymail item count:
  ```bash
  aws dynamodb describe-table --table-name victorymail \
    --query 'Table.ItemCount' --output text
  ```
  Save as `PRE_MIGRATION_COUNT=<N>` for integrity check reference

---

## T-1 hour

- [ ] **Pause victorymail cron jobs** (SES inbound processor, webhook delivery worker):
  - Scale victorymail Lambda concurrency to 0 for inbound processor + outbound worker
  - Or use WAF managed rule to block `/v1/webhook-deliver` temporarily
- [ ] **Final dry-run** with exact prod tables:
  ```bash
  python tools/migrate_victorymail_to_agentcomms.py \
    --source-table victorymail \
    --dest-table agentcomms \
    --dry-run --json | tee /tmp/migrate-dryrun-prod.log
  # Check: no "error" events in log
  ```
- [ ] Verify Spotter is monitoring:
  - victorymail CloudWatch: `IncomingRequests`, `5XXError`
  - agentcomms CloudWatch: same metrics
  - DynamoDB: `ConsumedWriteCapacityUnits` on agentcomms table

---

## T+0:00 — Cutover start

### T+0:00 — Quiet traffic

Apply a temporary WAF rule returning `429 Too Many Requests` for all requests
to `api.victorymail.dev`. This gives in-flight requests ~10 seconds to drain
before the migration begins, and prevents new writes to victorymail during migration.

```bash
# Create WAF rate-limit / block rule via AWS console or CLI
# Rule name: "pivot-maintenance-block" — block all, priority 0
# Remove at T+1:30
aws wafv2 create-rule-group ... # see WAF runbook for exact CLI
```

> **Note:** This causes `429` for legitimate customers for ~15 minutes. The status
> page announcement covers this window.

---

### T+0:05 — Migrate data

```bash
python tools/migrate_victorymail_to_agentcomms.py \
  --source-table victorymail \
  --dest-table agentcomms \
  --json | tee /tmp/migrate-prod.log
```

Expected output: NDJSON lines with `"event": "write_ok"` for every entity.
Watch for any `"event": "error"` lines — if error rate > 0.1%, pause and investigate.

Estimated runtime: 5–15 minutes depending on item count.

---

### T+0:15 — Migrate S3 objects

```bash
bash tools/migrate_s3_objects.sh 2>&1 | tee /tmp/migrate-s3.log
```

Expected: all `aws s3 sync` commands exit 0.

---

### T+0:30 — Migrate Stripe customers

```bash
python tools/migrate_stripe_customers.py \
  --dry-run 2>&1 | tee /tmp/migrate-stripe-dryrun.log
# Review, then:
python tools/migrate_stripe_customers.py \
  --json 2>&1 | tee /tmp/migrate-stripe-prod.log
```

---

### T+0:40 — Run integrity checker

```bash
python tools/check_migration_integrity.py \
  --source-table victorymail \
  --dest-table agentcomms \
  --json | tee /tmp/integrity.log
```

**Expected:** all checks green, `"event": "integrity_ok"`.

**If any check fails:**
- If < 0.1% of items: log as known issue, proceed
- If > 0.1% or any org/api-key mismatch: **STOP. Rollback via DNS only** (T+0:45 not yet reached)

---

### T+0:45 — DNS flip

Flip `api.victorymail.dev` from the old API GW to the sunset-redirect CloudFront distribution.

If the CDK stack's `ARecord` was commented out during preflight deploy, re-enable it and redeploy:
```bash
cd cdk
cdk deploy SunsetRedirectStack
```

Or update the Route 53 record manually:
```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id $VICTORYMAIL_HOSTED_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api.victorymail.dev.",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "Z2FDTNDATAQYW2",
          "DNSName": "<sunset-redirect-cloudfront-domain>.cloudfront.net",
          "EvaluateTargetHealth": false
        }
      }
    }]
  }'
```

---

### T+0:50 — Route 53 confirmation

Confirm `api.agentcomms.dev` is resolving to the AgentComms API GW:
```bash
dig +short api.agentcomms.dev
# Should return CloudFront/API GW IP addresses, not old victorymail origin
```

---

### T+0:55 — DNS TTL expires

With TTL=60s set in preflight, propagation completes within ~60 seconds of the Route 53 change.
Confirm `api.victorymail.dev` now returns `301` to `api.agentcomms.dev`:
```bash
curl -v https://api.victorymail.dev/v1/agents 2>&1 | grep -E "^< HTTP|^< Location"
# Expected: HTTP/2 301
#           Location: https://api.agentcomms.dev/v1/agents
```

---

### T+1:00 — Live smoke test

Run the full smoke test battery against the live `api.agentcomms.dev` endpoint:
```bash
bash tools/smoke_test_agentcomms.sh --base-url https://api.agentcomms.dev
```

All checks must be green before proceeding.

---

### T+1:15 — Remove WAF block rule

Remove the `pivot-maintenance-block` WAF rule to restore normal traffic flow:
```bash
aws wafv2 delete-rule-group --name pivot-maintenance-block --scope REGIONAL --id $RULE_GROUP_ID --lock-token $LOCK_TOKEN
```

Traffic is now flowing normally to `api.agentcomms.dev`.

---

### T+1:30 — Cutover complete

- [ ] Update status page: maintenance window closed, all systems operational
- [ ] Post in `#engineering`: "Cutover complete at $(date -u). All checks green."
- [ ] Post in `#customer-success`: "Pivot cutover complete. Customers should see 301s from old URL."
- [ ] Start T+24 monitoring window (see below)

---

## Post-cutover monitoring (T+0 → T+24 hours)

Continuously monitor:

- **agentcomms API**: `5XXError` rate < 0.5%, p99 latency < 1s
- **victorymail sunset redirect**: `4XXError` count (expected: mostly 301s)
- **CloudWatch Logs**: agentcomms Lambda error rate
- **Stripe webhooks**: check Stripe dashboard for webhook delivery failures

**Rollback decision gates:**

| Time window | Rollback method | Trigger |
|-------------|-----------------|---------|
| T+0:00 to T+0:45 | DNS flip back only (route53 change, no data needed) | Any data migration failure > 0.1% |
| T+0:45 to T+24:00 | `tools/rollback_to_victorymail.py` + DNS flip | API error rate > 5% sustained 10 min, or data corruption |
| After T+24:00 | Not feasible without data loss | N/A — accept forward |

**If rollback needed in window T+0:45 → T+24:00:**
```bash
python tools/rollback_to_victorymail.py \
  --source-table agentcomms \
  --dest-table victorymail \
  --cutover-timestamp <T_ISO8601> \
  --json | tee /tmp/rollback.log
# Then flip DNS per rollback-dns-batch.json:
aws route53 change-resource-record-sets \
  --hosted-zone-id $VICTORYMAIL_HOSTED_ZONE_ID \
  --change-batch file://tools/rollback-dns-batch.json
```

---

## T+24 hours — Stability check

- [ ] Review CloudWatch metrics: no elevated error rate in agentcomms
- [ ] Review Stripe: no subscription failures
- [ ] Close the rollback window (rollback_to_victorymail.py is no longer meaningful after this point)
- [ ] Post internal announcement: "AgentComms pivot stable. Rollback window closed."
- [ ] Schedule T+90 sunset task (see below)

---

## T+90 days — Sunset completion

On the date 90 days after cutover (approximately `<CUTOVER_DATE + 90d>`):

1. Update the `sunsetDate` prop in the CDK stack to today's date.
2. Redeploy the sunset-redirect stack:
   ```bash
   cd cdk
   cdk deploy SunsetRedirectStack \
     --context sunsetDate=$(date -u +%Y-%m-%dT%H:%M:%SZ)
   ```
   After this, `api.victorymail.dev` returns **410 Gone** on all requests.

3. Monitor for 7 days for customer complaints.
4. After 7 days with no complaints, retire the victorymail stacks:
   ```bash
   cd cdk
   cdk destroy VictorymailApiStack VictorymailDataStack VictorymailEmailStack
   ```
   (Keep the SunsetRedirectStack running for another 30 days as a tombstone.)

---

## Appendix: Key environment variables

```bash
export AWS_PROFILE=agentcomms-prod        # or set AWS_ACCESS_KEY_ID + SECRET
export VICTORYMAIL_HOSTED_ZONE_ID=Z1ABC...
export STRIPE_API_KEY=sk_live_...
export AGENTCOMMS_TABLE=agentcomms
export VICTORYMAIL_TABLE=victorymail
```

## Appendix: Emergency contacts

- AWS Support case: account <AWS_ACCOUNT_ID>
- Stripe support: dashboard.stripe.com → Support
- On-call engineer: see `#on-call` Slack channel
