# SDK Documentation

AgentComms provides first-party Python and Node SDKs for the agent-centric API. Both SDKs use `AGENTCOMMS_API_KEY` and default to `https://api.agentcomms.dev/v1`.

## Python

Install from a checkout:

```bash
pip install -e sdks/python
```

Basic usage:

```python
from agentcomms import Client

client = Client(api_key="ak_live_YOUR_KEY")

created = client.agents.create(
    name="InvoiceBot",
    provision={
        "email": {"local_part": "invoice", "domain": "example.com"},
        "telegram": {"bot_token": "..."},
    },
)

agent = client.agents(created["agent_id"])

for msg in agent.messages.list(channels=["email", "telegram"], limit=25):
    print(f"[{msg.channel}] {msg.from_.address}: {msg.body_text}")

agent.messages.send(
    to="alice@example.com",
    subject="Status",
    body="Done.",
)
```

Environment-based initialization:

```bash
export AGENTCOMMS_API_KEY=ak_live_YOUR_KEY
export AGENTCOMMS_BASE_URL=https://api.agentcomms.dev/v1
```

```python
from agentcomms import Client

client = Client()
```

Agent resources:

| Resource | Examples |
|---|---|
| Agents | `client.agents.create(...)`, `client.agents.list()`, `client.agents.get(agent_id)`, `client.agents.delete(agent_id)` |
| Messages | `client.agents(agent_id).messages.list()`, `.get(message_id)`, `.send(...)`, `.reply(...)`, `.mark_read(...)`, `.wait(...)`, `.extract_otp(...)` |
| Channels | `client.agents(agent_id).channels.list()`, `.create(...)`, `.delete(channel_id)` |
| Threads | `client.agents(agent_id).threads.list()`, `.get(thread_key)` |
| Drafts | `client.agents(agent_id).drafts.list()`, `.create(...)`, `.update(...)`, `.send(...)`, `.delete(...)` |
| Webhooks | `client.agents(agent_id).webhooks.list()`, `.create(...)`, `.update(...)`, `.delete(...)` |
| Native Slack | `client.agents(agent_id).slack.list_workspaces()`, `.list_channels(team_id)`, `.post_message(...)` |
| Native Telegram | `client.agents(agent_id).telegram.list_chats()`, `.post_message(...)` |
| Push | `client.agents(agent_id).push.register_device(...)`, `.send(...)` |
| AI | `client.agents(agent_id).ai.categorize(...)`, `.extract(...)`, `.summarize(...)`, `.search(...)` |
| Vault | `client.vault.create(...)`, `.list()`, `.get(vault_id)`, `.get_totp(vault_id)`, `.delete(vault_id)` |
| Personas | `client.personas.create(...)`, `.list()`, `.associate(...)`, `.delete(persona_id)` |
| Domains | `client.domains.create(domain_name="example.com")`, `.list()`, `.verify(domain_id)`, `.delete(domain_id)` |

The SDK raises `AgentCommsError` subclasses for API failures and retries idempotent requests on `429` and `5xx`.

## Node.js

Install from npm or from a checkout:

```bash
npm install @agentcomms/client
```

```bash
cd sdks/node
npm install
npm run build
```

Basic usage:

```typescript
import { Client } from "@agentcomms/client";

const client = new Client({ apiKey: "ak_live_YOUR_KEY" });

const created = await client.agents.create({
  name: "InvoiceBot",
  provision: {
    email: { local_part: "invoice", domain: "example.com" },
    telegram: { bot_token: "..." },
  },
});

const agent = client.agents.agent(created.agent_id);

const messages = await agent.messages.list({
  channels: ["email", "telegram"],
  limit: 25,
});

for (const msg of messages) {
  console.log(`[${msg.channel}] ${msg.from.address}: ${msg.body_text}`);
}

await agent.messages.reply(messages[0].message_id, {
  body: "Got it, processing.",
});
```

Environment-based initialization:

```bash
export AGENTCOMMS_API_KEY=ak_live_YOUR_KEY
export AGENTCOMMS_BASE_URL=https://api.agentcomms.dev/v1
```

```typescript
import { Client } from "@agentcomms/client";

const client = new Client();
```

Node resources:

| Resource | Examples |
|---|---|
| Agents | `client.agents.create(...)`, `client.agents.list()`, `client.agents.get(agentId)`, `client.agents.delete(agentId)` |
| Messages | `client.agents.agent(agentId).messages.list()`, `.listPage(...)`, `.get(messageId)`, `.send(...)`, `.reply(...)`, `.markRead(...)`, `.wait(...)`, `.extractOtp(...)` |
| Channels | `client.agents.agent(agentId).channels.list()`, `.create(...)`, `.delete(channelId)` |
| Threads | `client.agents.agent(agentId).threads.list()`, `.get(threadKey)` |
| Drafts | `client.agents.agent(agentId).drafts.list()`, `.create(...)`, `.update(...)`, `.send(...)`, `.delete(...)` |
| Webhooks | `client.agents.agent(agentId).webhooks.list()`, `.create(...)`, `.update(...)`, `.delete(...)` |
| Native Slack | `client.agents.agent(agentId).slack.listWorkspaces()`, `.listChannels(teamId)`, `.postMessage(...)` |
| Native Telegram | `client.agents.agent(agentId).telegram.listChats()`, `.postMessage(...)` |
| Push | `client.agents.agent(agentId).push.registerDevice(...)`, `.send(...)` |
| AI | `client.agents.agent(agentId).ai.categorize(...)`, `.extract(...)`, `.summarize(...)`, `.search(...)` |
| Vault | `client.vault.create(...)`, `.list()`, `.get(vaultId)`, `.getTotp(vaultId)`, `.delete(vaultId)` |
| Personas | `client.personas.create(...)`, `.list()`, `.associate(...)`, `.delete(personaId)` |
| Domains | `client.domains.create({ domain_name: "example.com" })`, `.list()`, `.verify(domainId)`, `.delete(domainId)` |

## Compatibility

The old `freemail` Python package shim remains in the repository for migration, but new code should import `agentcomms`. The old inbox/pod API is legacy; new integrations should model durable actors as agents and provision channels underneath them.

## License

Apache-2.0. See [LICENSE](../LICENSE).
