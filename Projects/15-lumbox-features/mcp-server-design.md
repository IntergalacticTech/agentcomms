# MCP Server Design Document

Complete specification for the AgentMail MCP (Model Context Protocol) server -- the primary interface through which AI agents interact with email.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Installation and Configuration](#2-installation-and-configuration)
3. [Transport Modes](#3-transport-modes)
4. [Complete Tool Definitions](#4-complete-tool-definitions)
5. [Tool Implementation Architecture](#5-tool-implementation-architecture)
6. [Error Handling](#6-error-handling)
7. [Security](#7-security)
8. [Development and Publishing](#8-development-and-publishing)
9. [Example AI Agent Workflows](#9-example-ai-agent-workflows)

---

## 1. Overview

### What is MCP?

The **Model Context Protocol (MCP)** is an open standard created by Anthropic that defines how AI models communicate with external tools and data sources. MCP provides a structured JSON-RPC 2.0 interface where a **server** exposes a set of **tools** (callable functions with typed input/output schemas) and optional **resources** (read-only data). An MCP **client** -- typically an AI assistant runtime like Claude Code, Cursor, or a custom agent framework -- discovers these tools at startup and can invoke them as part of its reasoning loop.

MCP replaces ad-hoc function-calling integrations with a standardized protocol. The server declares its capabilities, the client inspects them, and the model decides when and how to use each tool based on the user's intent and the tool descriptions.

### Why AgentMail Needs an MCP Server

AgentMail's primary users are AI agents, not humans. Our REST API is designed for programmatic access, but AI agents interact through natural language. An MCP server bridges this gap:

1. **Zero-code integration**: An agent running in Claude Code or Cursor can send, receive, and manage email without the user writing any code. The agent discovers the tools and uses them conversationally.
2. **Discovery over documentation**: Instead of reading API docs, the AI model reads tool descriptions and JSON Schemas at context load time. It knows exactly what parameters each tool accepts and what it returns.
3. **Compound actions**: MCP tools can orchestrate multi-step API workflows (create inbox, wait for email, extract OTP) as single tool calls, which is how agents naturally think about tasks.
4. **Competitive differentiation**: Lumbox, our closest competitor, does not offer an MCP server. This makes AgentMail the first email platform natively accessible to AI agents through the standard protocol that Claude, Cursor, Windsurf, and other agent runtimes support.
5. **Ecosystem positioning**: As MCP adoption grows across the AI tooling ecosystem, being a first-class MCP server means AgentMail appears in tool registries, marketplace listings, and agent templates.

### Package Identity

| Distribution | Package Name | Registry |
|-------------|-------------|----------|
| Node.js (primary) | `@agentmail/mcp-server` | npm |
| Python (wrapper) | `agentmail-mcp` | PyPI |
| Docker | `ghcr.io/agentmail/mcp-server` | GitHub Container Registry |

The MCP server runs as a **local process** on the developer's machine (or in a container). It connects outbound to the AgentMail REST API at `https://api.agentmail.aws`. It does not listen on any port in stdio mode -- it communicates with the MCP client exclusively through stdin/stdout.

### Protocol Version

The server implements MCP protocol version `2024-11-05` (latest stable). It declares the following server capabilities during initialization:

```json
{
  "protocolVersion": "2024-11-05",
  "capabilities": {
    "tools": {},
    "resources": {}
  },
  "serverInfo": {
    "name": "agentmail",
    "version": "1.0.0"
  }
}
```

---

## 2. Installation and Configuration

### Prerequisites

- Node.js 18+ (for npx execution)
- An AgentMail API key (obtain from the developer console or via `POST /agent/signup` + `POST /agent/verify`)

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENTMAIL_API_KEY` | Yes | -- | API key in format `am_live_...` or `am_test_...` |
| `AGENTMAIL_API_URL` | No | `https://api.agentmail.aws` | Base URL for the AgentMail REST API |
| `AGENTMAIL_DEFAULT_INBOX` | No | -- | Default inbox ID to use when inbox_id is omitted from tool calls |
| `AGENTMAIL_LOG_LEVEL` | No | `warn` | Logging level: `debug`, `info`, `warn`, `error`, `silent` |
| `AGENTMAIL_TIMEOUT` | No | `300000` | Default HTTP request timeout in milliseconds |
| `AGENTMAIL_TRANSPORT` | No | `stdio` | Transport mode: `stdio`, `sse`, `streamable-http` |
| `AGENTMAIL_PORT` | No | `3100` | Port for SSE and Streamable HTTP transports |

### Claude Code

The simplest installation. Run once:

```bash
claude mcp add agentmail -- npx @agentmail/mcp-server
```

This registers the MCP server in Claude Code's configuration. The API key must be set in the shell environment (e.g., in `.bashrc`, `.zshrc`, or a `.env` file that Claude Code sources).

To pass the API key explicitly:

```bash
claude mcp add agentmail \
  --env AGENTMAIL_API_KEY=am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL \
  -- npx @agentmail/mcp-server
```

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "agentmail": {
      "command": "npx",
      "args": ["@agentmail/mcp-server"],
      "env": {
        "AGENTMAIL_API_KEY": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL",
        "AGENTMAIL_API_URL": "https://api.agentmail.aws"
      }
    }
  }
}
```

Restart Claude Desktop after saving. The AgentMail tools appear in the tool list immediately.

### Cursor

Create `.cursor/mcp.json` in the project root (or `~/.cursor/mcp.json` for global):

```json
{
  "mcpServers": {
    "agentmail": {
      "command": "npx",
      "args": ["@agentmail/mcp-server"],
      "env": {
        "AGENTMAIL_API_KEY": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL"
      }
    }
  }
}
```

### VS Code (Copilot MCP)

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "agentmail": {
      "command": "npx",
      "args": ["@agentmail/mcp-server"],
      "env": {
        "AGENTMAIL_API_KEY": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL"
      }
    }
  }
}
```

### JetBrains IDEs (AI Assistant MCP)

Add to the JetBrains MCP configuration (Settings > Tools > AI Assistant > MCP Servers):

```json
{
  "mcpServers": {
    "agentmail": {
      "command": "npx",
      "args": ["@agentmail/mcp-server"],
      "env": {
        "AGENTMAIL_API_KEY": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL"
      }
    }
  }
}
```

### Windsurf

Create `.windsurf/mcp.json` in the project root:

```json
{
  "mcpServers": {
    "agentmail": {
      "command": "npx",
      "args": ["@agentmail/mcp-server"],
      "env": {
        "AGENTMAIL_API_KEY": "am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL"
      }
    }
  }
}
```

### Docker (for remote/SSE deployments)

```bash
docker run -d \
  -e AGENTMAIL_API_KEY=am_live_7kB3mN9pQ2rX5vW8yA1cD4eF6gH0jL \
  -e AGENTMAIL_TRANSPORT=sse \
  -e AGENTMAIL_PORT=3100 \
  -p 3100:3100 \
  ghcr.io/agentmail/mcp-server:latest
```

### Custom Agent Frameworks

For programmatic use in Python/Node.js agent frameworks:

**Python (using subprocess):**

```python
import subprocess
import json

proc = subprocess.Popen(
    ["npx", "@agentmail/mcp-server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    env={**os.environ, "AGENTMAIL_API_KEY": "am_live_..."},
)
# Send JSON-RPC messages to proc.stdin, read from proc.stdout
```

**Python (using agentmail-mcp package):**

```python
pip install agentmail-mcp
```

```python
from agentmail_mcp import AgentMailMCPServer

server = AgentMailMCPServer(api_key="am_live_...")
server.start()  # Starts the Node.js process internally
```

**Node.js (using @modelcontextprotocol/sdk):**

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transport = new StdioClientTransport({
  command: "npx",
  args: ["@agentmail/mcp-server"],
  env: { AGENTMAIL_API_KEY: "am_live_..." },
});

const client = new Client({ name: "my-agent", version: "1.0.0" });
await client.connect(transport);

const tools = await client.listTools();
const result = await client.callTool({
  name: "create_inbox",
  arguments: { display_name: "My Agent" },
});
```

---

## 3. Transport Modes

The MCP server supports three transport modes. The transport is selected via the `--transport` CLI flag or the `AGENTMAIL_TRANSPORT` environment variable.

### stdio (Default)

```bash
npx @agentmail/mcp-server --transport stdio
```

- **How it works**: The server reads JSON-RPC messages from stdin and writes responses to stdout. Each message is delimited by a newline. Diagnostic output goes to stderr.
- **Use cases**: Local MCP clients (Claude Code, Cursor, VS Code, JetBrains). This is the standard transport for locally-run MCP servers.
- **Advantages**: No network ports, no firewall concerns, no authentication beyond the process environment. The MCP client spawns the server as a child process and communicates directly.
- **Limitations**: Single client only. Cannot be shared across multiple MCP clients simultaneously.

### SSE (Server-Sent Events)

```bash
npx @agentmail/mcp-server --transport sse --port 3100
```

- **How it works**: The server starts an HTTP server on the specified port. Clients connect via `GET /sse` to establish a Server-Sent Events stream for server-to-client messages, and send requests via `POST /message`. The server assigns a session ID to each connection.
- **Use cases**: Remote MCP clients, web-based agent UIs, shared team servers, Docker deployments.
- **Advantages**: Multiple clients can connect simultaneously. Works across network boundaries. Compatible with web browsers.
- **Limitations**: Requires network port exposure. Should be placed behind a reverse proxy with TLS in production.
- **Authentication**: The server validates an `Authorization: Bearer <token>` header on the SSE and message endpoints. The token is the AgentMail API key or a separate MCP access token configured via `AGENTMAIL_MCP_TOKEN`.

### Streamable HTTP

```bash
npx @agentmail/mcp-server --transport streamable-http --port 3100
```

- **How it works**: Uses the newer MCP Streamable HTTP transport. The server exposes a single `POST /mcp` endpoint. Requests are standard HTTP POST with JSON-RPC bodies. Responses can be either immediate JSON responses or streamed via SSE when the response is long-running (e.g., `wait_for_email`). The server supports session management via the `Mcp-Session-Id` header.
- **Use cases**: Modern MCP clients that support the streamable HTTP transport. Preferred over SSE for new integrations.
- **Advantages**: Simpler than SSE (single endpoint). Supports both synchronous and streaming responses. Better proxy and load balancer compatibility.
- **Limitations**: Not yet supported by all MCP clients (as of early 2026).

### CLI Flags

```
Usage: @agentmail/mcp-server [options]

Options:
  --transport <mode>    Transport mode: stdio, sse, streamable-http (default: stdio)
  --port <number>       Port for SSE/HTTP transports (default: 3100)
  --host <string>       Bind address for SSE/HTTP transports (default: 127.0.0.1)
  --api-key <string>    AgentMail API key (overrides AGENTMAIL_API_KEY env var)
  --api-url <string>    AgentMail API URL (overrides AGENTMAIL_API_URL env var)
  --log-level <level>   Log level: debug, info, warn, error, silent (default: warn)
  --version             Show version number
  --help                Show help
```

---

## 4. Complete Tool Definitions

This section specifies every tool exposed by the MCP server. Each tool includes:

- **Name**: The tool identifier used in MCP `tools/call` requests
- **Description**: Natural language description the AI model reads to decide when to use the tool
- **Input Schema**: Complete JSON Schema for the tool's parameters
- **Output**: Description of the return value
- **REST API Mapping**: The underlying API endpoint(s)

Tools are organized by category. Total tool count: **43 tools**.

---

### 4.1 Inbox Management (6 tools)

#### `create_inbox`

Create a new email inbox. Returns the inbox details including the generated email address.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "email": {
      "type": "string",
      "description": "Desired email address (e.g., 'agent-47@mail.acme.com'). If omitted, a random address is generated on the default domain."
    },
    "display_name": {
      "type": "string",
      "description": "Display name for outbound emails (e.g., 'Support Agent 47')."
    },
    "pod_id": {
      "type": "string",
      "description": "Pod ID to assign the inbox to. Uses the default pod if omitted."
    },
    "domain": {
      "type": "string",
      "description": "Domain to create the inbox on. Uses the org's default domain if omitted."
    }
  },
  "required": [],
  "additionalProperties": false
}
```

**Output:** Full inbox object including `id`, `email`, `display_name`, `status`, `created_at`.

**REST API Mapping:** `POST /v1/inboxes`

**Example usage:**

```
User: "Create a new inbox for my GitHub signup"
Agent calls: create_inbox({display_name: "GitHub Signup Agent"})
Returns: {id: "01HXYZ...", email: "agent-a7k3m@inbox.agentmail.dev", ...}
```

---

#### `list_inboxes`

List all email inboxes in the organization. Supports pagination.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "description": "Maximum number of inboxes to return (1-100).",
      "default": 25,
      "minimum": 1,
      "maximum": 100
    },
    "page_token": {
      "type": "string",
      "description": "Pagination cursor from a previous response's next_page_token."
    },
    "pod_id": {
      "type": "string",
      "description": "Filter inboxes by pod ID."
    },
    "domain": {
      "type": "string",
      "description": "Filter inboxes by domain."
    },
    "status": {
      "type": "string",
      "enum": ["active", "paused", "deleted"],
      "description": "Filter by inbox status."
    }
  },
  "required": [],
  "additionalProperties": false
}
```

**Output:** Paginated list of inbox objects with `data`, `next_page_token`, `has_more`.

**REST API Mapping:** `GET /v1/inboxes`

---

#### `get_inbox`

Get detailed information about a specific inbox.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID (ULID)."
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output:** Full inbox object including `id`, `email`, `display_name`, `status`, `message_count`, `unread_count`, `settings`, `forwarding`, `created_at`.

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}`

---

#### `update_inbox`

Update an inbox's display name, settings, or forwarding configuration.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to update."
    },
    "display_name": {
      "type": "string",
      "description": "New display name for outbound emails."
    },
    "settings": {
      "type": "object",
      "description": "Inbox settings to update (partial update -- only specified fields change).",
      "properties": {
        "auto_reply_enabled": { "type": "boolean" },
        "auto_reply_body": { "type": "string" },
        "categorization_enabled": { "type": "boolean" },
        "spam_filter_level": {
          "type": "string",
          "enum": ["off", "low", "normal", "aggressive"]
        }
      }
    },
    "forwarding": {
      "type": "object",
      "description": "Forwarding configuration.",
      "properties": {
        "enabled": { "type": "boolean" },
        "address": { "type": "string" }
      }
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output:** Full updated inbox object.

**REST API Mapping:** `PATCH /v1/inboxes/{inbox_id}`

---

#### `delete_inbox`

Delete an inbox and all its messages. This is a soft delete -- the inbox enters 'deleted' status and is permanently purged after the retention period.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to delete."
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output:** Confirmation message. No content returned (HTTP 204).

**REST API Mapping:** `DELETE /v1/inboxes/{inbox_id}`

---

#### `get_inbox_by_address`

Find an inbox by its email address. Useful when you know the address but not the inbox ID.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "address": {
      "type": "string",
      "description": "The full email address to look up (e.g., 'agent-47@mail.acme.com')."
    }
  },
  "required": ["address"],
  "additionalProperties": false
}
```

**Output:** Full inbox object if found, or an error if no inbox exists with that address.

**REST API Mapping:** `GET /v1/inboxes?email={address}` (filters the list endpoint by exact email match and returns the first result)

---

### 4.2 Email Operations (8 tools)

#### `send_email`

Compose and send a new email from an inbox.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to send from. Uses AGENTMAIL_DEFAULT_INBOX if omitted."
    },
    "to": {
      "type": "array",
      "description": "List of recipient email addresses.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string", "description": "Recipient email address." },
          "name": { "type": "string", "description": "Recipient display name (optional)." }
        },
        "required": ["address"]
      },
      "minItems": 1
    },
    "cc": {
      "type": "array",
      "description": "Carbon copy recipients.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["address"]
      }
    },
    "bcc": {
      "type": "array",
      "description": "Blind carbon copy recipients.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["address"]
      }
    },
    "subject": {
      "type": "string",
      "description": "Email subject line."
    },
    "body_text": {
      "type": "string",
      "description": "Plain text email body. At least one of body_text or body_html is required."
    },
    "body_html": {
      "type": "string",
      "description": "HTML email body."
    },
    "reply_to": {
      "type": "array",
      "description": "Reply-to addresses (overrides the inbox address).",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["address"]
      }
    },
    "headers": {
      "type": "object",
      "description": "Custom SMTP headers as key-value pairs.",
      "additionalProperties": { "type": "string" }
    },
    "send_at": {
      "type": "string",
      "description": "ISO 8601 timestamp for scheduled send. Sends immediately if omitted."
    }
  },
  "required": ["to", "subject"],
  "additionalProperties": false
}
```

**Output:** Full message object including `id`, `ses_message_id`, `thread_id`, `created_at`.

**REST API Mapping:** `POST /v1/inboxes/{inbox_id}/messages`

**Example usage:**

```
User: "Send an email to jane@example.com about the project update"
Agent calls: send_email({
  inbox_id: "01HXYZ...",
  to: [{address: "jane@example.com", name: "Jane"}],
  subject: "Project Update",
  body_text: "Hi Jane, here's the latest update on the project..."
})
```

---

#### `reply_to_email`

Reply to an existing email message. The recipient, subject, and threading headers (In-Reply-To, References) are automatically populated from the original message.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the message."
    },
    "message_id": {
      "type": "string",
      "description": "The ID of the message to reply to."
    },
    "body_text": {
      "type": "string",
      "description": "Plain text reply body."
    },
    "body_html": {
      "type": "string",
      "description": "HTML reply body."
    },
    "attachments": {
      "type": "array",
      "description": "File attachments for the reply.",
      "items": {
        "type": "object",
        "properties": {
          "filename": { "type": "string" },
          "content_type": { "type": "string" },
          "content_base64": { "type": "string" }
        },
        "required": ["filename", "content_type", "content_base64"]
      }
    }
  },
  "required": ["inbox_id", "message_id"],
  "additionalProperties": false
}
```

**Output:** Full message object for the sent reply.

**REST API Mapping:** `POST /v1/inboxes/{inbox_id}/messages/{message_id}/reply`

---

#### `reply_all`

Reply-all to an existing email message. All original recipients (To, CC) are included in the reply.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the message."
    },
    "message_id": {
      "type": "string",
      "description": "The ID of the message to reply-all to."
    },
    "body_text": {
      "type": "string",
      "description": "Plain text reply body."
    },
    "body_html": {
      "type": "string",
      "description": "HTML reply body."
    }
  },
  "required": ["inbox_id", "message_id"],
  "additionalProperties": false
}
```

