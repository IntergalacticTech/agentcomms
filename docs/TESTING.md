# Testing AgentComms end-to-end

This guide walks you through verifying the AgentComms bootstrap flow on a **clean AWS account** (recommended: a separate sub-account, not your production one). It exercises every channel path that doesn't require a real third-party registration (Slack app, 10DLC brand, APNs certs).

Expect this to take about 45 minutes the first time: setup and AWS/DNS preconditions, a CDK bootstrap/deploy run, and a few minutes of smoke tests.

---

## 1. Prerequisites

Install locally on your workstation:

- **Node 20+**: `node --version` should print `v20.x` or higher
- **Python 3.12+**: `python3 --version`
- **AWS CLI v2**: `aws --version` prints `aws-cli/2.x`
- **AWS CDK v2**: `npx cdk --version` prints `2.x`
- **Docker Desktop**: `docker info` succeeds (CDK bundling runs containers for Python Lambda deps)

Provision ahead of time:

- **A fresh AWS sub-account** (or a scratch account with AdministratorAccess). Don't test this against a production account — if something goes sideways you want a clean blast radius.
- **A domain you own** with DNS delegated to Route 53 in that AWS account. It doesn't need to be a domain you care about — `agentcomms-test-<yourname>.com` is fine to register in Route 53 if you don't have a spare.
- **An email address** you can read (used for the smoke-test delivery). It does NOT need to be on the same domain.

Create the Route 53 hosted zone if it doesn't exist:

```bash
aws route53 create-hosted-zone \
  --name agentcomms-test.example.com \
  --caller-reference $(date +%s)
```

Then update your registrar's NS records to point at the four Route 53 name servers it printed.

---

## 2. Install the CLI

```bash
# from the AgentComms source tree
cd cli && npm install && npm run build && npm link
# verify
agentcomms --version   # → 0.1.0
agentcomms --help
```

