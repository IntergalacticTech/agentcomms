# SDK Documentation

FreeMail provides official SDKs for Python and Node.js. Both SDKs cover the full API surface and handle authentication, pagination, and error handling.

---

## Python SDK

### Installation

```bash
pip install git+https://github.com/IntergalacticTech/freemail.git#subdirectory=sdks/python
```

### Initialization

```python
from freemail import FreeMail

client = FreeMail("am_live_YOUR_KEY")

# Custom base URL (optional)
client = FreeMail("am_live_YOUR_KEY", base_url="https://api.victorymail.dev/v1")
```

### Context Manager

The client can be used as a context manager:

```python
with FreeMail("am_live_YOUR_KEY") as client:
    inboxes = client.inboxes.list()
```

### Resources

#### client.inboxes

| Method | Description |
|--------|-------------|
| `client.inboxes.list(**kwargs)` | List all inboxes. Accepts `limit`, `page_token`, `order`, `pod_id`. |
| `client.inboxes.get(inbox_id)` | Get a single inbox by ID. |
| `client.inboxes.create(**kwargs)` | Create an inbox. Accepts `display_name`, `email`, `pod_id`, `settings`, `forwarding`. |
| `client.inboxes.update(inbox_id, **kwargs)` | Update inbox fields. Accepts `display_name`, `settings`, `forwarding`. |
| `client.inboxes.delete(inbox_id)` | Soft-delete an inbox. |
| `client.inboxes.wait_for_message(inbox_id, **kwargs)` | Long-poll for a matching message. Accepts `timeout`, `filter`. |
| `client.inboxes.extract_otp(inbox_id, **kwargs)` | Wait for email and extract OTP. Accepts `sender`, `subject_contains`, `after`, `timeout`. |

#### client.messages

| Method | Description |
|--------|-------------|
| `client.messages.list(inbox_id, **kwargs)` | List messages. Accepts `limit`, `page_token`, `order`. |
| `client.messages.get(inbox_id, message_id)` | Get a message with full body. |
| `client.messages.send(inbox_id, **kwargs)` | Send a message. Requires `to`, `subject`, and at least one of `body_text`/`body_html`. |
| `client.messages.reply(inbox_id, message_id, **kwargs)` | Reply to a message. Requires `body_text` or `body_html`. |
| `client.messages.forward(inbox_id, message_id, **kwargs)` | Forward a message. Requires `to`. |
| `client.messages.update(inbox_id, message_id, **kwargs)` | Update message metadata. Accepts `is_read`, `is_starred`, `is_trash`, `labels`. |

#### client.pods

| Method | Description |
|--------|-------------|
| `client.pods.list(**kwargs)` | List all pods. |
| `client.pods.get(pod_id)` | Get a single pod. |
| `client.pods.create(**kwargs)` | Create a pod. Requires `name`. |
| `client.pods.delete(pod_id)` | Delete an empty pod. |

#### client.domains

| Method | Description |
|--------|-------------|
| `client.domains.list(**kwargs)` | List all domains. |
| `client.domains.get(domain_id)` | Get domain details and verification status. |
| `client.domains.create(**kwargs)` | Register a domain. Requires `domain`. |
| `client.domains.verify(domain_id)` | Trigger DNS verification. |
| `client.domains.delete(domain_id)` | Delete a domain registration. |

#### client.webhooks

| Method | Description |
|--------|-------------|
| `client.webhooks.list(**kwargs)` | List all webhooks. |
| `client.webhooks.create(**kwargs)` | Create a webhook. Requires `url`, `events`. |
| `client.webhooks.update(webhook_id, **kwargs)` | Update webhook fields. |
| `client.webhooks.delete(webhook_id)` | Delete a webhook. |

#### client.api_keys

| Method | Description |
|--------|-------------|
| `client.api_keys.list(**kwargs)` | List all API keys (prefix only, not the full key). |
| `client.api_keys.create(**kwargs)` | Create a new API key. Requires `name`, `scope`. |
| `client.api_keys.delete(key_id)` | Revoke an API key. |

### Full Example

```python
from freemail import FreeMail

client = FreeMail("am_live_YOUR_KEY")

# Create a pod for organizing inboxes
pod = client.pods.create(name="Signup Automation")

# Create an inbox in the pod
inbox = client.inboxes.create(
    display_name="Signup Bot",
    pod_id=pod["id"],
)
print(f"Inbox created: {inbox['email']}")

# Send an email
msg = client.messages.send(
    inbox["id"],
    to=[{"address": "user@example.com"}],
    subject="Welcome!",
    body_text="Thanks for signing up.",
    body_html="<h1>Thanks for signing up.</h1>",
)

# List messages
messages = client.messages.list(inbox["id"], limit=10)
for m in messages["data"]:
    print(f"  {m['direction']}: {m['subject']}")

# Wait for a verification email and extract the OTP
otp = client.inboxes.extract_otp(
    inbox["id"],
    sender="noreply@service.com",
    subject_contains="verification",
    timeout=25,
)
if otp["code"]:
    print(f"OTP: {otp['code']}")
else:
    print("No OTP found, raw body:")
    print(otp.get("body_text", ""))

# Set up a webhook
webhook = client.webhooks.create(
    url="https://api.yourapp.com/hooks/freemail",
    events=["message.received"],
)
print(f"Webhook secret: {webhook['secret']}")

# Clean up
client.inboxes.delete(inbox["id"])
client.pods.delete(pod["id"])
```