**Output:** Full message object for the sent reply.

**REST API Mapping:** `POST /v1/inboxes/{inbox_id}/messages/{message_id}/reply-all`

---

#### `forward_email`

Forward an existing email message to new recipients. The original message content and attachments are included.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the message."
    },
    "message_id": {
      "type": "string",
      "description": "The ID of the message to forward."
    },
    "to": {
      "type": "array",
      "description": "Recipients to forward to.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["address"]
      },
      "minItems": 1
    },
    "comment": {
      "type": "string",
      "description": "Optional comment to prepend above the forwarded message."
    }
  },
  "required": ["inbox_id", "message_id", "to"],
  "additionalProperties": false
}
```

**Output:** Full message object for the forwarded message.

**REST API Mapping:** `POST /v1/inboxes/{inbox_id}/messages/{message_id}/forward`

---

#### `list_messages`

List messages in an inbox. Returns messages in reverse chronological order by default.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to list messages from."
    },
    "limit": {
      "type": "integer",
      "description": "Maximum number of messages to return (1-100).",
      "default": 25,
      "minimum": 1,
      "maximum": 100
    },
    "page_token": {
      "type": "string",
      "description": "Pagination cursor from a previous response."
    },
    "before": {
      "type": "string",
      "description": "Return messages received before this ISO 8601 timestamp."
    },
    "after": {
      "type": "string",
      "description": "Return messages received after this ISO 8601 timestamp."
    },
    "thread_id": {
      "type": "string",
      "description": "Filter by thread ID to get all messages in a conversation."
    },
    "category": {
      "type": "string",
      "description": "Filter by AI-assigned category (e.g., 'sales', 'support', 'verification')."
    },
    "is_read": {
      "type": "boolean",
      "description": "Filter by read status. Omit to return both read and unread."
    },
    "include_spam": {
      "type": "boolean",
      "description": "Include messages flagged as spam.",
      "default": false
    },
    "include_trash": {
      "type": "boolean",
      "description": "Include trashed messages.",
      "default": false
    },
    "ascending": {
      "type": "boolean",
      "description": "Sort oldest first instead of newest first.",
      "default": false
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output:** Paginated list with `data` (array of message objects with `id`, `from`, `to`, `subject`, `snippet`, `is_read`, `labels`, `category`, `attachments`, `received_at`), `next_page_token`, `has_more`.

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/messages`

