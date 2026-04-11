# @freemail/sdk

Node.js SDK for the FreeMail email platform.

## Installation

```bash
npm install @freemail/sdk
```

## Quickstart

```typescript
import { FreeMail } from "@freemail/sdk";

const client = new FreeMail("am_live_your_key");

// Create an inbox
const inbox = await client.inboxes.create({ display_name: "My Agent" });

// Send a message
const msg = await client.messages.send(inbox.id, {
  to: [{ address: "user@example.com" }],
  subject: "Hello from FreeMail!",
  body_text: "Sent via the Node.js SDK",
});

// Wait for an inbound message and extract an OTP
const otp = await client.inboxes.extractOtp(inbox.id, {
  sender: "noreply@example.com",
});
console.log(`OTP: ${otp.code}`);
```

## Resources

| Resource          | Methods                                        |
| ----------------- | ---------------------------------------------- |
| `client.inboxes`  | list, get, create, update, delete, waitForMessage, extractOtp |
| `client.messages` | list, get, send, reply, forward, update        |
| `client.pods`     | list, get, create, delete                      |
| `client.domains`  | list, get, create, verify, delete              |
| `client.webhooks` | list, create, update, delete                   |
| `client.apiKeys`  | list, create, delete                           |

## Error Handling

```typescript
import { FreemailAPIError, NotFoundError, RateLimitError } from "@freemail/sdk";

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