(When the npm package is public, this becomes `npm i -g @agentcomms/cli`. For now you're installing from the source tree.)

---

## 3. Preflight (no side effects)

Run the `doctor` subcommand first. It runs every check that `bootstrap` would run, but deploys nothing.

```bash
export AWS_PROFILE=your-test-profile     # or set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY
export AGENTCOMMS_DOMAIN=agentcomms-test.example.com
export AGENTCOMMS_ADMIN_EMAIL=you@example.com
export AWS_REGION=us-east-1

agentcomms doctor --domain $AGENTCOMMS_DOMAIN --json
```

Expected output (one JSON line per check):

```
{"phase":"preflight","check":"aws_credentials","status":"ok","msg":"account 123456789012"}
{"phase":"preflight","check":"region","status":"ok","msg":"SES-inbound region us-east-1"}
{"phase":"preflight","check":"route53_zone","status":"ok","msg":"zone /hostedzone/Z0123456 found"}
{"phase":"preflight","check":"ses_account","status":"warn","msg":"SES in sandbox; ..."}
{"phase":"preflight","check":"tool_node","status":"ok"}
{"phase":"preflight","check":"tool_python3","status":"ok"}
{"phase":"preflight","check":"tool_aws","status":"ok"}
{"phase":"preflight","check":"tool_docker","status":"ok"}
```

If any check is `fail`, fix that item before proceeding. The `ses_account warn` is fine — bootstrap proceeds; you'll just need to request SES production access later if you want to send to unverified recipients.

---

## 4. Bootstrap

This is the real deploy. It creates the core AgentComms CloudFormation stacks in your account, a KMS key, an API Gateway, Lambda functions, a DynamoDB table with 7 GSIs, S3 buckets, a Kinesis stream, and adapter infrastructure. Budget roughly 20 minutes wall-clock on the first run.

```bash
agentcomms bootstrap \
  --domain $AGENTCOMMS_DOMAIN \
  --region $AWS_REGION \
  --admin-email $AGENTCOMMS_ADMIN_EMAIL \
  --non-interactive \
  --json | tee /tmp/bootstrap.log
```

Watch for these phases (each is one line of NDJSON):

- `preflight` — repeats the doctor checks
- `cdk_bootstrap` — one-time CDK toolkit stack (skipped if already bootstrapped)
- `deploy` — core stacks: AgentCommsData, AgentCommsEvents, AgentCommsApi, AgentCommsAdapters, AgentCommsAdapters-Email, plus enabled adapter sub-stacks
- `ses` — DKIM identity registration
- `seed` — creates the first Org and prints your admin API key
- `smoke` — confirmation
- `done` — final report

**When the `done` line appears, extract the `admin_api_key` value.** It will only be shown once.

```bash
ADMIN_API_KEY=$(grep '"phase":"done"' /tmp/bootstrap.log | tail -1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["admin_api_key"])')
API_URL=$(grep '"phase":"done"' /tmp/bootstrap.log | tail -1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_url"])')
echo "$ADMIN_API_KEY"
echo "$API_URL"
```

Exit code reference:
- `0` — success
- `1` — preflight failure (fix and retry)
- `2` — CDK deploy failure (check CloudFormation console; most are transient and retriable)
- `3` — DKIM verification timeout (wait, then `agentcomms bootstrap --resume`)
- `4` — smoke test failed (needs human attention; check CloudWatch logs)

---

## 5. Smoke tests against the live API

### Test 1 — list agents (should be empty)
```bash
curl -sS -H "Authorization: Bearer $ADMIN_API_KEY" "$API_URL/agents" | jq
# expected: {"agents": []}
```

### Test 2 — create an agent with email provisioning
```bash
curl -sS -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"TestBot\",\"provision\":{\"email\":{\"local_part\":\"test\",\"domain\":\"$AGENTCOMMS_DOMAIN\"}}}" \
  "$API_URL/agents" | jq
# expected: 201 response with agent_id and channels[0] = email, status=active
```

### Test 3 — read the agent's unified inbox
```bash
AGENT_ID=$(curl -sS -H "Authorization: Bearer $ADMIN_API_KEY" "$API_URL/agents" | jq -r '.agents[0].agent_id')
curl -sS -H "Authorization: Bearer $ADMIN_API_KEY" "$API_URL/agents/$AGENT_ID/messages" | jq
# expected: {"messages": []}
```

### Test 4 — create a vault TOTP entry
```bash
curl -sS -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type":"totp","label":"test-github","seed":"JBSWY3DPEHPK3PXP"}' \
  "$API_URL/vault" | jq
# then fetch the current code:
VAULT_ID=$(curl -sS -H "Authorization: Bearer $ADMIN_API_KEY" "$API_URL/vault" | jq -r '.items[0].vault_id')
curl -sS -H "Authorization: Bearer $ADMIN_API_KEY" "$API_URL/vault/$VAULT_ID/totp" | jq
# expected: {"code":"123456","valid_until":...}
```

### Test 5 — create a persona
```bash
curl -sS -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice Test","email":"alice@example.com"}' \
  "$API_URL/personas" | jq
```

### Test 6 — register a custom domain
```bash
curl -sS -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"domain_name":"acme-test.example.com"}' \
  "$API_URL/domains" | jq
# expected: 201 with DKIM tokens + DNS records to publish
```

If all six return the expected shape with 2xx status codes, the deploy is healthy.

---

## 6. Send a real email through the hub

The email adapter is the most exercised path in the codebase. Send a real email:

```bash
EMAIL_AGENT_ID=$(curl -sS -H "Authorization: Bearer $ADMIN_API_KEY" "$API_URL/agents" | jq -r '.agents[] | select(.name=="TestBot") | .agent_id')
curl -sS -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"to\":\"$AGENTCOMMS_ADMIN_EMAIL\",\"subject\":\"AgentComms smoke test\",\"body\":\"If you received this, end-to-end send works.\"}" \
  "$API_URL/agents/$EMAIL_AGENT_ID/messages" | jq
```

Check your inbox at `$AGENTCOMMS_ADMIN_EMAIL` within 30 seconds.

**If you're in SES sandbox**, you'll need to verify `$AGENTCOMMS_ADMIN_EMAIL` as an identity first:

```bash
aws sesv2 create-email-identity --email-identity $AGENTCOMMS_ADMIN_EMAIL
# then click the verification email before retrying the send
```

---

## 7. Receive an email through the hub

From any external inbox, send an email to `test@$AGENTCOMMS_DOMAIN`. Wait about 30 seconds, then:

```bash
curl -sS -H "Authorization: Bearer $ADMIN_API_KEY" "$API_URL/agents/$EMAIL_AGENT_ID/messages" | jq
```

You should see a message with `direction: "inbound"`, `is_dm: true`, and the body text of your test email.

If the message doesn't appear, check the ingest Lambda logs:

```bash
aws logs tail /aws/lambda/AgentCommsAdaptersEmail-EmailIngestFn* --since 5m
```

---

## 8. Enable an additional channel

### Telegram (fastest)

```bash
# 1. In Telegram, message @BotFather: /newbot  (walk through the prompts; save the token)
# 2. Enable the channel:
agentcomms channels enable telegram
# (paste the bot token when prompted)

# 3. Add a telegram channel to your agent:
curl -sS -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"channel":"telegram","mode":"provision","config":{"bot_token":"'$TELEGRAM_BOT_TOKEN'"}}' \
  "$API_URL/agents/$EMAIL_AGENT_ID/channels" | jq

# 4. Find your bot in Telegram (the username from @BotFather), say /start, then send "hi"
# 5. Check unified inbox:
curl -sS -H "Authorization: Bearer $ADMIN_API_KEY" "$API_URL/agents/$EMAIL_AGENT_ID/messages" | jq
```

Both the email and the Telegram messages should appear in the same unified inbox, interleaved by timestamp.

---

## 9. Tear down when you're done

```bash
agentcomms destroy --yes
```

This deletes the AgentComms CloudFormation stacks deployed by bootstrap and the DynamoDB table. It **does not** delete the S3 buckets (retained to protect against accidental data loss). Delete them manually:

```bash
for b in agentcomms-raw-inbound-prod-<your-account> agentcomms-bodies-prod-<your-account> agentcomms-attachments-prod-<your-account>; do
  aws s3 rm s3://$b --recursive
  aws s3api delete-bucket --bucket $b
done
```

---

## Known issues during testing

- **First bundle is slow.** The CDK Docker bundling takes 3-5 minutes the first time it pulls the `python:3.12` image. Subsequent deploys are ~30 seconds.
- **macOS + Docker + `/Users/` mounts.** If you see "too many open files" during CDK synth, raise your fd limit: `sudo launchctl limit maxfiles 524288 524288` and restart Docker Desktop.
- **SES sandbox.** New AWS accounts start with SES in sandbox mode. You can deploy AgentComms fine, but you can only send email to verified recipients. Request production access with `aws sesv2 put-account-details --production-access-enabled --mail-type TRANSACTIONAL --website-url https://agentcomms-test.example.com --use-case-description "..." --contact-language EN` (approval takes 24 hours).
- **10DLC for SMS.** If you want to test SMS, you'll need to register a brand and campaign through AWS End User Messaging. That takes 2–7 business days and costs $4/month per number; skip it unless you genuinely need SMS for this test round.
- **Slack app registration.** If you want to test Slack, you'll need to create a Slack app in Slack's developer console and paste the credentials into `agentcomms channels enable slack`. Roughly 10 minutes of manual work.

---

## Reporting issues

If something breaks during testing, the most useful thing you can do is capture:

1. The full `/tmp/bootstrap.log` (NDJSON output).
2. CloudFormation events for the failing stack: `aws cloudformation describe-stack-events --stack-name <failed-stack>`.
3. The relevant Lambda's CloudWatch log group, last 5 minutes.

Open an issue at https://github.com/IntergalacticTech/agentcomms/issues with those three pieces.