---

#### `get_message`

Get the full content of a specific email message, including body text, HTML, headers, and attachment metadata.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the message."
    },
    "message_id": {
      "type": "string",
      "description": "The message ID to retrieve."
    }
  },
  "required": ["inbox_id", "message_id"],
  "additionalProperties": false
}
```

**Output:** Full message object including `body_text`, `body_html`, `headers`, `attachments` (with metadata), and all other fields.

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/messages/{message_id}`

**Note on output sanitization:** By default, the tool returns `from`, `to`, `subject`, `snippet` (first 200 chars of body_text), `category`, `labels`, `attachments` (metadata only), and `received_at`. The full `body_text` and `body_html` are included only when the `get_message` tool is called explicitly (not in list results). This prevents accidentally flooding the model context with large email bodies.

---

#### `search_messages`

Search across messages using full-text keyword search, semantic (meaning-based) search, or hybrid mode. Powered by OpenSearch Serverless with vector embeddings.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query text (e.g., 'enterprise pricing proposal', 'invoice from Acme Corp')."
    },
    "mode": {
      "type": "string",
      "enum": ["keyword", "semantic", "hybrid"],
      "description": "Search mode. 'keyword' for exact text matching, 'semantic' for meaning-based search, 'hybrid' for both.",
      "default": "hybrid"
    },
    "inbox_ids": {
      "type": "array",
      "description": "Limit search to specific inbox IDs. Searches all inboxes if omitted.",
      "items": { "type": "string" }
    },
    "pod_ids": {
      "type": "array",
      "description": "Limit search to specific pod IDs.",
      "items": { "type": "string" }
    },
    "from": {
      "type": "string",
      "description": "Filter by sender address or domain."
    },
    "date_start": {
      "type": "string",
      "description": "Start of date range (ISO 8601)."
    },
    "date_end": {
      "type": "string",
      "description": "End of date range (ISO 8601)."
    },
    "limit": {
      "type": "integer",
      "description": "Maximum results to return (1-50).",
      "default": 10,
      "minimum": 1,
      "maximum": 50
    }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

**Output:** Array of search results, each containing `message` (summary object with `id`, `inbox_id`, `from`, `subject`, `snippet`, `received_at`), `score` (relevance score 0-1), and `highlights` (matching text fragments).

**REST API Mapping:** `POST /v1/search`

---

#### `get_attachment`

Download an email attachment. Returns a pre-signed URL for the attachment file. The URL expires after 15 minutes.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the message."
    },
    "message_id": {
      "type": "string",
      "description": "The message ID containing the attachment."
    },
    "attachment_id": {
      "type": "string",
      "description": "The attachment ID to download."
    }
  },
  "required": ["inbox_id", "message_id", "attachment_id"],
  "additionalProperties": false
}
```

**Output:** Object with `url` (pre-signed S3 URL), `filename`, `content_type`, `size` (bytes).

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/messages/{message_id}/attachments/{attachment_id}` (follows the 302 redirect and returns the URL)

---

### 4.3 Wait/OTP Tools (3 tools) -- KEY DIFFERENTIATOR

These tools are what make AgentMail uniquely valuable for AI agents. They convert the common agent pattern of "trigger an action, wait for an email, extract information" into single blocking tool calls.

#### `wait_for_email`

Block until an email matching the specified filters arrives in the inbox, or until the timeout expires. This is a long-poll operation -- the MCP server holds the connection open while the REST API polls for matching messages.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to watch for new emails."
    },
    "from": {
      "type": "string",
      "description": "Filter by sender address or domain (e.g., 'github.com' or 'noreply@github.com'). Matches if the sender address contains this string."
    },
    "subject": {
      "type": "string",
      "description": "Filter by subject line. Prefix with 're:' for regex matching (e.g., 're:verify|confirm'). Otherwise treated as a substring match."
    },
    "has_attachment": {
      "type": "boolean",
      "description": "Filter by whether the email has attachments."
    },
    "category": {
      "type": "string",
      "description": "Filter by AI-assigned category (e.g., 'verification', 'receipt', 'newsletter')."
    },
    "timeout_seconds": {
      "type": "integer",
      "description": "Maximum time to wait in seconds. The tool blocks until a matching email arrives or the timeout expires.",
      "default": 60,
      "minimum": 1,
      "maximum": 300
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output on success:** Object with `message` (full message object including `id`, `from`, `to`, `subject`, `body_text`, `snippet`, `category`, `attachments`, `received_at`) and `waited_seconds` (how long the tool blocked before the email arrived).

**Output on timeout:** Error with `error: "timeout"`, `message: "No matching email received within {N} seconds"`, and `filter` (the criteria used).

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/wait?timeout={N}&from={from}&subject={subject}`

**Example usage:**

```
User: "Wait for the verification email from GitHub"
Agent calls: wait_for_email({
  inbox_id: "01HXYZ...",
  from: "github.com",
  subject: "verify",
  timeout_seconds: 120
})
// Tool blocks for up to 120 seconds...
Returns: {
  message: {
    id: "msg_abc123",
    from: {address: "noreply@github.com"},
    subject: "Please verify your email address",
    snippet: "Your verification code is 847293...",
    ...
  },
  waited_seconds: 4.2
}
```

---

#### `wait_for_otp`

Wait for a verification/OTP email to arrive and automatically extract the verification code, magic link, or backup codes. This is the single most valuable tool for AI agent workflows involving service signups, 2FA, and email verification.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to watch for OTP emails."
    },
    "from": {
      "type": "string",
      "description": "Filter by sender address or domain (e.g., 'github.com'). Recommended to avoid extracting OTPs from unrelated emails."
    },
    "type": {
      "type": "string",
      "enum": ["numeric", "alphanumeric", "magic_link", "any"],
      "description": "Expected OTP type. 'numeric' for digit-only codes, 'alphanumeric' for mixed codes, 'magic_link' for clickable verification URLs, 'any' to detect all types.",
      "default": "any"
    },
    "timeout_seconds": {
      "type": "integer",
      "description": "Maximum time to wait for the OTP email in seconds.",
      "default": 60,
      "minimum": 1,
      "maximum": 300
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output on success:**

```json
{
  "otp": "847293",
  "type": "numeric",
  "email_id": "msg_abc123",
  "from": "noreply@github.com",
  "subject": "Your verification code",
  "received_at": "2026-04-10T14:23:00Z",
  "expires_at": "2026-04-10T14:33:00Z",
  "magic_link": null,
  "backup_codes": null,
  "raw_match": "Your verification code is 847293. It expires in 10 minutes.",
  "waited_seconds": 3.8
}
```

**Output on timeout:** Error with `error: "timeout"`, `message: "No verification email received within {N} seconds"`, `emails_checked` (count of non-matching emails examined).

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/otp?timeout={N}&from={from}&type={type}`

**Example usage:**

```
User: "Get the verification code from Stripe"
Agent calls: wait_for_otp({
  inbox_id: "01HXYZ...",
  from: "stripe.com",
  type: "numeric",
  timeout_seconds: 90
})
Returns: {otp: "482917", type: "numeric", from: "noreply@stripe.com", ...}
Agent: "Your Stripe verification code is 482917."
```

---

#### `extract_otp`

Extract OTP codes, magic links, and backup codes from an existing email message that has already been received. Use this when you have already retrieved a message and need to parse verification information from it, rather than waiting for a new email.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the message."
    },
    "message_id": {
      "type": "string",
      "description": "The message ID to extract OTP information from."
    }
  },
  "required": ["inbox_id", "message_id"],
  "additionalProperties": false
}
```

**Output:**

```json
{
  "otp": "847293",
  "type": "numeric",
  "magic_link": "https://github.com/confirm?token=abc123def456",
  "backup_codes": null,
  "expires_at": "2026-04-10T14:33:00Z",
  "raw_match": "Your verification code is 847293."
}
```

Returns `null` for fields where no matching pattern was found. If no OTP, magic link, or backup codes are detected, returns an error explaining that the message does not appear to contain verification information.

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/messages/{message_id}/extract-otp` (dedicated extraction endpoint that runs the OTP detection pipeline against a specific message)

---

### 4.4 Thread Operations (3 tools)

#### `list_threads`

