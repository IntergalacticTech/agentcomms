# MCP Server Guide

The AgentComms MCP server exposes the hub API as tools that coding agents can call directly. It is the fastest path for an AI agent to create an identity, read a unified inbox, send replies, wait for messages, extract OTP codes, and manage channel-specific surfaces.

## Install

```bash
npm i -g @agentcomms/mcp
```

Or build from this repository:

```bash
cd mcp
npm install
npm run build
```

## Configure

| Variable | Required | Description |
|---|---|---|
| `AGENTCOMMS_API_KEY` | Yes | AgentComms API key, for example `ak_live_...` |
| `AGENTCOMMS_BASE_URL` | No | API base URL. Defaults to `https://api.agentcomms.dev/v1` |

Claude Desktop example:

```json
{
  "mcpServers": {
    "agentcomms": {
      "command": "agentcomms-mcp",
      "env": {
        "AGENTCOMMS_API_KEY": "ak_live_YOUR_KEY",
        "AGENTCOMMS_BASE_URL": "https://api.agentcomms.dev/v1"
      }
    }
  }
}
```

For a source checkout, set `command` to `node` and `args` to the built `mcp/dist/index.js` path.

## Tool Groups

| Group | Tools |
|---|---|
| Agents | `agent_list`, `agent_create`, `agent_get`, `agent_delete` |
| Messages | `messages_list`, `message_get`, `message_send`, `message_reply`, `wait_for_message`, `extract_otp` |
| Channels | `channels_list`, `channel_create`, `channel_delete` |
| Vault | `vault_list`, `vault_create`, `vault_get`, `vault_get_totp`, `vault_delete` |
| Personas | `persona_list`, `persona_create`, `persona_associate`, `persona_delete` |
| AI | `ai_categorize`, `ai_extract`, `ai_summarize`, `ai_search` |

## Common Workflows

Create an agent:

```json
{
  "tool": "agent_create",
  "arguments": {
    "name": "InvoiceBot",
    "provision": {
      "email": { "local_part": "invoice", "domain": "example.com" }
    }
  }
}
```

List the unified inbox:

```json
{
  "tool": "messages_list",
  "arguments": {
    "agent_id": "agt_...",
    "channels": ["email", "slack"],
    "limit": 25
  }
}
```

Send or reply:

```json
{
  "tool": "message_send",
  "arguments": {
    "agent_id": "agt_...",
    "to": "alice@example.com",
    "subject": "Status",
    "body": "Done."
  }
}
```

```json
{
  "tool": "message_reply",
  "arguments": {
    "agent_id": "agt_...",
    "message_id": "msg_...",
    "body": "Got it, processing."
  }
}
```

Provision a channel:

```json
{
  "tool": "channel_create",
  "arguments": {
    "agent_id": "agt_...",
    "channel": "telegram",
    "mode": "provision",
    "config": {
      "bot_token": "..."
    }
  }
}
```

## Troubleshooting

`AGENTCOMMS_API_KEY not set` means the MCP host did not pass the environment variable to the process. Put the variable in the MCP host config, not only in your shell profile.

If tools do not appear, run `cd mcp && npm run build && npm test`, then restart the MCP host.

`wait_for_message` and `extract_otp` are bounded long polls. For production workflows that need reliable asynchronous delivery, subscribe to webhooks or consume the event stream instead of looping forever in an MCP client.

## License

Apache-2.0. See [LICENSE](../LICENSE).
