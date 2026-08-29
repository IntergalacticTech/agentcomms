# AGENT.md — Deploy AgentComms into your AWS account

This file is written for coding agents (Claude Code, Cursor, Aider, Codex, etc.).
If you are a human, you can follow it too — it's just terse.

## TL;DR

1. Install: `npm i -g @agentcomms/cli`
2. Set 3 env vars: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (or a named profile), `AGENTCOMMS_DOMAIN`, `AGENTCOMMS_ADMIN_EMAIL`
3. Run: `agentcomms bootstrap --domain $AGENTCOMMS_DOMAIN --admin-email $AGENTCOMMS_ADMIN_EMAIL --non-interactive --json`
4. Wait ≤ 25 minutes.
5. Read final NDJSON line — contains the `admin_api_key`. Store it.

## Preconditions (verify before starting)

Before running `agentcomms bootstrap`, confirm:

- [ ] AWS credentials work: `aws sts get-caller-identity` returns your account.
- [ ] Your target AWS region is one where SES inbound works: `us-east-1`, `us-west-2`, `eu-west-1`.
- [ ] You own the DNS for the target domain. Create a Route 53 hosted zone for it in the same account: `aws route53 list-hosted-zones --query 'HostedZones[?Name==`your-domain.com.`]'` should return a zone.
- [ ] Node 20+, Python 3.12+, AWS CLI v2, AWS CDK v2 (`npx cdk --version`), Docker daemon running.

If any precondition fails, STOP. Running bootstrap without preconditions leads to partial deployments that are hard to clean up.

## The command (machine-parseable)

```bash
agentcomms bootstrap \
  --domain your-domain.com \
  --region us-east-1 \
  --admin-email you@your-domain.com \
  --non-interactive \
  --json
```

Optional flags:
- `--account 123456789012` — validate that AWS creds resolve to this account ID before deploying
- `--profile myprofile` — use a named AWS CLI profile
- `--skip-channels sms,slack` — omit specific channel adapters from the initial deploy

## NDJSON event stream

Each phase emits a line of JSON to stdout. Expected phases in order:

```json
{"phase":"preflight","check":"aws_credentials","status":"ok"}
{"phase":"preflight","check":"ses_account","status":"warn","msg":"account in sandbox; deployment will continue, request production access separately","cmd":"aws sesv2 put-account-details ..."}
{"phase":"cdk_bootstrap","status":"ok"}
{"phase":"deploy","stack":"AgentCommsData","status":"running","progress":0.3}
{"phase":"deploy","stack":"AgentCommsData","status":"ok"}
{"phase":"ses","check":"dkim","status":"waiting","msg":"submit DKIM CNAMEs via: agentcomms status"}
{"phase":"ses","check":"dkim","status":"ok","msg":"skipping poll in v0.1; run `agentcomms status` after DNS propagates"}
{"phase":"seed","status":"ok","org_id":"org_01H...","admin_api_key":"ak_live_...","note":"This key is shown once. Store it securely."}
{"phase":"smoke","status":"ok","msg":"smoke test skipped in v0.1; run `agentcomms status` to verify channels"}
{"phase":"done","status":"ok","api_url":"https://api.your-domain.com/v1","console_url":"https://console.your-domain.com","admin_email":"you@your-domain.com","admin_api_key":"ak_live_...","next_steps":["Create agents: agentcomms agents create --name MyAgent","Create agent-scoped keys: agentcomms keys create --scope agent --agent-id agt_... --name MyAgent","Store the admin API key securely."]}
```

All structured output goes to stdout. Human-readable progress goes to stderr. Pipe stdout through `jq` if you want to filter specific phases.

## Exit code contract

| Code | Meaning | Agent action |
|------|---------|--------------|
| 0 | Success | Parse `done` line, extract `admin_api_key`, proceed. |
| 1 | Preflight failure | Read `status` field of each `preflight` event. Fix the failing items. Retry. |
| 2 | CDK deploy failure | Check CloudFormation events in AWS console. Usually retriable with the same command. |
| 3 | SES DKIM verification timeout | DNS propagation slow. Wait 15 min, run `agentcomms status` — if DKIM is now OK, run `agentcomms bootstrap --resume`. |
| 4 | Smoke test failure | Deployment succeeded but end-to-end email round-trip failed. Needs human attention — bootstrap does NOT auto-rollback. Check CloudWatch logs for the email adapter Lambda. |

## Top-10 common failures (grep patterns + fixes)

### 1. `preflight: ses_account sandbox`
- Grep: `"check":"ses_account","status":"warn"`
- Cause: Your AWS account has SES in sandbox mode.
- Impact: You can still deploy AgentComms, but you can only send email to verified addresses until you request production access.
- Fix: `aws sesv2 put-account-details --production-access-enabled --mail-type TRANSACTIONAL --website-url https://your-domain.com --use-case-description "..." --contact-language EN --additional-contact-email-addresses you@your-domain.com`. Wait 24 hours for AWS approval.

### 2. `preflight: route53_zone not_found`
- Grep: `"check":"route53_zone","status":"fail"`
- Cause: No Route 53 hosted zone for the `--domain` you supplied.
- Fix: Create the zone — `aws route53 create-hosted-zone --name your-domain.com --caller-reference $(date +%s)` — OR point Route 53 delegation at an existing external DNS zone you control.

