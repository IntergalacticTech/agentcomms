# AgentComms — Testing Plan

A structured walkthrough for verifying the live deployment. Takes ~45 minutes to run through all 11 sections; you can stop after Section 4 for a basic sanity check.

Target instance: the live **JWC Personal** deployment at `https://api.agentcomms.dev/v1/`.

---

## 0. Prerequisites

Before starting, confirm you have:

- A shell on your laptop (no AWS CLI required for most tests; only needed for Section 11)
- `curl` (stdlib on macOS/Linux; `winget install curl` on Windows)
- `python3` 3.10+ for the SDK section
- `npm` / Node 20+ for the CLI and Node SDK sections
- An org API key (generate one from the console or `POST /v1/api-keys`; placeholder shown as `ak_live_YOUR_ORG_KEY_HERE`). Never paste a live key into a tracked file.
- A real email address you can read inbound at (for the round-trip test in §5)

Paste these into your shell once — every section below assumes they're exported:

```bash
export AGENTCOMMS_API_KEY=ak_live_YOUR_ORG_KEY_HERE
export AGENTCOMMS_BASE_URL=https://api.agentcomms.dev/v1
export MY_EMAIL=you@example.com    # ← replace with an inbox you can read
```

---

## 1. Connectivity + auth (2 min)

Verify the API gateway responds, auth works, and your key is valid.

```bash
# 1a. Unauthenticated GET — should be 401
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "$AGENTCOMMS_BASE_URL/agents"
# expected: HTTP 401

# 1b. Bad key — should be 401
curl -sS -o /dev/null -w "HTTP %{http_code}\n" -H "Authorization: Bearer bogus" "$AGENTCOMMS_BASE_URL/agents"
# expected: HTTP 401

# 1c. Your key — should be 200 with JSON array of agents
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/agents" | python3 -m json.tool
# expected: {"agents": [{"agent_id": "agt_YOUR_AGENT_ID", "name": "jwc-first-agent"}]}
```

**Pass criteria:** HTTP 401 for both unauth cases, HTTP 200 with `jwc-first-agent` for the valid call.

**If this fails:** the API isn't live or your key is wrong. Skip everything below and tell me — either DNS regressed or the stack is broken.

---

## 2. One-command full smoke test (1 min)

The repo ships with a 15-check smoke test. Runs in ~20 seconds, creates + tears down test resources cleanly.

```bash
cd /path/to/FreeMail.ai    # your local repo clone
./tools/smoke_test_live.sh
```

**Pass criteria:** `SMOKE TEST PASSED: 15 / 15` at the bottom.

The 15 checks cover: auth surface (3), agent lifecycle (4), vault TOTP (2), personas (1), domains (1), webhook auth gates (2), cleanup (2).

**If this fails:** note which check failed and tail the relevant Lambda log group. Most common cause: CloudFront propagation race immediately after a deploy.

---

## 3. Agent creation + channel provisioning (5 min)

Create a fresh agent with email channel, confirm the provisioned email address is yours, delete it.

```bash
# 3a. Create an agent named after what you're doing with it
RESP=$(curl -sS -X POST \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"manual-test-agent",
    "provision":{"email":{"local_part":"test-'$(date +%s)'","domain":"victorymail.dev"}}
  }' \
  "$AGENTCOMMS_BASE_URL/agents")
echo "$RESP" | python3 -m json.tool

# Extract the agent_id for subsequent calls
AGENT_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['agent_id'])")
echo "Agent: $AGENT_ID"
```

**Pass criteria:** HTTP 201. Response has an `agent_id`, a `channels[0]` with `channel: "email"`, `status: "active"`, and a real `@victorymail.dev` address.

```bash
# 3b. Confirm it's in the list
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/agents" | python3 -m json.tool

# 3c. Inspect its channels
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/channels" | python3 -m json.tool

# 3d. Delete it
curl -sS -X DELETE -o /dev/null -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID"
# expected: HTTP 204

# 3e. Confirm it's gone
curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID"
# expected: HTTP 404
```

---

## 4. Outbound email — real round-trip (3 min)

Send a real email from your agent to your own inbox. Confirms SES sending works end-to-end.

```bash
# 4a. Send to your real email
curl -sS -X POST \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to":"'$MY_EMAIL'",
    "subject":"AgentComms test send",
    "body":"This is a live test from my agent at api.agentcomms.dev.\n\nIf you got this, outbound email works end-to-end."
  }' \
  "$AGENTCOMMS_BASE_URL/agents/agt_YOUR_AGENT_ID/messages" | python3 -m json.tool
```

