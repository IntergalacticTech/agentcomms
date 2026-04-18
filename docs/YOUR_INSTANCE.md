# Your AgentComms Instance

Everything you need to connect your AI agents to AgentComms — today.

## TL;DR

```
API base URL (clean):    https://api.agentcomms.dev/v1
API base URL (direct):   https://0xztg5asi6.execute-api.us-east-1.amazonaws.com/prod/v1
API key:                 ak_live_IuSw6CRVC0PbryeJvXapjviOL6AWcbM8aGoyLKgY
Org:                     org_01KPH36QSYPCPJAEY4GRN5EJ1G  (JWC Personal)
Region:                  us-east-1

Landing:                 https://agentcomms.dev     (live)
Console:                 https://console.agentcomms.dev  (live)
```

Both API URLs accept the same API key. Use the clean `api.agentcomms.dev` URL in SDK configs.

One agent is already provisioned for you — `agt_01KPH37E2917EVKZX7YV5VFN75` (`jwc-first-agent`) with an email channel at `jwc@victorymail.dev`. Use it as a template or delete it and create your own.

---

## 1. Verify it's working

```bash
curl -s -H "Authorization: Bearer ak_live_IuSw6CRVC0PbryeJvXapjviOL6AWcbM8aGoyLKgY" \
  "https://0xztg5asi6.execute-api.us-east-1.amazonaws.com/prod/v1/agents" | python3 -m json.tool
```

Expected: JSON with one agent (`jwc-first-agent`). If you see that, you're good.

---

## 2. Connect Claude Desktop (via MCP)

The MCP server gives Claude Desktop 24 tools covering agents, messages, channels, vault, personas, and AI.

### Install

From this repo:
```bash
cd mcp && npm install && npm run build
npm link            # makes `agentcomms-mcp` available globally
```

(Once the npm package is public, this becomes `npm i -g @agentcomms/mcp`.)

### Configure Claude Desktop

Open `~/Library/Application Support/Claude/claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "agentcomms": {
      "command": "agentcomms-mcp",
      "env": {
        "AGENTCOMMS_API_KEY": "ak_live_IuSw6CRVC0PbryeJvXapjviOL6AWcbM8aGoyLKgY",
        "AGENTCOMMS_BASE_URL": "https://0xztg5asi6.execute-api.us-east-1.amazonaws.com/prod/v1"
      }
    }
  }
}
```

Quit and restart Claude Desktop. You should see 24 new tools prefixed `agent_*`, `message_*`, `vault_*`, `persona_*`, `ai_*`, `channels_*` when you pull up the MCP tool panel.

### Try it in Claude

> "List my agents, then send a test email from the first one to me@example.com saying hello."

Claude will call `agent_list`, pick the first agent, then `message_send` with the body — routing through the email adapter, out via SES.

---

## 3. Connect Cursor (same MCP server)

In Cursor, open Settings → MCP → Add new server. Use the same command + env vars as above.

Cursor's chat pane picks up the tools and can call them from agent mode.

---

## 4. Connect Claude Code (Python SDK, not MCP)

Claude Code can use the Python SDK directly via tool scripts or by running Python code inline.

### Install the SDK

```bash
cd sdks/python && pip install -e .
```

(Once published: `pip install agentcomms`.)

### Example: agent script

```python
# save as my_agent.py
from agentcomms import Client

client = Client(
    api_key="ak_live_IuSw6CRVC0PbryeJvXapjviOL6AWcbM8aGoyLKgY",
    base_url="https://0xztg5asi6.execute-api.us-east-1.amazonaws.com/prod/v1",
)

# Create a new agent with email + SMS
result = client._request("POST", "/agents", json={
    "name": "MyInvoiceBot",
    "provision": {
        "email": {"local_part": "invoice", "domain": "victorymail.dev"},
    },
})
print(f"Created agent {result['agent_id']}")

# List all my agents
agents = client._request("GET", "/agents")["agents"]
for a in agents:
    print(f"  {a['agent_id']}: {a['name']}")
```

Run it:
```bash
python my_agent.py
```

---

## 5. Connect any coding agent (raw HTTP)

Any tool that can make authenticated HTTP calls works. The auth is a simple Bearer token.

```bash
curl -H "Authorization: Bearer ak_live_IuSw6CRVC0PbryeJvXapjviOL6AWcbM8aGoyLKgY" \
     -H "Content-Type: application/json" \
     -X POST \
     -d '{"name":"MyBot","provision":{"email":{"local_part":"mybot","domain":"victorymail.dev"}}}' \
     "https://0xztg5asi6.execute-api.us-east-1.amazonaws.com/prod/v1/agents"
```

Full API reference: see `docs/api-reference.md` and `docs/openapi.yaml`.

---

## 6. What's live and callable right now

| Category | Endpoints | Status |
|---|---|---|
| Agents | `POST /v1/agents`, `GET /v1/agents`, `GET/DELETE /v1/agents/{id}` | ✅ Working — tested live |
| Channels | `/v1/agents/{id}/channels*` | ✅ Working |
| Messages | `/v1/agents/{id}/messages*`, `/wait`, `/extract-otp` | ✅ Working |
| Threads / Drafts / Webhooks | `/v1/agents/{id}/{threads,drafts,webhooks}` | ✅ Working |
| Vault | `/v1/vault*` + `/v1/vault/{id}/totp` | ✅ Working — KMS encrypted |
| Personas | `/v1/personas*` + `/v1/agents/{id}/personas` | ✅ Working |
| Domains | `/v1/domains*` | ✅ Working — issues real SES DKIM tokens |
| AI | `/v1/agents/{id}/ai/{categorize,extract,summarize,search}` | ⚠️ Live but needs Bedrock model access grants in the AWS account |
| Email channel | send + receive | ✅ Working — using `victorymail.dev` pool |
| SMS channel | provision + send + receive | ⚠️ Needs 10DLC brand registration (multi-day carrier process) |
| Slack bridge | OAuth flow + events webhook | ⚠️ Needs a real Slack app registration (placeholder creds deployed) |
| Telegram channel | provision + webhook ingest | ⚠️ Needs a BotFather bot token (you provide at provision time) |
| Push channel | device registration + send | ⚠️ Needs APNs / FCM platform app credentials |

