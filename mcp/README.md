# @agentcomms/mcp — Model Context Protocol server for AgentComms

Expose AgentComms operations to any MCP-compatible coding agent (Claude Desktop, Cursor, etc.).

## Install

    npm i -g @agentcomms/mcp

## Configure

    export AGENTCOMMS_API_KEY=ak_live_...
    export AGENTCOMMS_BASE_URL=https://api.agentcomms.dev/v1   # optional; defaults to this

## Use with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agentcomms": {
      "command": "agentcomms-mcp",
      "env": {
        "AGENTCOMMS_API_KEY": "ak_live_..."
      }
    }
  }
}
```

Restart Claude Desktop. Your agents can now call tools like `agent_create`, `message_send`, `vault_get_totp`, etc.

## Tools exposed

### Agents
| Tool | Description |
|------|-------------|
| `agent_list` | List all agents |
| `agent_create` | Create a new agent |
| `agent_get` | Get agent details |
| `agent_delete` | Delete an agent |

### Messages
| Tool | Description |
|------|-------------|
| `messages_list` | List messages for an agent |
| `message_get` | Get a single message |
| `message_send` | Send a message (channel auto-inferred) |
| `message_reply` | Reply to a message thread |
| `wait_for_message` | Long-poll for an incoming message |
| `extract_otp` | Extract OTP/verification code from a message |

### Channels
| Tool | Description |
|------|-------------|
| `channels_list` | List channels for an agent |
| `channel_create` | Provision a new channel |
| `channel_delete` | Delete a channel |

### Vault
| Tool | Description |
|------|-------------|
| `vault_list` | List vault entries |
| `vault_create` | Store a new secret |
| `vault_get` | Retrieve a vault entry |
| `vault_get_totp` | Get current TOTP code for a vault entry |
| `vault_delete` | Delete a vault entry |

### Personas
| Tool | Description |
|------|-------------|
| `persona_list` | List all personas |
| `persona_create` | Create a synthetic persona |
| `persona_associate` | Associate a persona with an agent |
| `persona_delete` | Delete a persona |

### AI
| Tool | Description |
|------|-------------|
| `ai_categorize` | Categorize a message using AI |
| `ai_extract` | Extract structured data from a message |
| `ai_summarize` | Summarize a message or thread |
| `ai_search` | Semantic search over agent messages |

## Build from source

```bash
npm install
npm run build
npm test
```

## License

FSL-1.1-Apache-2.0 — see repo root LICENSE.