**Pass criteria:** response has `"status": "sent"` and a non-empty `channel_native_id` (SES message ID starting with `01000`).

**Then check your inbox at `$MY_EMAIL`.** You should have an email from `jwc@victorymail.dev` within 30 seconds.

**If the response says `status: "failed"`:** tail the MessagesFn Lambda logs:
```bash
aws logs tail /aws/lambda/AgentCommsApi-MessagesFnD30972E8-LyFfZKoM2EUI --since 2m --region us-east-1
```
The most common cause is SES sandbox mode rejecting sends to unverified recipients. Fix: in the SES console, verify `$MY_EMAIL` as an email identity OR request SES production access (already enabled on this account, so this shouldn't be an issue).

---

## 5. Inbound email — KNOWN GAP

**This section is expected to fail** in the current deployment. Documenting so you know it's a gap, not a bug.

If you reply to the email from Section 4, the reply will NOT appear in your agent's unified inbox. Why: after the Phase 5 cutover, the SES `victorymail-inbound` receipt rule set was deactivated (it was pointing at the now-deleted `VictoryMail-Api` Lambda). No replacement receipt rule set was configured for either `victorymail.dev` or `agentcomms.dev`.

**To fix this later** (not required for most agent use cases that are outbound-driven):

1. Create SES identity for `agentcomms.dev`:
   ```bash
   aws sesv2 create-email-identity --email-identity agentcomms.dev --dkim-signing-attributes NextSigningKeyLength=RSA_2048_BIT
   ```
2. Publish DKIM CNAMEs + SPF + MX records to Route 53 zone `<YOUR_HOSTED_ZONE_ID>`.
3. Deploy a new SES receipt rule set that routes inbound to `AgentCommsApi-MessagesFn` (or to a dedicated ingest Lambda).
4. Activate the new rule set.

Est: 30-60 minutes of dev work. Tell me if/when you want this and I'll execute.

For now: **test everything else assuming outbound-only.**

---

## 6. Vault — TOTP + secret storage (5 min)

Store a real TOTP seed, generate codes server-side, verify against a known oracle.

```bash
# 6a. Create a TOTP vault entry. Seed JBSWY3DPEHPK3PXP is the canonical TOTP test vector.
VAULT_RESP=$(curl -sS -X POST \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type":"totp","label":"test-totp","seed":"JBSWY3DPEHPK3PXP"}' \
  "$AGENTCOMMS_BASE_URL/vault")
echo "$VAULT_RESP" | python3 -m json.tool

VAULT_ID=$(echo "$VAULT_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['vault_id'])")

# 6b. Fetch the current 6-digit code
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  "$AGENTCOMMS_BASE_URL/vault/$VAULT_ID/totp" | python3 -m json.tool
# expected: {"code": "######", "valid_until": ...}

# 6c. Verify against the canonical oracle
python3 -c "import pyotp; print(pyotp.TOTP('JBSWY3DPEHPK3PXP').now())"
# The two codes should match (same 30-second window).
```

**Pass criteria:** vault POST returns 201 with a `vault_id`; GET /totp returns a 6-digit `code` that matches `pyotp.TOTP(...).now()`; notice the response does NOT include the seed itself (seed never leaks).

```bash
# 6d. Store a password-type secret (any opaque value)
curl -sS -X POST \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type":"password","label":"github-pat","value":"ghp_test_placeholder"}' \
  "$AGENTCOMMS_BASE_URL/vault" | python3 -m json.tool

# 6e. List (metadata only — no encrypted blobs or plaintext)
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/vault" | python3 -m json.tool

# 6f. Cleanup
curl -sS -X DELETE -o /dev/null -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  "$AGENTCOMMS_BASE_URL/vault/$VAULT_ID"
# expected: HTTP 204
```

---

## 7. Personas (3 min)

```bash
# 7a. Create a persona (static data — no Bedrock call)
PERSONA_RESP=$(curl -sS -X POST \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Test Alice",
    "email":"alice@example.com",
    "phone":"+15551234567",
    "metadata":{"role":"tester"}
  }' \
  "$AGENTCOMMS_BASE_URL/personas")
echo "$PERSONA_RESP" | python3 -m json.tool

# 7b. Associate the persona with your primary agent
PERSONA_ID=$(echo "$PERSONA_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['persona_id'])")
curl -sS -X POST \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"persona_id\":\"$PERSONA_ID\"}" \
  "$AGENTCOMMS_BASE_URL/agents/agt_YOUR_AGENT_ID/personas" | python3 -m json.tool

# 7c. Cleanup
curl -sS -X DELETE -o /dev/null -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  "$AGENTCOMMS_BASE_URL/personas/$PERSONA_ID"
```

**Pass criteria:** create returns 201 with a `persona_id`, association returns 200, delete returns 204.

**Known limitation:** `generate: true` in the persona body (Bedrock-backed fake persona generation) returns **501 Not Implemented** until you grant Bedrock model access to the AWS account.

---

## 8. Domains (3 min)

```bash
# 8a. Register a custom domain — returns real SES DKIM tokens
curl -sS -X POST \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"domain_name":"manual-test-'$(date +%s)'.example"}' \
  "$AGENTCOMMS_BASE_URL/domains" | python3 -m json.tool
```

**Pass criteria:** HTTP 201, response includes 3 `dkim_tokens`, `dns_records` map with SPF/DMARC/MX, and `status: "pending_dns"`.

These DKIM tokens are real SES tokens — if you added the CNAMEs to the domain's DNS, SES would validate it and the domain would become usable for sending email on.

---

## 9. AI endpoints (2 min — partial; full test requires Bedrock grant)

```bash
# 9a. Search is keyword-based (works without Bedrock)
curl -sS -X POST \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"test"}' \
  "$AGENTCOMMS_BASE_URL/agents/agt_YOUR_AGENT_ID/ai/search" | python3 -m json.tool
# expected: HTTP 200 with empty results (no messages yet in inbox)
```

**Pass criteria:** HTTP 200 with `{"results": []}`.

**Categorize / Extract / Summarize** require Bedrock model access (Anthropic Claude 3 Haiku and Sonnet). These return **500 Internal Server Error** until access is granted. To enable: AWS Console → Amazon Bedrock → Model access → Request access for Claude 3 Haiku + Claude 3 Sonnet in us-east-1.

---

## 10. CLI + SDK usage (10 min)

### 10a. The `agentcomms` CLI

```bash
cd /path/to/FreeMail.ai/cli
npm install
npm run build
npm link                     # makes `agentcomms` available globally

# Preflight checks (no side effects)
agentcomms doctor --domain agentcomms.dev --json | head -10
# expected: NDJSON lines, most status:"ok"; ses_account may be warn (fine)

# Other subcommands
agentcomms --help
agentcomms version
```

### 10b. Python SDK

```bash
cd /path/to/FreeMail.ai
pip install -e sdks/python

python3 <<'EOF'
from agentcomms import Client
client = Client(
    api_key="ak_live_YOUR_ORG_KEY_HERE",
    base_url="https://api.agentcomms.dev/v1",
)
data = client._request("GET", "/agents")
print(f"Agents: {len(data['agents'])}")
for a in data["agents"]:
    print(f"  {a['agent_id']}: {a['name']}")
EOF
```

**Pass criteria:** prints at least one agent (`jwc-first-agent`).

### 10c. Node SDK

```bash
cd /path/to/FreeMail.ai/sdks/node
npm install
npm run build

node --input-type=module -e '
  import("./dist/index.js").then(async ({ Client }) => {
    const client = new Client({
      apiKey: "ak_live_YOUR_ORG_KEY_HERE",
      baseUrl: "https://api.agentcomms.dev/v1",
    });
    const data = await client.request("GET", "/agents");
    console.log("Agents:", data.agents.length);
    data.agents.forEach(a => console.log(" ", a.agent_id, a.name));
  });
'
```

**Pass criteria:** same agent list as Python.

### 10d. MCP server in Claude Desktop

```bash
cd /path/to/FreeMail.ai/mcp
npm install
npm run build
npm link
which agentcomms-mcp         # should print a path
```

Then add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agentcomms": {
      "command": "agentcomms-mcp",
      "env": {
        "AGENTCOMMS_API_KEY": "ak_live_YOUR_ORG_KEY_HERE",
        "AGENTCOMMS_BASE_URL": "https://api.agentcomms.dev/v1"
      }
    }
  }
}
```

Quit and restart Claude Desktop. In a new conversation, you should see 24 new tools when you open the tool panel: `agent_list`, `agent_create`, `agent_delete`, `messages_list`, `message_send`, `message_reply`, `wait_for_message`, `extract_otp`, `channels_list`, `channel_create`, `channel_delete`, `vault_list`, `vault_create`, `vault_get`, `vault_get_totp`, `vault_delete`, `persona_list`, `persona_create`, `persona_associate`, `persona_delete`, `ai_categorize`, `ai_extract`, `ai_summarize`, `ai_search`.

**Pass criteria:** try asking Claude "list my agents in agentcomms" — it should call `agent_list` and show your `jwc-first-agent`.

---

## 11. Infrastructure sanity (5 min, requires AWS CLI + creds loaded)

```bash
# 11a. All four CloudFormation stacks are healthy
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query "StackSummaries[?starts_with(StackName,'AgentComms')].StackName" \
  --output text