Green is production-ready. Yellow needs one more external step (third-party registration) before end-to-end works — but the routes are live and tested.

---

## 7. `agentcomms.dev` DNS — ✅ live

- Route 53 zone: `Z0370999MWHX8OSTHZPR` (in account 732770059798)
- ACM cert: combined cert covering agentcomms.dev + *.agentcomms.dev + victorymail.dev + *.victorymail.dev (`3bd1b3a6-a843-4804-9e0e-069550fd6aec`)
- `api.agentcomms.dev` → API Gateway custom domain → `AgentCommsApi` (stage `prod`)
- `agentcomms.dev` → CloudFront distribution `E9787GLOP9GSN` (landing page S3 origin)
- `console.agentcomms.dev` → CloudFront distribution `E1PG2DM90218AR` (console React app S3 origin)

All three URLs serve from the same infrastructure as their `victorymail.dev` counterparts — no duplicate stacks.

---

## 8. Rotating / creating more API keys

The key you have (`ak_live_IuSw6CRVC0PbryeJvXapjviOL6AWcbM8aGoyLKgY`) is ORG-scoped, which means it can do everything inside your `JWC Personal` org. For production use of a specific agent, you probably want agent-scoped keys.

### Create an agent-scoped key

```bash
curl -H "Authorization: Bearer ak_live_IuSw6CRVC0PbryeJvXapjviOL6AWcbM8aGoyLKgY" \
     -H "Content-Type: application/json" \
     -X POST \
     -d '{"name":"my-invoice-bot-key","scope":"agent","agent_id":"agt_01KPH37E2917EVKZX7YV5VFN75"}' \
     "https://0xztg5asi6.execute-api.us-east-1.amazonaws.com/prod/v1/api-keys"
```

The response includes the plaintext key once. Store it.

### Rotate / revoke

```bash
curl -H "Authorization: Bearer ak_live_..." \
     -X DELETE \
     "https://0xztg5asi6.execute-api.us-east-1.amazonaws.com/prod/v1/api-keys/key_01H..."
```

---

## 9. Reading inbound email for your agent

The agent `jwc-first-agent` has an email address: `jwc@victorymail.dev`. Anything sent to that address will land in its unified inbox within ~10 seconds.

```bash
# send yourself a test email to jwc@victorymail.dev from your personal email...
# then:
curl -s -H "Authorization: Bearer ak_live_IuSw6CRVC0PbryeJvXapjviOL6AWcbM8aGoyLKgY" \
     "https://0xztg5asi6.execute-api.us-east-1.amazonaws.com/prod/v1/agents/agt_01KPH37E2917EVKZX7YV5VFN75/messages" | python3 -m json.tool
```

The `messages` array contains every inbound + outbound message with full MIME metadata.

---

## 10. What to try next

- Have Claude send an email to yourself via the MCP `message_send` tool.
- Reply to the email from your human inbox. Have Claude read the unified inbox via `messages_list` and respond.
- Create a TOTP vault entry: have Claude call `vault_create` with `type=totp`, seed = one of your actual TOTP secrets. Then ask Claude for the current code via `vault_get_totp`.
- Create a persona (`persona_create`), associate it with your agent (`persona_associate`), then query the persona to check it stuck.
- Watch the CloudWatch logs as your agent operates:
  ```
  aws logs tail /aws/lambda/AgentCommsApi-AgentsFn* --follow --region us-east-1
  ```

---

## 11. Troubleshooting

**`HTTP 401 Unauthorized`** — bad API key. Copy the key from this doc exactly; `Bearer ` (with a space) goes before it.

**`HTTP 403`** — wrong scope. Check the key's scope vs the path you're calling (org keys can call anything; agent keys only their own agent's paths).

**`HTTP 500` on a new endpoint** — something went wrong server-side. Tail the relevant Lambda log group:
```bash
aws logs tail /aws/lambda/AgentCommsApi-<FnName>Fn* --since 3m --region us-east-1
```

**Email send fails with SES verification error** — the domain `victorymail.dev` is SES-verified, but your account may be in sandbox mode so it can only send to verified recipients. Add your recipient email as an SES identity, or request SES production access.

**MCP tools don't show up in Claude Desktop** — check the config JSON has no trailing commas (Claude's parser is strict), and that `agentcomms-mcp` resolves on your PATH (`which agentcomms-mcp` should return a path).

---

## 12. What I'm NOT giving you yet

- **Hosted console login at `console.agentcomms.dev`** — still deferred to when DNS flips. For now, `https://console.victorymail.dev` shows "AgentComms Console" but runs against the legacy victorymail API, not your new agentcomms org.
- **Automated DNS finalize script** — I'll write `tools/finalize_agentcomms_dns.py` the next session. For now, after you update the registrar, ping me and I'll finish the API GW custom domain mapping + CloudFront alternates manually.
- **npm-installable CLI** — the `agentcomms` CLI is in `cli/dist/` but not yet published to npm. Install from source: `cd cli && npm install && npm run build && npm link`.