List conversation threads in an inbox. Threads group related messages together based on In-Reply-To and References headers.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to list threads from."
    },
    "limit": {
      "type": "integer",
      "description": "Maximum number of threads to return (1-100).",
      "default": 25,
      "minimum": 1,
      "maximum": 100
    },
    "page_token": {
      "type": "string",
      "description": "Pagination cursor from a previous response."
    },
    "category": {
      "type": "string",
      "description": "Filter threads by AI-assigned category."
    },
    "is_read": {
      "type": "boolean",
      "description": "Filter by read status of the thread."
    },
    "before": {
      "type": "string",
      "description": "Return threads with last activity before this ISO 8601 timestamp."
    },
    "after": {
      "type": "string",
      "description": "Return threads with last activity after this ISO 8601 timestamp."
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output:** Paginated list of thread objects with `id`, `subject`, `snippet`, `message_count`, `unread_count`, `participants`, `labels`, `category`, `last_message_at`.

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/threads`

---

#### `get_thread`

Get a conversation thread with all its messages, ordered chronologically.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the thread."
    },
    "thread_id": {
      "type": "string",
      "description": "The thread ID to retrieve."
    }
  },
  "required": ["inbox_id", "thread_id"],
  "additionalProperties": false
}
```

**Output:** Full thread object including `messages` array (all messages in the thread with full content), `participants`, `message_count`, `labels`, `category`.

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/threads/{thread_id}`

---

#### `update_thread`

Update a thread's labels, read status, or starred status. Changes apply to all messages in the thread.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the thread."
    },
    "thread_id": {
      "type": "string",
      "description": "The thread ID to update."
    },
    "labels": {
      "type": "array",
      "description": "New label set for the thread (replaces existing labels).",
      "items": { "type": "string" }
    },
    "is_read": {
      "type": "boolean",
      "description": "Mark the thread as read or unread."
    },
    "is_starred": {
      "type": "boolean",
      "description": "Star or unstar the thread."
    },
    "is_trash": {
      "type": "boolean",
      "description": "Move to trash or restore from trash."
    }
  },
  "required": ["inbox_id", "thread_id"],
  "additionalProperties": false
}
```

**Output:** Updated thread object (without messages array).

**REST API Mapping:** `PATCH /v1/inboxes/{inbox_id}/threads/{thread_id}`

---

### 4.5 Domain Management (4 tools)

#### `add_domain`

Register a custom domain for sending and receiving email. Returns the DNS records that must be configured at your DNS provider before the domain can be verified.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "domain": {
      "type": "string",
      "description": "The domain name to register (e.g., 'mail.acme.com')."
    },
    "catch_all_inbox_id": {
      "type": "string",
      "description": "Inbox ID to receive emails sent to any address at this domain that doesn't have a dedicated inbox."
    }
  },
  "required": ["domain"],
  "additionalProperties": false
}
```

**Output:** Full domain object with `id`, `domain`, `status: "pending"`, `dns_records` (MX, SPF, DKIM CNAMEs, DMARC TXT records with exact values to configure).

**REST API Mapping:** `POST /v1/domains`

---

#### `list_domains`

List all custom domains for the organization with their verification status.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "description": "Maximum number of domains to return (1-100).",
      "default": 25
    },
    "page_token": {
      "type": "string",
      "description": "Pagination cursor from a previous response."
    }
  },
  "required": [],
  "additionalProperties": false
}
```

**Output:** Paginated list of domain objects with `id`, `domain`, `status`, `mx_verified`, `spf_verified`, `dkim_verified`, `dmarc_verified`, `created_at`, `verified_at`.

**REST API Mapping:** `GET /v1/domains`

---

#### `verify_domain`

Trigger a re-verification check for a domain's DNS records. Use this after configuring DNS records to check if they have propagated and are correct.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "domain_id": {
      "type": "string",
      "description": "The domain ID to verify."
    }
  },
  "required": ["domain_id"],
  "additionalProperties": false
}
```

**Output:** Domain object with updated verification status for each record type (`mx_verified`, `spf_verified`, `dkim_verified`, `dmarc_verified`). If all pass, `status` changes to `"verified"`.

**REST API Mapping:** `POST /v1/domains/{domain_id}/verify`

---

#### `get_dns_records`

Get the required DNS records for a domain in a human-readable format. Also returns a BIND zone file that can be imported into DNS providers.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "domain_id": {
      "type": "string",
      "description": "The domain ID to get DNS records for."
    }
  },
  "required": ["domain_id"],
  "additionalProperties": false
}
```

**Output:** Object with `domain`, `records` (array of `{type, name, value, verified}` for each required DNS record), and `zone_file` (BIND-format zone file as a string).

**REST API Mapping:** `GET /v1/domains/{domain_id}` (extracts `dns_records`) + `GET /v1/domains/{domain_id}/zone-file`

---

### 4.6 Draft Operations (4 tools)

#### `create_draft`

Create an email draft that can be reviewed and sent later.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to create the draft in."
    },
    "to": {
      "type": "array",
      "description": "Intended recipients.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["address"]
      }
    },
    "cc": {
      "type": "array",
      "description": "CC recipients.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["address"]
      }
    },
    "subject": {
      "type": "string",
      "description": "Email subject line."
    },
    "body_text": {
      "type": "string",
      "description": "Plain text draft body."
    },
    "body_html": {
      "type": "string",
      "description": "HTML draft body."
    },
    "thread_id": {
      "type": "string",
      "description": "Thread ID if this draft is a reply within an existing conversation."
    },
    "in_reply_to_message_id": {
      "type": "string",
      "description": "Message ID this draft is a reply to."
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output:** Full draft object including `id`, `inbox_id`, `to`, `subject`, `body_text`, `created_at`.

**REST API Mapping:** `POST /v1/inboxes/{inbox_id}/drafts`

---

#### `list_drafts`

List all drafts in an inbox.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to list drafts from."
    },
    "limit": {
      "type": "integer",
      "description": "Maximum number of drafts to return (1-100).",
      "default": 25
    },
    "page_token": {
      "type": "string",
      "description": "Pagination cursor from a previous response."
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output:** Paginated list of draft objects.

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/drafts`

---

#### `update_draft`

Update an existing draft. Supports partial updates -- only the specified fields are changed.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the draft."
    },
    "draft_id": {
      "type": "string",
      "description": "The draft ID to update."
    },
    "to": {
      "type": "array",
      "description": "Updated recipients.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["address"]
      }
    },
    "cc": {
      "type": "array",
      "description": "Updated CC recipients.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["address"]
      }
    },
    "subject": {
      "type": "string",
      "description": "Updated subject line."
    },
    "body_text": {
      "type": "string",
      "description": "Updated plain text body."
    },
    "body_html": {
      "type": "string",
      "description": "Updated HTML body."
    }
  },
  "required": ["inbox_id", "draft_id"],
  "additionalProperties": false
}
```

**Output:** Full updated draft object.

**REST API Mapping:** `PATCH /v1/inboxes/{inbox_id}/drafts/{draft_id}`

---

#### `send_draft`

Send an existing draft. The draft is converted to a sent message and removed from the drafts list.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the draft."
    },
    "draft_id": {
      "type": "string",
      "description": "The draft ID to send."
    },
    "send_at": {
      "type": "string",
      "description": "ISO 8601 timestamp for scheduled send. Sends immediately if omitted."
    }
  },
  "required": ["inbox_id", "draft_id"],
  "additionalProperties": false
}
```

**Output:** Full message object for the sent email (same shape as `send_email` output).

**REST API Mapping:** `POST /v1/inboxes/{inbox_id}/drafts/{draft_id}/send`

---

### 4.7 Webhook Management (3 tools)

#### `create_webhook`

Register a webhook endpoint to receive real-time notifications when events occur (new messages, bounces, inbox creation, etc.).

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "description": "The HTTPS URL to deliver webhook events to."
    },
    "events": {
      "type": "array",
      "description": "List of event types to subscribe to.",
      "items": {
        "type": "string",
        "enum": [
          "message.received",
          "message.sent",
          "message.bounced",
          "message.complained",
          "message.delayed",
          "inbox.created",
          "inbox.deleted",
          "domain.verified",
          "domain.failed",
          "subscription.updated"
        ]
      },
      "minItems": 1
    },
    "filter": {
      "type": "object",
      "description": "Scope the webhook to specific pods or inboxes.",
      "properties": {
        "pod_ids": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Only fire for events in these pods."
        },
        "inbox_ids": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Only fire for events in these inboxes."
        }
      }
    }
  },
  "required": ["url", "events"],
  "additionalProperties": false
}
```

**Output:** Full webhook object including `id`, `url`, `events`, `status`, `secret` (for signature verification), `created_at`.

**REST API Mapping:** `POST /v1/webhooks`

---

#### `list_webhooks`

List all webhook endpoints registered for the organization.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "description": "Maximum number of webhooks to return (1-100).",
      "default": 25
    },
    "page_token": {
      "type": "string",
      "description": "Pagination cursor from a previous response."
    }
  },
  "required": [],
  "additionalProperties": false
}
```

**Output:** Paginated list of webhook objects with `id`, `url`, `events`, `status`, `delivery_stats`, `created_at`.

**REST API Mapping:** `GET /v1/webhooks`

---

#### `delete_webhook`

Delete a webhook endpoint. Events will no longer be delivered to this URL.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "webhook_id": {
      "type": "string",
      "description": "The webhook ID to delete."
    }
  },
  "required": ["webhook_id"],
  "additionalProperties": false
}
```

**Output:** Confirmation message. No content returned (HTTP 204).

**REST API Mapping:** `DELETE /v1/webhooks/{webhook_id}`

---

### 4.8 List Management (4 tools)

Mailing lists are distribution lists for broadcasting to multiple external recipients.

#### `create_list`

Create a new mailing list.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Name of the mailing list (e.g., 'Product Updates', 'Weekly Newsletter')."
    },
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID that will be used to send emails to this list."
    },
    "members": {
      "type": "array",
      "description": "Initial list members.",
      "items": {
        "type": "object",
        "properties": {
          "address": { "type": "string", "description": "Member email address." },
          "name": { "type": "string", "description": "Member display name." }
        },
        "required": ["address"]
      }
    }
  },
  "required": ["name", "inbox_id"],
  "additionalProperties": false
}
```

**Output:** Full list object with `id`, `name`, `inbox_id`, `member_count`, `created_at`.

**REST API Mapping:** `POST /v1/lists`

---

#### `get_list`

Get a mailing list with its members (paginated).

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "list_id": {
      "type": "string",
      "description": "The mailing list ID."
    },
    "limit": {
      "type": "integer",
      "description": "Maximum number of members to return per page.",
      "default": 25
    },
    "page_token": {
      "type": "string",
      "description": "Pagination cursor for member list."
    }
  },
  "required": ["list_id"],
  "additionalProperties": false
}
```

**Output:** Full list object with `members` array (paginated), `member_count`, `next_page_token`, `has_more`.

**REST API Mapping:** `GET /v1/lists/{list_id}`

---

#### `list_lists`

