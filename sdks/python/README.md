# AgentComms Python SDK

Python SDK for AgentComms, the agent communications hub.

## Install

```bash
pip install agentcomms
```

For local development from this repo:

```bash
cd sdks/python
pip install -e .
```

## Quickstart

```python
from agentcomms import Client

client = Client(
    api_key="ak_live_your_key",
    base_url="https://api.your-domain.com/v1",
)

agent = client.agents.create(
    name="InvoiceBot",
    provision={"email": {"local_part": "invoice", "domain": "your-domain.com"}},
)

agent_id = agent["agent_id"]
hub = client.agents(agent_id)

hub.messages.send(
    to="person@example.com",
    subject="Hello",
    body="Sent through AgentComms",
)

for msg in hub.messages.list():
    print(msg.message_id, msg.channel, msg.body_text)
```

## Resources

| Resource | Methods |
|---|---|
| `client.agents` | list, create, get, update, delete |
| `client.agents("agt_...").messages` | list, list_page, get, send, reply, mark_read, wait, extract_otp |
| `client.agents("agt_...").channels` | list, get, create, patch, delete |
| `client.agents("agt_...").threads` | list, get |
| `client.agents("agt_...").drafts` | list, get, create, patch, delete |
| `client.agents("agt_...").webhooks` | list, get, create, patch, delete |
| `client.agents("agt_...").slack` | workspace-native Slack actions |
| `client.agents("agt_...").telegram` | chat-native Telegram actions |
| `client.agents("agt_...").push` | device registration and push send |
| `client.vault` | encrypted org vault and TOTP |
| `client.personas` | reusable identity profiles |
| `client.domains` | SES domain lifecycle |

## License

Apache-2.0. See the repository root `LICENSE`.