### Error Handling

The SDK raises exceptions for API errors. Catch them to handle specific cases:

```python
from freemail import FreeMail

client = FreeMail("am_live_YOUR_KEY")

try:
    inbox = client.inboxes.get("nonexistent-id")
except Exception as e:
    print(f"Error: {e}")
```

---

## Node.js SDK

### Installation

```bash
npm install IntergalacticTech/freemail#main --install-strategy=shallow
```

### Initialization

```typescript
import { FreeMail } from "@freemail/sdk";

const client = new FreeMail("am_live_YOUR_KEY");

// Custom base URL (optional)
const client = new FreeMail("am_live_YOUR_KEY", {
  baseUrl: "https://api.victorymail.dev/v1",
});
```

### Resources

#### client.inboxes

| Method | Description |
|--------|-------------|
| `client.inboxes.list(options?)` | List inboxes. Options: `limit`, `page_token`, `order`, `pod_id`. |
| `client.inboxes.get(inboxId)` | Get a single inbox. |
| `client.inboxes.create(options?)` | Create an inbox. Options: `display_name`, `email`, `pod_id`, `settings`, `forwarding`. |
| `client.inboxes.update(inboxId, options)` | Update inbox fields. |
| `client.inboxes.delete(inboxId)` | Soft-delete an inbox. |
| `client.inboxes.waitForMessage(inboxId, options?)` | Long-poll for a matching message. |
| `client.inboxes.extractOtp(inboxId, options?)` | Wait for email and extract OTP. |

#### client.messages

| Method | Description |
|--------|-------------|
| `client.messages.list(inboxId, options?)` | List messages in an inbox. |
| `client.messages.get(inboxId, messageId)` | Get a message with full body. |
| `client.messages.send(inboxId, options)` | Send a message. |
| `client.messages.reply(inboxId, messageId, options)` | Reply to a message. |
| `client.messages.forward(inboxId, messageId, options)` | Forward a message. |
| `client.messages.update(inboxId, messageId, options)` | Update message metadata. |

#### client.pods

| Method | Description |
|--------|-------------|
| `client.pods.list(options?)` | List all pods. |
| `client.pods.get(podId)` | Get a single pod. |
| `client.pods.create(options)` | Create a pod. |
| `client.pods.delete(podId)` | Delete an empty pod. |

#### client.domains

| Method | Description |
|--------|-------------|
| `client.domains.list(options?)` | List all domains. |
| `client.domains.get(domainId)` | Get domain details. |
| `client.domains.create(options)` | Register a domain. |
| `client.domains.verify(domainId)` | Trigger DNS verification. |
| `client.domains.delete(domainId)` | Delete a domain. |

#### client.webhooks

| Method | Description |
|--------|-------------|
| `client.webhooks.list(options?)` | List all webhooks. |
| `client.webhooks.create(options)` | Create a webhook. |
| `client.webhooks.update(webhookId, options)` | Update a webhook. |
| `client.webhooks.delete(webhookId)` | Delete a webhook. |

#### client.apiKeys

| Method | Description |
|--------|-------------|
| `client.apiKeys.list(options?)` | List API keys. |
| `client.apiKeys.create(options)` | Create an API key. |
| `client.apiKeys.delete(keyId)` | Revoke an API key. |

### Full Example

```typescript
import { FreeMail } from "@freemail/sdk";

const client = new FreeMail("am_live_YOUR_KEY");

// Create a pod
const pod = await client.pods.create({ name: "Signup Automation" });

// Create an inbox in the pod
const inbox = await client.inboxes.create({
  display_name: "Signup Bot",
  pod_id: pod.id,
});
console.log(`Inbox created: ${inbox.email}`);

// Send an email
const msg = await client.messages.send(inbox.id, {
  to: [{ address: "user@example.com" }],
  subject: "Welcome!",
  body_text: "Thanks for signing up.",
  body_html: "<h1>Thanks for signing up.</h1>",
});

// List messages
const messages = await client.messages.list(inbox.id, { limit: 10 });
for (const m of messages.data) {
  console.log(`  ${m.direction}: ${m.subject}`);
}

// Wait for a verification email and extract the OTP
const otp = await client.inboxes.extractOtp(inbox.id, {
  sender: "noreply@service.com",
  subject_contains: "verification",
  timeout: 25,
});
if (otp.code) {
  console.log(`OTP: ${otp.code}`);
} else {
  console.log("No OTP found, raw body:", otp.body_text);
}

// Set up a webhook
const webhook = await client.webhooks.create({
  url: "https://api.yourapp.com/hooks/freemail",
  events: ["message.received"],
});
console.log(`Webhook secret: ${webhook.secret}`);

// Clean up
await client.inboxes.delete(inbox.id);
await client.pods.delete(pod.id);
```

### Error Handling

The SDK provides typed error classes:

```typescript
import {
  FreemailAPIError,
  NotFoundError,
  RateLimitError,
} from "@freemail/sdk";

try {
  await client.inboxes.get("nonexistent");
} catch (err) {
  if (err instanceof NotFoundError) {
    console.log("Inbox not found");
  } else if (err instanceof RateLimitError) {
    console.log("Rate limited, retry later");
  } else if (err instanceof FreemailAPIError) {
    console.log(`API error ${err.statusCode}: ${err.message}`);
  }
}
```