# expected: AgentCommsApi  AgentCommsAdapters  AgentCommsEvents  AgentCommsData

# 11b. The agentcomms DynamoDB table has only legit orgs
aws dynamodb scan --table-name agentcomms \
  --filter-expression "SK = :meta" \
  --expression-attribute-values '{":meta":{"S":"META"}}' \
  --query "Items[].{name:name.S,pk:PK.S}" --output table
# expected: 2 rows — "Victory (Phase 1 Test)" and "JWC Personal"

# 11c. DNS for all three agentcomms.dev endpoints
for host in agentcomms.dev console.agentcomms.dev api.agentcomms.dev; do
  ip=$(dig +short "$host" @1.1.1.1 | head -1)
  echo "  $host → $ip"
done
# expected: 3 IPs, all CloudFront (start 13.x.x.x / 3.x.x.x) or API Gateway (100.x)

# 11d. ACM cert is ISSUED
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:<region>:<YOUR_ACCOUNT_ID>:certificate/<YOUR_ACM_CERT_ID> \
  --query "Certificate.Status"
# expected: "ISSUED"
```

**Pass criteria:** all four pass. If any regress, `python tools/finalize_agentcomms_dns.py` re-runs the manual setup idempotently.

---

## Failure diagnostics quick reference

| Symptom | Most likely cause | Fix |
|---|---|---|
| HTTP 500 on a handler endpoint | Lambda missing IAM permission for a downstream service | `aws logs tail /aws/lambda/AgentCommsApi-<FnName>Fn* --since 3m` and grep for `AccessDenied` |
| HTTP 401 with valid key | Authorizer cache returned stale policy — bust with a different URL path first, or wait 5 min | — |
| Email `status: "failed"` | SES sandbox + unverified recipient | Verify recipient in SES console, or request prod access (already granted) |
| `console.agentcomms.dev` DNS doesn't resolve | CloudFront alternate-domain-name authorization cache stale after a distribution change | wait 10-30 min, or run `python tools/finalize_agentcomms_dns.py` to re-kick |
| `agentcomms` CLI hangs on bootstrap preflight | Docker not running or Route 53 zone missing | `docker info`, check zone exists |
| Bedrock-backed features 500 | Model access not granted | AWS Console → Bedrock → Model access → request Claude 3 Haiku + Sonnet |

---

## Post-test cleanup

The smoke test script (Section 2) cleans up its own resources. For any agents, vault entries, personas, or domains you create manually during testing, delete them to keep your org clean:

```bash
# List what's under your org
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/agents" | python3 -m json.tool
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/vault" | python3 -m json.tool
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/personas" | python3 -m json.tool
curl -sS -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/domains" | python3 -m json.tool

