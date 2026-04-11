# FreeMail MCP Server

MCP (Model Context Protocol) server that exposes FreeMail email platform operations as tools for AI agents.

## Configuration

Set the `FREEMAIL_API_KEY` environment variable to your FreeMail API key. Optionally set `FREEMAIL_API_URL` to override the default API base URL.

## Build

```bash
npm install
npm run build
```

## Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "freemail": {
      "command": "node",
      "args": ["/path/to/mcp-server/dist/index.js"],
      "env": {
        "FREEMAIL_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `create_inbox` | Create a new email inbox |
| `list_inboxes` | List all inboxes |
| `send_email` | Send an email from an inbox |
| `list_messages` | List messages in an inbox |
| `get_message` | Get a specific message with full body |
| `reply_to_message` | Reply to a message |
| `wait_for_email` | Wait for a new email matching criteria |
| `extract_otp` | Wait for email and extract verification code |
| `delete_inbox` | Delete an inbox |
| `get_organization` | Get current organization info |
