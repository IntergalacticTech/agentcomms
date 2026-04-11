# FreeMail Python SDK

Python SDK for the FreeMail email-as-a-service platform.

## Install

```bash
pip install git+https://github.com/IntergalacticTech/FreeMail.ai.git#subdirectory=sdks/python
```

## Quickstart

```python
from freemail import FreeMail

client = FreeMail("am_live_your_api_key")

# Create an inbox
inbox = client.inboxes.create(display_name="My Agent")

# Send an email
msg = client.messages.send(
    inbox["id"],
    to=[{"address": "user@example.com"}],
    subject="Hello!",
    body_text="Sent from FreeMail",
)

# Wait for a reply and extract OTP
otp = client.inboxes.extract_otp(inbox["id"], sender="noreply@example.com")
print(f"OTP: {otp['code']}")
```

## Resources

The client exposes the following resource namespaces:

- `client.inboxes` -- create, list, get, update, delete inboxes; wait for messages; extract OTPs
- `client.messages` -- list, get, send, reply, forward, update messages
- `client.pods` -- create, list, get, delete pods
- `client.domains` -- create, list, get, verify, delete domains
- `client.webhooks` -- create, list, update, delete webhooks
- `client.api_keys` -- create, list, delete API keys

## Configuration

```python
# Custom base URL
client = FreeMail("am_live_...", base_url="https://your-custom-endpoint.com/v1")
```

## Context manager

```python
with FreeMail("am_live_...") as client:
    inboxes = client.inboxes.list()
```