List all mailing lists for the organization.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "description": "Maximum number of lists to return.",
      "default": 25
    },
    "page_token": {
      "type": "string",
      "description": "Pagination cursor from a previous response."
    }
  },
  "required": [],
  "additionalProperties": false
}
```

**Output:** Paginated list of mailing list objects.

**REST API Mapping:** `GET /v1/lists`

---

#### `delete_list`

Delete a mailing list. Does not delete any previously sent messages.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "list_id": {
      "type": "string",
      "description": "The mailing list ID to delete."
    }
  },
  "required": ["list_id"],
  "additionalProperties": false
}
```

**Output:** Confirmation message. No content returned (HTTP 204).

**REST API Mapping:** `DELETE /v1/lists/{list_id}`

---

### 4.9 Account and Usage (3 tools)

#### `get_usage`

Get current usage metrics and quota limits for the organization. Useful for checking how many inboxes, messages, and API calls have been used against the plan limits.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {},
  "required": [],
  "additionalProperties": false
}
```

**Output:**

```json
{
  "tier": "pro",
  "quotas": {
    "max_inboxes": 100000,
    "max_messages_per_day": 100000,
    "max_api_keys": 50,
    "max_pods": 100,
    "max_domains": 20,
    "max_webhooks": 50
  },
  "usage": {
    "inboxes": 1247,
    "messages_today": 8432,
    "api_keys": 3,
    "pods": 2,
    "domains": 1
  },
  "percentage": {
    "inboxes": 1.2,
    "messages_today": 8.4,
    "api_keys": 6.0,
    "pods": 2.0,
    "domains": 5.0
  }
}
```

**REST API Mapping:** `GET /v1/organizations/me` (extracts and reformats the `quotas` and `usage` fields, computes percentages)

---

#### `get_organization`

Get organization details including name, email, tier, settings, and current plan.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {},
  "required": [],
  "additionalProperties": false
}
```

**Output:** Full organization object with `id`, `name`, `email`, `tier`, `status`, `settings` (default domain, webhook secret, retention days, AI features), `created_at`.

**REST API Mapping:** `GET /v1/organizations/me`

---

#### `list_api_keys`

List all API keys for the organization. Returns metadata only -- the secret key value is never exposed.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {},
  "required": [],
  "additionalProperties": false
}
```

**Output:** Array of API key metadata objects with `id`, `name`, `prefix` (first 12 chars), `scope`, `scope_resource_id`, `last_used_at`, `created_at`.

**REST API Mapping:** `GET /v1/api-keys`

---

### 4.10 Skill Tools -- Compound Actions (3 tools)

These tools orchestrate multiple API calls into a single high-level action. They exist because AI agents frequently need these multi-step patterns, and expressing them as single tools reduces latency, error surface, and context consumption.

#### `signup_with_email`

End-to-end email signup flow: creates a temporary inbox, returns the email address for the user to enter into a service's signup form, then waits for a verification email and extracts the OTP code or magic link.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "service_name": {
      "type": "string",
      "description": "Name of the service being signed up for (e.g., 'GitHub', 'Stripe'). Used to optimize OTP extraction patterns for known providers and to label the inbox."
    },
    "display_name": {
      "type": "string",
      "description": "Display name for the inbox (e.g., 'GitHub Signup Agent')."
    },
    "domain": {
      "type": "string",
      "description": "Domain to create the inbox on. Uses default domain if omitted."
    },
    "timeout_seconds": {
      "type": "integer",
      "description": "Maximum time to wait for the verification email after the inbox is created.",
      "default": 120,
      "minimum": 30,
      "maximum": 300
    }
  },
  "required": ["service_name"],
  "additionalProperties": false
}
```

**Output:**

```json
{
  "inbox_id": "01HXYZ...",
  "email_address": "agent-a7k3m@inbox.agentmail.dev",
  "status": "waiting",
  "instructions": "Enter this email address into the GitHub signup form, then I will wait for the verification email and extract the code."
}
```

When the tool is first called, it returns immediately with the email address and `status: "waiting"`. The tool description instructs the AI model to present the address to the user, then call `wait_for_otp` as a follow-up.

**Implementation detail:** This tool is split into two phases to avoid blocking the AI model while the user is performing the signup:

1. **Phase 1** (immediate): `POST /v1/inboxes` to create the inbox, return the address.
2. **Phase 2** (user triggers): The model calls `wait_for_otp` with the inbox_id when the user confirms they have entered the address.

Alternatively, in fully autonomous agent mode (no human in the loop), the tool can block on `wait_for_otp` internally and return the complete result:

```json
{
  "inbox_id": "01HXYZ...",
  "email_address": "agent-a7k3m@inbox.agentmail.dev",
  "status": "completed",
  "otp": "847293",
  "magic_link": null,
  "from": "noreply@github.com",
  "subject": "Please verify your email address",
  "waited_seconds": 8.4
}
```

**REST API Mapping:** `POST /v1/inboxes` + `GET /v1/inboxes/{id}/otp`

---

#### `monitor_inbox`

Subscribe to an inbox and report new emails as they arrive for a specified duration. The tool uses repeated long-poll calls internally, returning each batch of new messages as they are received.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to monitor."
    },
    "duration_seconds": {
      "type": "integer",
      "description": "How long to monitor the inbox in seconds. The tool returns all emails received during this window.",
      "default": 300,
      "minimum": 10,
      "maximum": 3600
    },
    "from": {
      "type": "string",
      "description": "Only report emails from this sender address or domain."
    },
    "category": {
      "type": "string",
      "description": "Only report emails matching this AI category."
    }
  },
  "required": ["inbox_id"],
  "additionalProperties": false
}
```

**Output:** Array of message summary objects received during the monitoring period:

```json
{
  "messages_received": 3,
  "duration_seconds": 300,
  "messages": [
    {
      "id": "msg_001",
      "from": "alice@example.com",
      "subject": "New support ticket #1234",
      "snippet": "Customer reports login issue...",
      "received_at": "2026-04-10T14:31:00Z"
    },
    {
      "id": "msg_002",
      "from": "bob@example.com",
      "subject": "Re: Invoice question",
      "snippet": "Thanks for clarifying the charges...",
      "received_at": "2026-04-10T14:33:22Z"
    }
  ]
}
```

**Implementation detail:** Internally chains multiple `GET /v1/inboxes/{id}/wait?timeout=30` calls. After each wait returns (either with a message or timeout), immediately issues another wait until the total duration elapses. Messages are accumulated and returned as a batch when the duration expires.

**REST API Mapping:** Multiple `GET /v1/inboxes/{inbox_id}/wait` calls in sequence.

---

#### `bulk_send`

Send the same email to multiple recipients, each as an individual message (not CC/BCC). Useful for personalized outreach, notifications, or announcements where each recipient should see only their own address.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID to send from."
    },
    "to_addresses": {
      "type": "array",
      "description": "List of recipient email addresses. Each receives a separate email.",
      "items": { "type": "string" },
      "minItems": 1,
      "maxItems": 500
    },
    "subject": {
      "type": "string",
      "description": "Email subject line."
    },
    "body_text": {
      "type": "string",
      "description": "Plain text email body."
    },
    "body_html": {
      "type": "string",
      "description": "HTML email body."
    }
  },
  "required": ["inbox_id", "to_addresses", "subject"],
  "additionalProperties": false
}
```

**Output:**

```json
{
  "total": 50,
  "sent": 48,
  "failed": 2,
  "failures": [
    { "address": "invalid@", "error": "Invalid email address format" },
    { "address": "blocked@example.com", "error": "Address on block list" }
  ]
}
```

**REST API Mapping:** Multiple `POST /v1/inboxes/{inbox_id}/messages` calls in parallel (batched in groups of 10 with concurrency control).

---

### 4.11 Message Actions (2 tools)

#### `mark_message`

Update a message's metadata -- mark as read/unread, star/unstar, label, or trash.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the message."
    },
    "message_id": {
      "type": "string",
      "description": "The message ID to update."
    },
    "is_read": {
      "type": "boolean",
      "description": "Mark as read (true) or unread (false)."
    },
    "is_starred": {
      "type": "boolean",
      "description": "Star (true) or unstar (false) the message."
    },
    "is_trash": {
      "type": "boolean",
      "description": "Move to trash (true) or restore (false)."
    },
    "labels": {
      "type": "array",
      "description": "Set labels on the message (replaces existing labels).",
      "items": { "type": "string" }
    }
  },
  "required": ["inbox_id", "message_id"],
  "additionalProperties": false
}
```

**Output:** Full updated message object.

**REST API Mapping:** `PATCH /v1/inboxes/{inbox_id}/messages/{message_id}`

---

#### `get_raw_message`

Download the raw RFC 2822 email source (complete MIME message). Useful for debugging email headers, verifying DKIM signatures, or passing the raw message to other tools.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "inbox_id": {
      "type": "string",
      "description": "The inbox ID containing the message."
    },
    "message_id": {
      "type": "string",
      "description": "The message ID to download the raw source for."
    }
  },
  "required": ["inbox_id", "message_id"],
  "additionalProperties": false
}
```

**Output:** Raw RFC 2822 email source as a string.

**REST API Mapping:** `GET /v1/inboxes/{inbox_id}/messages/{message_id}/raw`

---

### Tool Count Summary

| Category | Count | Tools |
|----------|-------|-------|
| Inbox Management | 6 | `create_inbox`, `list_inboxes`, `get_inbox`, `update_inbox`, `delete_inbox`, `get_inbox_by_address` |
| Email Operations | 8 | `send_email`, `reply_to_email`, `reply_all`, `forward_email`, `list_messages`, `get_message`, `search_messages`, `get_attachment` |
| Wait/OTP | 3 | `wait_for_email`, `wait_for_otp`, `extract_otp` |
| Thread Operations | 3 | `list_threads`, `get_thread`, `update_thread` |
| Domain Management | 4 | `add_domain`, `list_domains`, `verify_domain`, `get_dns_records` |
| Draft Operations | 4 | `create_draft`, `list_drafts`, `update_draft`, `send_draft` |
| Webhook Management | 3 | `create_webhook`, `list_webhooks`, `delete_webhook` |
| List Management | 4 | `create_list`, `get_list`, `list_lists`, `delete_list` |
| Account & Usage | 3 | `get_usage`, `get_organization`, `list_api_keys` |
| Skill Tools | 3 | `signup_with_email`, `monitor_inbox`, `bulk_send` |
| Message Actions | 2 | `mark_message`, `get_raw_message` |
| **Total** | **43** | |

