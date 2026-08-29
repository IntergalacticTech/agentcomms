# @agentcomms/client

Official Node.js SDK for AgentComms.

## Installation

```bash
npm install @agentcomms/client
```

## Quickstart

```typescript
import { Client } from "@agentcomms/client";

const client = new Client({ apiKey: "ak_live_your_key" });

const created = await client.agents.create({
  name: "InvoiceBot",
  provision: {
    email: { local_part: "invoice", domain: "example.com" },
  },
});

const agent = client.agents.agent(created.agent_id);

await agent.messages.send({
  to: "user@example.com",
  subject: "Hello from AgentComms",
  body: "Sent via the Node.js SDK",
});

const messages = await agent.messages.list({ limit: 25 });
await agent.messages.reply(messages[0].message_id, { body: "Received." });
```

The constructor also reads `AGENTCOMMS_API_KEY` and `AGENTCOMMS_BASE_URL` from the environment.

## Resources

| Resource | Methods |
|---|---|
| `client.agents` | `list`, `create`, `get`, `patch`, `update`, `delete`, `provision`, `agent` |
| `client.agents.agent(id).messages` | `list`, `listPage`, `get`, `send`, `reply`, `markRead`, `wait`, `extractOtp` |
| `client.agents.agent(id).channels` | `list`, `create`, `get`, `patch`, `delete` |
| `client.agents.agent(id).threads` | `list`, `get` |
| `client.agents.agent(id).drafts` | `list`, `create`, `get`, `update`, `delete`, `send` |
| `client.agents.agent(id).webhooks` | `list`, `create`, `get`, `update`, `delete` |
| `client.agents.agent(id).slack` | Slack native surfaces |
| `client.agents.agent(id).telegram` | Telegram native surfaces |
| `client.agents.agent(id).push` | Push devices and sends |
| `client.agents.agent(id).ai` | `categorize`, `extract`, `summarize`, `search` |
| `client.vault` | `list`, `create`, `get`, `getTotp`, `delete` |
| `client.personas` | `list`, `create`, `get`, `update`, `associate`, `delete` |
| `client.domains` | `list`, `create`, `get`, `verify`, `zoneFile`, `delete` |

## Error Handling

```typescript
import { AgentCommsError, NotFoundError, RateLimitError } from "@agentcomms/client";

try {
  await client.agents.get("missing");
} catch (err) {
  if (err instanceof NotFoundError) {
    console.log("Agent not found");
  } else if (err instanceof RateLimitError) {
    console.log("Rate limited, retry later");
  } else if (err instanceof AgentCommsError) {
    console.log(`API error ${err.statusCode}: ${err.message}`);
  }
}
```

## License

Apache-2.0.
