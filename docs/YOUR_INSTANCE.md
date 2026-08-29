# Your AgentComms Instance

Use this template after `agentcomms bootstrap` finishes. Paste only local/private deployment details into an untracked copy. Do not commit live API keys.

## Fill In

```text
API base URL:     https://<api-id>.execute-api.<region>.amazonaws.com/prod/v1
Clean API URL:    https://api.<your-domain>/v1
Console URL:      https://console.<your-domain>
Org ID:           org_...
Region:           us-east-1
Admin API key:    ak_live_...
```

## Verify

```bash
curl -sS "$AGENTCOMMS_BASE_URL/agents" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY"
```

Expected: `{"agents": [...]}`.

## MCP

Build from the repository:

```bash
cd mcp
npm install
npm run build
npm link
```

Claude Desktop config:

```json
{
  "mcpServers": {
    "agentcomms": {
      "command": "agentcomms-mcp",
      "env": {
        "AGENTCOMMS_API_KEY": "ak_live_YOUR_KEY",
        "AGENTCOMMS_BASE_URL": "https://api.<your-domain>/v1"
      }
    }
  }
}
```

## Create an Agent and Email Channel

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "MyAgent"}'
```

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/agt_.../channels" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "email",
    "mode": "provision",
    "config": {"local_part": "myagent", "domain": "<your-domain>"}
  }'
```

## Create a Scoped API Key

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/api-keys" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent-key", "scope": "agent", "agent_id": "agt_..."}'
```

The response includes the plaintext key once. Store it in your secret manager.

## Troubleshooting

- `401` means the API key is missing, malformed, revoked, expired, or from the wrong deployment.
- `403` usually means the key scope does not match the route.
- SES sandbox accounts can send only to verified recipients.
- Slack, Telegram, SMS, and push may need provider setup before end-to-end sends work.