---

## 5. Tool Implementation Architecture

### System Diagram

```
┌─────────────────────────────┐
│   MCP Client                │
│   (Claude Code / Cursor /   │
│    Custom Agent)             │
└──────────┬──────────────────┘
           │ JSON-RPC over stdio
           │ (or SSE / Streamable HTTP)
           │
┌──────────▼──────────────────┐
│   @agentmail/mcp-server     │
│   (Node.js / TypeScript)    │
│                             │
│  ┌────────────────────┐     │
│  │  MCP Protocol      │     │
│  │  Layer              │     │
│  │  (@modelcontext-   │     │
│  │   protocol/sdk)    │     │
│  └────────┬───────────┘     │
│           │                 │
│  ┌────────▼───────────┐     │
│  │  Tool Router       │     │
│  │  (maps tool names  │     │
│  │   to handlers)     │     │
│  └────────┬───────────┘     │
│           │                 │
│  ┌────────▼───────────┐     │
│  │  API Client Layer  │     │
│  │  (HTTP client with │     │
│  │   auth, retries,   │     │
│  │   error mapping)   │     │
│  └────────┬───────────┘     │
│           │                 │
└───────────┼─────────────────┘
            │ HTTPS
            │
┌───────────▼─────────────────┐
│   api.agentmail.aws         │
│   (REST API)                │
│                             │
│   API Gateway → Lambda      │
│   → DynamoDB / SES / S3     │
└─────────────────────────────┘
```

### Design Principles

1. **Thin wrapper**: The MCP server contains zero business logic. It is a protocol adapter that maps MCP tool calls to REST API requests. All validation, authorization, rate limiting, and data processing happens server-side.

2. **Same SDK**: The MCP server's API client layer uses the same HTTP client code that the `@agentmail/sdk` npm package uses. They share request signing, error parsing, and retry logic. The MCP server simply wraps each SDK method as an MCP tool.

3. **Stateless**: The MCP server holds no state between tool calls. Every call is an independent API request. The only persistent state is the API key loaded at startup.

4. **Streaming for long-poll**: The `wait_for_email` and `wait_for_otp` tools keep the MCP call open while the underlying REST API long-polls. The MCP server uses the HTTP response stream from the API directly rather than setting its own timers.

### Internal Module Structure

```
src/
├── index.ts                  # Entry point, CLI parsing, transport setup
├── server.ts                 # MCP server initialization, tool registration
├── tools/
│   ├── inboxes.ts            # create_inbox, list_inboxes, get_inbox, etc.
│   ├── messages.ts           # send_email, reply_to_email, list_messages, etc.
│   ├── wait.ts               # wait_for_email, wait_for_otp, extract_otp
│   ├── threads.ts            # list_threads, get_thread, update_thread
│   ├── domains.ts            # add_domain, list_domains, verify_domain, etc.
│   ├── drafts.ts             # create_draft, list_drafts, update_draft, etc.
│   ├── webhooks.ts           # create_webhook, list_webhooks, delete_webhook
│   ├── lists.ts              # create_list, get_list, list_lists, delete_list
│   ├── account.ts            # get_usage, get_organization, list_api_keys
│   ├── skills.ts             # signup_with_email, monitor_inbox, bulk_send
│   └── actions.ts            # mark_message, get_raw_message
├── client/
│   ├── api-client.ts         # HTTP client with auth, base URL, headers
│   ├── retry.ts              # Exponential backoff retry logic
│   └── errors.ts             # API error → MCP error mapping
├── config.ts                 # Environment variable parsing, validation
└── types.ts                  # TypeScript interfaces for API responses
```

### Tool Handler Pattern

Every tool handler follows the same pattern:

```typescript
import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { apiClient } from "../client/api-client.js";

export function registerInboxTools(server: McpServer) {
  server.tool(
    "create_inbox",
    "Create a new email inbox. Returns the inbox details including the generated email address.",
    {
      email: z.string().optional().describe("Desired email address."),
      display_name: z.string().optional().describe("Display name for outbound emails."),
      pod_id: z.string().optional().describe("Pod ID to assign the inbox to."),
      domain: z.string().optional().describe("Domain to create the inbox on."),
    },
    async (params) => {
      const inbox = await apiClient.post("/v1/inboxes", {
        email: params.email,
        display_name: params.display_name,
        pod_id: params.pod_id,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(inbox, null, 2),
          },
        ],
      };
    }
  );
}
```

### Long-Poll Tool Pattern

The wait tools have a different pattern because they hold the connection open:

```typescript
server.tool(
  "wait_for_email",
  "Block until an email matching filters arrives, or timeout.",
  {
    inbox_id: z.string().describe("The inbox ID to watch."),
    from: z.string().optional().describe("Filter by sender."),
    subject: z.string().optional().describe("Filter by subject."),
    timeout_seconds: z.number().default(60).describe("Max wait time."),
  },
  async (params) => {
    const queryParams = new URLSearchParams();
    queryParams.set("timeout", String(params.timeout_seconds));
    if (params.from) queryParams.set("from", params.from);
    if (params.subject) queryParams.set("subject", params.subject);

    try {
      // This call blocks for up to timeout_seconds
      const result = await apiClient.get(
        `/v1/inboxes/${params.inbox_id}/wait?${queryParams}`,
        { timeout: (params.timeout_seconds + 5) * 1000 }
      );

      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      if (error.status === 408) {
        return {
          content: [{ type: "text", text: JSON.stringify(error.body, null, 2) }],
          isError: true,
        };
      }
      throw error;
    }
  }
);
```

### Compound Tool Pattern

Skill tools orchestrate multiple API calls:

```typescript
server.tool(
  "signup_with_email",
  "Create an inbox and wait for a verification email with OTP extraction.",
  {
    service_name: z.string().describe("Name of the service."),
    timeout_seconds: z.number().default(120).describe("Max wait for OTP."),
  },
  async (params) => {
    // Step 1: Create inbox
    const inbox = await apiClient.post("/v1/inboxes", {
      display_name: `${params.service_name} Signup`,
    });

    // Step 2: Return address immediately for user to enter
    // Then wait for OTP
    const otpResult = await apiClient.get(
      `/v1/inboxes/${inbox.id}/otp?timeout=${params.timeout_seconds}&from=${params.service_name.toLowerCase()}.com`,
      { timeout: (params.timeout_seconds + 5) * 1000 }
    );

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          inbox_id: inbox.id,
          email_address: inbox.email,
          status: "completed",
          otp: otpResult.otp,
          magic_link: otpResult.magic_link,
          from: otpResult.from,
          subject: otpResult.subject,
          waited_seconds: otpResult.waited_seconds,
        }, null, 2),
      }],
    };
  }
);
```

---

## 6. Error Handling

### API Error to MCP Error Mapping

The MCP server maps REST API errors to structured MCP tool error responses. Every error response includes a human-readable message that helps the AI model (and the user) understand what went wrong and what to do about it.

| HTTP Status | API Error Code | MCP Error Response |
|------------|----------------|-------------------|
| 400 | `INVALID_REQUEST` | `"Invalid request: {message}. Check the tool parameters and try again."` |
| 400 | `VALIDATION_ERROR` | `"Validation error: {message}. The following fields have issues: {details}."` |
| 401 | `UNAUTHORIZED` | `"Authentication failed. Your AGENTMAIL_API_KEY may be invalid, expired, or missing. Check your MCP server configuration."` |
| 403 | `FORBIDDEN` | `"Permission denied. Your API key does not have access to this resource. Key scope: {scope}."` |
| 403 | `SCOPE_VIOLATION` | `"Scope violation: your API key is scoped to {scope} and cannot access {resource}. Use an org-scoped key or request a key with broader scope."` |
| 404 | `RESOURCE_NOT_FOUND` | `"Not found: {resource_type} {id} does not exist. Verify the ID and try again."` |
| 408 | `TIMEOUT` | `"Timeout: no matching email arrived within {N} seconds. Try increasing timeout_seconds or check that the expected email was sent to the correct address."` |
| 409 | `CONFLICT` | `"Conflict: {message}. The resource may already exist or be in an incompatible state."` |
| 422 | `UNPROCESSABLE_ENTITY` | `"Cannot process request: {message}. Example: the email address format may be invalid."` |
| 429 | `RATE_LIMITED` | `"Rate limit exceeded. Retry after {retry_after} seconds. Current limit: {limit} requests per {window}."` |
| 500 | `INTERNAL_ERROR` | `"AgentMail server error. This is not your fault. The issue has been logged. Try again in a moment."` |
| 503 | `SERVICE_UNAVAILABLE` | `"AgentMail is temporarily unavailable. Retrying automatically..."` |

### Retry Logic

The MCP server implements automatic retries for transient errors:

```
Retryable errors: 429, 500, 503, network timeouts, connection resets
Max retries: 3
Backoff: exponential with jitter
  Attempt 1: immediate
  Attempt 2: 1-2 seconds
  Attempt 3: 2-4 seconds
  Attempt 4: 4-8 seconds (final)
```

Non-retryable errors (400, 401, 403, 404, 409, 422) are returned immediately.

### Rate Limit Handling

When a 429 response includes a `Retry-After` header, the MCP server:

1. Waits for the specified duration.
2. Retries the request.
3. If still rate limited after 3 retries, returns the error to the MCP client with the message: `"Rate limit exceeded. You have made too many requests. Wait {N} seconds before trying again. To increase your rate limit, upgrade your plan at https://console.agentmail.aws/billing."`.

### Quota Exceeded Handling

When an operation fails due to quota limits (e.g., max inboxes reached), the error message includes:

- Current usage vs limit
- Which quota was exceeded
- Upgrade URL: `"You have used {current}/{max} {resource}. Upgrade your plan at https://console.agentmail.aws/billing to increase this limit."`

### Timeout Handling for Long-Poll Tools