### 3. `deploy: AgentCommsData CREATE_FAILED s3 bucket already exists`
- Grep: `"status":"fail"` on a `deploy` phase line, CloudFormation error contains `BucketAlreadyExists`
- Cause: A previous partial deploy left S3 buckets. Bucket names are globally unique.
- Fix: `aws s3 ls | grep agentcomms-`, decide whether retained bucket contents are safe to remove, then delete the old buckets or choose a different domain/env configuration before retrying.

### 4. `deploy: Lambda Runtime.ImportModuleError`
- Grep: `Runtime.ImportModuleError` in CloudWatch logs or CDK output
- Cause: Docker bundling didn't install Python deps correctly. Common on M-series Macs.
- Fix: Restart Docker Desktop. `cd cdk && npx cdk deploy <FailedStack>`. If persistent, increase Docker file descriptor limit (see failure #9 below).

### 5. `ses: dkim timeout`
- Grep: `"check":"dkim","status":"fail","msg":"timeout"`
- Cause: DNS CNAMEs propagated slowly.
- Fix: `dig CNAME <token>._domainkey.your-domain.com`. If NXDOMAIN, wait. If resolving correctly, run `agentcomms status --json` and then rerun the same bootstrap command only if a stack failed.

### 6. `smoke: no delivery confirmation`
- Grep: `"phase":"smoke","status":"fail"`
- Cause: SES production access not granted OR recipient not verified in sandbox.
- Fix: Check SES console; verify the admin-email as an identity in sandbox OR request production access.

### 7. `preflight: iam insufficient`
- Grep: `"check":"iam","status":"fail"`
- Cause: The IAM user/role running bootstrap doesn't have CDK deploy permissions.
- Fix: Attach the CDK bootstrap role or grant `AdministratorAccess` to the bootstrapping principal (scope down after). Run `agentcomms doctor` for a detailed permissions report.

### 8. `cdk_bootstrap: already bootstrapped`
- Not an error. Normal if you've run CDK in this account/region before. Bootstrap continues to the deploy phase.

### 9. `deploy: too many open files`
- Grep: `EMFILE` or `too many open files` in CDK output
- Cause: macOS Docker file descriptor limit.
- Fix: `sudo sysctl -w kern.maxfiles=524288 kern.maxfilesperproc=524288`, then restart Docker Desktop.

### 10. `seed: admin_api_key lost`
- Cause: You lost the key printed in the NDJSON (it is printed exactly once and not stored by the CLI).
- Fix: If the CLI saved the key in `~/.agentcomms/config.json`, run `agentcomms keys create --scope org --name replacement-admin --json`. Then run `agentcomms keys list --json`, find the old key ID, and revoke it with `agentcomms keys revoke <key_id>`.

## Channels After Bootstrap

Bootstrap deploys the adapter infrastructure unless you omit adapters with `--skip-channels`. Per-agent channel identities are created through the API, SDKs, or MCP tools:

```bash
agentcomms agents create --name InvoiceBot
```

Then use `POST /v1/agents/{agent_id}/channels` or the SDK equivalent:

```python
client.agents("agt_...").channels.create(
    channel="email",
    config={"local_part": "invoice", "domain": "your-domain.com"},
)
```

Provider setup still happens outside AgentComms where the provider requires it:

- SMS: AWS End User Messaging and 10DLC approval are required before US numbers can send/receive.
- Slack: create a Slack app and store OAuth credentials in SSM under the documented `/agentcomms/{env}/adapters/slack/*` paths.
- Telegram: create a bot with BotFather and pass its token when provisioning.
- Push: configure APNs or FCM platform application credentials.
- Discord: adapter scaffold exists in `adapters/discord/`; the implementation is still open for contribution.

## Status check

After bootstrap, you can verify the deployment at any time:

```bash
agentcomms status --json
```

Returns a JSON object showing: CloudFormation stack statuses, SES identity verification, DKIM status, per-channel health, and the API URL.

## Teardown

```bash
agentcomms destroy --yes
```

Deletes CloudFormation stacks AND the DynamoDB table AND SNS/SQS/Kinesis resources. Does NOT delete S3 buckets (they're retained by default to protect against accidental data loss). Delete manually with `aws s3 rm s3://bucket-name --recursive && aws s3 rb s3://bucket-name` if you want them gone.

## Self-Hosting And Hosted Service

The canonical hosted `agentcomms.dev` service runs from the same open-source code and CDK app you deploy yourself. The hosted service competes on operations:

1. Victory's production AWS account + operational tuning
2. The `@agentcomms.dev` domain pool for email addresses
3. Victory's SES production sending reputation
4. Victory's 10DLC brand registration for SMS

You can self-host, fork, modify, redistribute, or operate your own hosted version under Apache-2.0.

## License

Apache-2.0. You can use AgentComms privately or commercially, self-host it, modify it, redistribute it, and build hosted services on top of it.

See [LICENSE](./LICENSE) and [docs/licensing.md](./docs/licensing.md).
