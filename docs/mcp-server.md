# MCP Server Guide

The FreeMail MCP (Model Context Protocol) server exposes FreeMail operations as tools that AI agents can call directly. This enables AI assistants like Claude to create inboxes, send emails, wait for replies, and extract OTP codes as part of their workflows.

## What is MCP?

Model Context Protocol (MCP) is an open standard for connecting AI models to external tools and data sources. When an AI agent has access to the FreeMail MCP server, it can autonomously manage email inboxes -- for example, signing up for a service, receiving a verification email, and extracting the OTP code.

## Installation

### Prerequisites

- Node.js 18+
- A FreeMail API key (see [Quickstart](quickstart.md))

### Build from Source

```bash
cd mcp-server
npm install
npm run build
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FREEMAIL_API_KEY` | Yes | Your FreeMail API key |
| `FREEMAIL_API_URL` | No | Override the default API base URL (defaults to `https://api.victorymail.dev/v1`) |

### Claude Desktop

Add the FreeMail MCP server to your Claude Desktop config file at `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "freemail": {
      "command": "node",
      "args": ["/path/to/mcp-server/dist/index.js"],
      "env": {
        "FREEMAIL_API_KEY": "am_live_YOUR_KEY"
      }
    }
  }
}
```

### OpenClaw / Other MCP Hosts

Any MCP-compatible host can run the FreeMail server. Set the command to `node /path/to/mcp-server/dist/index.js` and provide the `FREEMAIL_API_KEY` environment variable.

## Available Tools

The MCP server exposes the following tools:

| Tool | Description | Required Parameters |
|------|-------------|---------------------|
| `create_inbox` | Create a new email inbox | None (optional: `display_name`, `pod_id`) |
| `list_inboxes` | List all inboxes in the organization | None (optional: `pod_id`, `limit`) |
| `send_email` | Send an email from an inbox | `inbox_id`, `to`, `subject` (optional: `body_text`, `body_html`) |
| `list_messages` | List messages in an inbox | `inbox_id` (optional: `limit`) |
| `get_message` | Get a specific message with full body | `inbox_id`, `message_id` |
| `reply_to_message` | Reply to a message | `inbox_id`, `message_id`, `body_text` (optional: `body_html`) |
| `wait_for_email` | Wait for a new email matching criteria | `inbox_id` (optional: `timeout`, `sender`, `subject_contains`) |
| `extract_otp` | Wait for email and extract verification code | `inbox_id` (optional: `timeout`, `sender`, `subject_contains`) |
| `delete_inbox` | Delete an inbox | `inbox_id` |
| `get_organization` | Get current organization info | None |

## Tool Details

### create_inbox

Creates a new email inbox and returns its details including the assigned email address.

**Parameters:**

```json
{
  "display_name": "My Agent Inbox",
  "pod_id": "01HXYZ..."
}
```

**Returns:** Inbox object with `id`, `email`, `display_name`, `status`.

### send_email

Sends an email from an inbox.

**Parameters:**

```json
{
  "inbox_id": "01HXYZ...",
  "to": [{"address": "user@example.com"}],
  "subject": "Hello!",
  "body_text": "Plain text content",
  "body_html": "<p>HTML content</p>"
}
```

### wait_for_email

Long-polls for up to 25 seconds for a new email matching the provided criteria.

**Parameters:**

```json
{
  "inbox_id": "01HXYZ...",
  "timeout": 25,
  "sender": "noreply@service.com",
  "subject_contains": "verification"
}
```

### extract_otp

Waits for a matching email and automatically extracts the OTP/verification code from the body. Supports numeric codes (4-8 digits), dash-separated codes (e.g., `123-456`), and alphanumeric codes (6-10 characters).

**Parameters:**

```json
{
  "inbox_id": "01HXYZ...",
  "timeout": 25,
  "sender": "noreply@service.com",
  "subject_contains": "verification"
}
```

**Returns:**

```json
{
  "code": "482917",
  "message_id": "01HXYZ...",
  "from": "noreply@service.com",
  "subject": "Your verification code"
}
```

## Example Usage with AI Agents

Here is how an AI agent might use the FreeMail MCP tools to sign up for a service:

### Scenario: Autonomous Service Signup

An AI agent needs to create an account on a third-party service that requires email verification:

1. **Agent calls `create_inbox`** -- gets a fresh email address like `r7k3m9pq@victorymail.dev`
2. **Agent navigates to the service's signup page** and enters the inbox email address
3. **Agent calls `extract_otp`** with `sender: "noreply@service.com"` -- FreeMail waits for the verification email and returns the code
4. **Agent enters the OTP code** on the service's verification page
5. **Agent calls `delete_inbox`** to clean up

### Scenario: Email Monitoring

An AI agent monitors a support inbox and replies to common questions:

1. **Agent calls `list_messages`** to check for new messages
2. **Agent calls `get_message`** to read the full content of unread messages
3. **Agent processes the message** and generates a response
4. **Agent calls `reply_to_message`** to send the reply

### Scenario: Notifications

An AI agent sends status update emails to stakeholders:

1. **Agent calls `create_inbox`** with `display_name: "Status Bot"`
2. **Agent calls `send_email`** with the update content and recipient list
3. **Agent calls `wait_for_email`** to check for any bounce notifications or replies

## Troubleshooting

### "FREEMAIL_API_KEY not set"

Ensure the environment variable is set in your MCP server configuration. In Claude Desktop, add it to the `env` field in the config JSON.

### Tools not appearing

- Verify the MCP server builds successfully: `npm run build`
- Check that the path in your config points to `dist/index.js`
- Restart your MCP host (Claude Desktop, etc.) after configuration changes

### Timeout errors on wait_for_email / extract_otp

The maximum timeout is 25 seconds. If you need to wait longer, call the tool repeatedly. Consider using webhooks for production workflows that need to handle longer delays.