The `wait_for_email`, `wait_for_otp`, and `monitor_inbox` tools set the HTTP client timeout to `timeout_seconds + 5 seconds` (5-second buffer for network latency). If the REST API returns a 408 timeout, the tool returns a structured error (not a network timeout exception) so the AI model can decide whether to retry with different parameters.

### Network Error Handling

If the REST API is unreachable (DNS failure, connection refused, TLS error):

```
"Cannot connect to AgentMail API at {url}. Check your network connection and verify AGENTMAIL_API_URL is correct. Current value: {url}."
```

---

## 7. Security

### API Key Management

- The API key is loaded exclusively from the `AGENTMAIL_API_KEY` environment variable or the `--api-key` CLI flag.
- The API key is **never** included in MCP configuration files that may be committed to version control. The env var approach ensures the key lives in the shell environment or a `.env` file excluded from git.
- The MCP server does not log the API key. It logs only the key prefix (`am_live_7kB3...`) for debugging purposes.
- The API key is transmitted only over HTTPS to `api.agentmail.aws`. The MCP server rejects `http://` API URLs unless `AGENTMAIL_ALLOW_INSECURE=true` is set (for local development only).

### Data Sanitization in Tool Outputs

Email bodies may contain sensitive information (passwords, financial data, personal information). The MCP server applies the following sanitization rules:

1. **List operations** (`list_messages`, `list_threads`): Return only `snippet` (first 200 characters of body_text), never full bodies. This prevents accidentally loading large volumes of email content into the model context.

2. **Get operations** (`get_message`, `get_thread`): Return full `body_text` and `body_html`. The model needs the full content to answer questions about specific emails.

3. **Search results** (`search_messages`): Return `snippet` and `highlights` only.

4. **Attachment content**: Never included inline. The `get_attachment` tool returns a download URL, not the file content. Binary data would be meaningless in a text-based MCP response.

5. **Headers**: The `headers` field from messages is included only in `get_message` and `get_raw_message`, not in list results. Headers can contain routing information that is rarely useful and clutters context.

### No Sensitive Data in Logs

The MCP server logs to stderr at the configured log level. The following data is **never** logged:

- API key (beyond the prefix)
- Email body content
- Attachment content or URLs
- Webhook secrets
- Any PII from email addresses (sender names, etc.)

The following is logged at `debug` level:

- Tool call names and parameter keys (not values)
- API endpoint paths
- Response status codes
- Timing information

### MCP Transport Security

- **stdio**: Inherently secure -- communication stays within the local process. No network exposure.
- **SSE / Streamable HTTP**: Must be deployed behind TLS (HTTPS). The server binds to `127.0.0.1` by default (local only). To expose to the network, explicitly set `--host 0.0.0.0` and ensure a reverse proxy (nginx, Caddy, cloud load balancer) terminates TLS.
- **Token authentication for SSE/HTTP**: When running in SSE or Streamable HTTP mode, the server requires an `Authorization: Bearer <token>` header on all connections. The token is either the AgentMail API key or a separate `AGENTMAIL_MCP_TOKEN` for cases where the MCP server access should be controlled independently of the API key.

---

## 8. Development and Publishing

### Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Runtime | Node.js | 18+ (LTS) |
| Language | TypeScript | 5.x |
| MCP SDK | `@modelcontextprotocol/sdk` | Latest stable |
| HTTP Client | `undici` (Node.js built-in) | Built-in |
| Schema Validation | `zod` | 3.x |
| CLI Parsing | `commander` | 12.x |
| Build | `tsc` | 5.x |
| Test | `vitest` | 2.x |
| Lint | `eslint` + `@typescript-eslint` | Latest |

### Project Setup

```
@agentmail/mcp-server/
├── package.json
├── tsconfig.json
├── vitest.config.ts
├── .eslintrc.json
├── .github/
│   └── workflows/
│       ├── ci.yml              # Lint + test on PR
│       └── publish.yml         # Publish to npm + PyPI on tag
├── src/
│   ├── index.ts
│   ├── server.ts
│   ├── config.ts
│   ├── types.ts
│   ├── tools/
│   │   ├── inboxes.ts
│   │   ├── messages.ts
│   │   ├── wait.ts
│   │   ├── threads.ts
│   │   ├── domains.ts
│   │   ├── drafts.ts
│   │   ├── webhooks.ts
│   │   ├── lists.ts
│   │   ├── account.ts
│   │   ├── skills.ts
│   │   └── actions.ts
│   └── client/
│       ├── api-client.ts
│       ├── retry.ts
│       └── errors.ts
├── tests/
│   ├── tools/
│   │   ├── inboxes.test.ts
│   │   ├── messages.test.ts
│   │   ├── wait.test.ts
│   │   └── ...
│   ├── client/
│   │   ├── api-client.test.ts
│   │   └── retry.test.ts
│   └── integration/
│       └── server.test.ts
├── dist/                       # Built output (gitignored)
└── python/
    ├── pyproject.toml
    ├── agentmail_mcp/
    │   ├── __init__.py
    │   └── wrapper.py          # Subprocess wrapper
    └── README.md
```

### Build Process

```bash
# Install dependencies
npm install

# Type check
npx tsc --noEmit

# Build
npx tsc

# Output: dist/index.js (entry point, marked as bin in package.json)

# Run locally
node dist/index.js --transport stdio

# Run via npx (as users will)
npx @agentmail/mcp-server
```

### package.json Key Fields

```json
{
  "name": "@agentmail/mcp-server",
  "version": "1.0.0",
  "description": "MCP server for AgentMail - give AI agents email capabilities",
  "bin": {
    "agentmail-mcp-server": "./dist/index.js"
  },
  "main": "./dist/index.js",
  "type": "module",
  "engines": {
    "node": ">=18"
  },
  "keywords": ["mcp", "email", "ai-agents", "agentmail", "model-context-protocol"],
  "files": ["dist/"],
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0",
    "zod": "^3.23.0",
    "commander": "^12.0.0"
  },
  "peerDependencies": {},
  "devDependencies": {
    "typescript": "^5.5.0",
    "vitest": "^2.0.0",
    "@typescript-eslint/eslint-plugin": "^8.0.0",
    "eslint": "^9.0.0"
  }
}
```

### npm Publishing

Published to npm under the `@agentmail` scope:

```bash
npm publish --access public
```

Trigger: GitHub Actions workflow on `v*` tag push.

```yaml
# .github/workflows/publish.yml
name: Publish
on:
  push:
    tags: ['v*']
jobs:
  npm:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          registry-url: https://registry.npmjs.org
      - run: npm ci
      - run: npm run build
      - run: npm test
      - run: npm publish --access public
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
  pypi:
    runs-on: ubuntu-latest
    needs: npm
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - working-directory: python
        run: |
          pip install build twine
          python -m build
          twine upload dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
```

### Python Wrapper (PyPI)

The `agentmail-mcp` PyPI package is a thin Python wrapper that spawns the Node.js MCP server as a subprocess. This is for Python-based agent frameworks that prefer `pip install` over `npx`.

```python
# agentmail_mcp/wrapper.py
import subprocess
import shutil
import sys

def get_npx_path():
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError(
            "npx not found. Install Node.js 18+ to use agentmail-mcp. "
            "See: https://nodejs.org/"
        )
    return npx

def main():
    npx = get_npx_path()
    proc = subprocess.run(
        [npx, "@agentmail/mcp-server", *sys.argv[1:]],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    sys.exit(proc.returncode)

if __name__ == "__main__":
    main()
```

### Versioning

The MCP server version tracks the AgentMail API version:

- API version `v1` -> MCP server `1.x.y`
- Patch releases (`1.0.1`, `1.0.2`) for bug fixes
- Minor releases (`1.1.0`, `1.2.0`) for new tools or tool parameter additions
- Major releases (`2.0.0`) only when the API version changes to `v2`

### Testing Strategy

1. **Unit tests**: Each tool handler is tested with mocked API responses. Verify correct parameter mapping, error handling, and output formatting.

2. **Integration tests**: Start the MCP server in stdio mode, connect an MCP client, call each tool, and verify the JSON-RPC responses. Uses a mock HTTP server to simulate the REST API.

3. **End-to-end tests**: Run against the real AgentMail API (staging environment) with a test API key. Verifies real inbox creation, message sending, OTP extraction. Run on CI before tag-based releases.

```typescript
// tests/tools/inboxes.test.ts
import { describe, it, expect, vi } from "vitest";
import { createTestServer } from "../helpers.js";

describe("create_inbox", () => {
  it("creates an inbox with default parameters", async () => {
    const { server, mockApi } = await createTestServer();

    mockApi.post("/v1/inboxes").reply(201, {
      id: "01HXYZ...",
      email: "agent-a7k3m@inbox.agentmail.dev",
      display_name: null,
      status: "active",
      created_at: "2026-04-10T14:32:00.000Z",
    });

    const result = await server.callTool("create_inbox", {});

    expect(result.content[0].text).toContain("agent-a7k3m@inbox.agentmail.dev");
    expect(mockApi.isDone()).toBe(true);
  });

  it("passes display_name to the API", async () => {
    const { server, mockApi } = await createTestServer();

    mockApi.post("/v1/inboxes", (body) => {
      expect(body.display_name).toBe("My Agent");
      return true;
    }).reply(201, { id: "01HXYZ...", email: "...", display_name: "My Agent" });

    await server.callTool("create_inbox", { display_name: "My Agent" });
  });

  it("handles 429 rate limit with retry", async () => {
    const { server, mockApi } = await createTestServer();

    mockApi
      .post("/v1/inboxes")
      .reply(429, { error: { code: "RATE_LIMITED" } }, { "Retry-After": "1" })
      .post("/v1/inboxes")
      .reply(201, { id: "01HXYZ...", email: "..." });

    const result = await server.callTool("create_inbox", {});
    expect(result.content[0].text).toContain("01HXYZ");
  });
});
```

---

## 9. Example AI Agent Workflows

### Example 1: Sign Up for GitHub Using an Agent Email

This demonstrates the core value proposition of AgentMail's MCP server -- an AI agent can handle email verification flows that would otherwise require manual human intervention.

**Conversation:**