# Delete as needed:
# curl -sS -X DELETE -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/agents/agt_..."
# curl -sS -X DELETE -H "Authorization: Bearer $AGENTCOMMS_API_KEY" "$AGENTCOMMS_BASE_URL/vault/vlt_..."
# etc.
```

---

## What's intentionally NOT tested here

The following require external setup before testing makes sense:

- **Inbound email** — no SES receipt rule set active. See §5.
- **SMS** — 10DLC brand registration pending. Route exists but provisioning will fail until brand+campaign registered.
- **Slack OAuth** — placeholder credentials in SSM. OAuth URL generates but callback returns error until a real Slack app is registered.
- **Telegram** — works if you provision with a real `bot_token` from BotFather. Same path as tested in §3, just pass `provision: {"telegram": {"bot_token": "..."}}`.
- **Push (APNs/FCM)** — no platform application credentials. Route exists but push will fail on send.
- **Bedrock AI** — see §9.

Each has a `docs/adapters/<channel>.md` stub with setup steps.

---

## Scoring

- **Minimum pass:** §§ 1, 2, 3, 4 complete green. That's the core hub + outbound email + lifecycle — enough for agents to send but not receive.
- **Full pass:** §§ 1-11 all green (modulo the explicit gaps in §5, §9). Signals the deployment is production-ready for outbound-driven agent workflows.
- **Nothing-works pass:** §1 fails. Stop and escalate.

Tell me your scoring row for each section when you run through it — I'll triage anything that doesn't match the expected output.