```
User: Sign up for GitHub using my agent email.

Agent: I'll create a new email inbox for your GitHub signup.

[Agent calls: create_inbox({display_name: "GitHub Signup"})]

Result: {
  "id": "01J8KR4M2N5P6Q7R8S9T0UVWXY",
  "email": "agent-k4m2n5@inbox.agentmail.dev",
  "display_name": "GitHub Signup",
  "status": "active"
}

Agent: I've created an inbox with the address agent-k4m2n5@inbox.agentmail.dev.
Please enter this email address in the GitHub signup form. Let me know when
you've submitted the form and I'll watch for the verification email.

User: Done, I submitted the signup form.

Agent: Watching for the verification email from GitHub...

[Agent calls: wait_for_otp({
  inbox_id: "01J8KR4M2N5P6Q7R8S9T0UVWXY",
  from: "github.com",
  timeout_seconds: 120
})]

// Tool blocks for 4.2 seconds until the email arrives...

Result: {
  "otp": "847293",
  "type": "numeric",
  "email_id": "01J8KR5A3B4C5D6E7F8G9H0JKL",
  "from": "noreply@github.com",
  "subject": "Your GitHub verification code",
  "received_at": "2026-04-10T14:23:04.200Z",
  "expires_at": "2026-04-10T14:33:04.200Z",
  "magic_link": null,
  "waited_seconds": 4.2
}

Agent: Your GitHub verification code is 847293. It expires in about 10 minutes.
Enter this code in the GitHub verification page to complete your signup.
```

**Tools used:** `create_inbox`, `wait_for_otp`
**Total tool calls:** 2
**Total time:** ~6 seconds (inbox creation + 4.2s wait for email)

---

### Example 2: Monitor Support Inbox for New Tickets

This demonstrates ongoing inbox monitoring -- an agent acting as a support triage assistant.

**Conversation:**

```
User: Monitor my support inbox for new tickets and summarize each one.

Agent: Let me find your support inbox first.

[Agent calls: list_inboxes({limit: 100})]

Result: {
  "data": [
    {"id": "01J8AB...", "email": "support@mail.acme.com", "display_name": "Support"},
    {"id": "01J8CD...", "email": "sales@mail.acme.com", "display_name": "Sales"},
    ...
  ]
}

Agent: Found the support inbox (support@mail.acme.com). I'll monitor it for the
next 5 minutes and report each new email.

[Agent calls: wait_for_email({
  inbox_id: "01J8AB...",
  timeout_seconds: 300
})]

// Blocks until first email arrives (47 seconds)...

Result: {
  "message": {
    "id": "msg_001",
    "from": {"address": "alice@customer.com", "name": "Alice Chen"},
    "subject": "Cannot log in to dashboard",
    "snippet": "Hi, I've been trying to log in to the dashboard since yesterday...",
    "category": "support",
    "received_at": "2026-04-10T14:31:47Z"
  },
  "waited_seconds": 47.3
}

Agent: New support ticket from Alice Chen (alice@customer.com):
  Subject: "Cannot log in to dashboard"
  Summary: Customer reports being unable to log in since yesterday.
  Category: Support

Let me check if there are related past conversations...

[Agent calls: search_messages({
  query: "login dashboard issue",
  inbox_ids: ["01J8AB..."],
  limit: 5,
  mode: "semantic"
})]

Result: {
  "results": [
    {
      "message": {"id": "msg_old_1", "subject": "Dashboard login broken after password reset", ...},
      "score": 0.87
    },
    {
      "message": {"id": "msg_old_2", "subject": "SSO login not working", ...},
      "score": 0.72
    }
  ]
}

Agent: I found 2 related past tickets:
  1. "Dashboard login broken after password reset" (87% match) -- resolved 2 weeks ago
  2. "SSO login not working" (72% match) -- resolved last month

This might be a recurring issue. I'll continue monitoring for more tickets.

[Agent calls: wait_for_email({
  inbox_id: "01J8AB...",
  timeout_seconds: 240
})]

// Continues monitoring...
```

**Tools used:** `list_inboxes`, `wait_for_email`, `search_messages`
**Pattern:** Loop of wait_for_email calls with search_messages for context enrichment.

---

### Example 3: Draft and Send a Weekly Report

This demonstrates the draft-review-send workflow where an agent composes an email, shows it to the user for approval, and sends it.

**Conversation:**

```
User: Send a weekly project update to the engineering team. Include that we
shipped the new auth system, fixed 12 bugs, and are starting the MCP server
project next week.

Agent: I'll draft the email first so you can review it before sending.

[Agent calls: list_inboxes({})]

Result: {
  "data": [
    {"id": "01J8EF...", "email": "updates@mail.acme.com", "display_name": "Project Updates"},
    ...
  ]
}

[Agent calls: create_draft({
  inbox_id: "01J8EF...",
  to: [{address: "eng-team@acme.com", name: "Engineering Team"}],
  subject: "Weekly Update: Auth System Shipped, MCP Server Next",
  body_text: "Hi team,\n\nHere's the weekly project update:\n\n## Shipped\n- New authentication system is live in production. All OAuth providers (Google, GitHub, SAML) are working. Migration from the old system completed with zero downtime.\n\n## Bug Fixes\n- Closed 12 bugs this week across the dashboard, API, and SDK. Highlights:\n  - Fixed race condition in inbox creation under high concurrency\n  - Resolved email threading issue with non-standard In-Reply-To headers\n  - Fixed timezone display in the developer console\n\n## Next Week\n- Starting the MCP Server project (P0). This will let AI agents interact with our API through Claude Code, Cursor, and other MCP-compatible tools.\n- Continuing performance optimization on the search pipeline.\n\nLet me know if you have questions.\n\nBest,\nProject Updates Bot",
  body_html: "<p>Hi team,</p><p>Here's the weekly project update:</p><h3>Shipped</h3><ul><li>New authentication system is live in production. All OAuth providers (Google, GitHub, SAML) are working. Migration from the old system completed with zero downtime.</li></ul><h3>Bug Fixes</h3><ul><li>Closed 12 bugs this week across the dashboard, API, and SDK.</li></ul><h3>Next Week</h3><ul><li>Starting the MCP Server project (P0).</li><li>Continuing performance optimization on the search pipeline.</li></ul>"
})]

Result: {
  "id": "01J8GH...",
  "inbox_id": "01J8EF...",
  "to": [{"address": "eng-team@acme.com", "name": "Engineering Team"}],
  "subject": "Weekly Update: Auth System Shipped, MCP Server Next",
  "body_text": "Hi team,...",
  "created_at": "2026-04-10T15:00:00Z"
}

Agent: I've drafted the weekly update. Here's a preview:

  To: Engineering Team <eng-team@acme.com>
  Subject: Weekly Update: Auth System Shipped, MCP Server Next

  Content covers:
  - Auth system shipped with zero-downtime migration
  - 12 bugs fixed (race condition, threading, timezone)
  - MCP Server project starting next week

  Shall I send it, or would you like to make changes?

User: Looks good, send it.

[Agent calls: send_draft({
  inbox_id: "01J8EF...",
  draft_id: "01J8GH..."
})]

Result: {
  "id": "01J8JK...",
  "ses_message_id": "0100018f-1234-5678-abcd-ef0123456789",
  "from": {"address": "updates@mail.acme.com", "name": "Project Updates"},
  "to": [{"address": "eng-team@acme.com", "name": "Engineering Team"}],
  "subject": "Weekly Update: Auth System Shipped, MCP Server Next",
  "direction": "outbound",
  "created_at": "2026-04-10T15:01:12Z"
}

Agent: Sent! The weekly update was delivered to eng-team@acme.com at 3:01 PM.
SES message ID: 0100018f-1234-5678-abcd-ef0123456789.
```

**Tools used:** `list_inboxes`, `create_draft`, `send_draft`
**Pattern:** Draft-review-send with human approval in the loop.

---

## Appendix A: MCP Resources (Read-Only Data)

In addition to tools, the MCP server exposes the following **resources** that MCP clients can read for context:

| Resource URI | Description |
|-------------|-------------|
| `agentmail://organization` | Current organization details (name, tier, settings) |
| `agentmail://usage` | Current usage and quota information |
| `agentmail://inboxes` | List of all inboxes (summary: id, email, display_name) |
| `agentmail://domains` | List of all domains with verification status |

Resources are read-only and do not require parameters. They are useful for MCP clients that load context at startup (e.g., Claude Desktop's resource panel).

---

## Appendix B: Future Tool Roadmap

Tools planned for future releases:

| Tool | Description | Target Release |
|------|------------|----------------|
| `create_auto_reply` | Set up automatic replies with AI-generated responses | v1.2.0 |
| `classify_message` | Manually trigger AI categorization on a message | v1.2.0 |
| `extract_data` | Extract structured data (invoices, receipts, addresses) from email | v1.3.0 |
| `create_pod` | Create a new pod for organizing inboxes | v1.1.0 |
| `list_pods` | List all pods | v1.1.0 |
| `query_metrics` | Query usage metrics with flexible time ranges and grouping | v1.2.0 |
| `schedule_email` | Schedule an email for future delivery | v1.1.0 |
| `batch_mark` | Mark multiple messages as read/unread/starred in one call | v1.2.0 |

---

## Appendix C: MCP Server Configuration File

For advanced deployments, the MCP server supports a YAML configuration file at `~/.agentmail/mcp-config.yaml`:

```yaml
# ~/.agentmail/mcp-config.yaml
api_key: ${AGENTMAIL_API_KEY}  # Supports env var interpolation
api_url: https://api.agentmail.aws
transport: stdio
port: 3100
host: 127.0.0.1
log_level: warn
timeout_ms: 300000

# Default tool parameters
defaults:
  inbox_id: "01HXYZ..."  # Used when inbox_id is omitted
  wait_timeout: 60
  search_mode: hybrid
  list_limit: 25

# Tool access control (optional)
# Restrict which tools are exposed to the MCP client
tools:
  enabled:
    - "*"  # All tools (default)
  disabled:
    - delete_inbox    # Prevent accidental inbox deletion
    - delete_webhook  # Prevent webhook removal
```

CLI flags override config file values. Environment variables override both.

Priority order: CLI flags > environment variables > config file > defaults.
