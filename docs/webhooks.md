# Webhooks

Webhooks let you receive real-time notifications when events happen in your FreeMail account. Instead of polling for new messages, you register an HTTPS endpoint and FreeMail pushes events to it.

## How Webhooks Work

1. You create a webhook via `POST /webhooks` with a URL and list of events to subscribe to.
2. FreeMail generates a signing secret (`whsec_...`) for your webhook.
3. When a subscribed event occurs, FreeMail sends an HTTP POST to your URL with the event payload.
4. Your server verifies the signature and processes the event.
5. FreeMail expects a 2xx response within 10 seconds.

## Available Events

| Event | Description |
|-------|-------------|
| `message.received` | A new inbound email was received in an inbox |
| `message.sent` | An outbound email was successfully sent via SES |
| `message.bounced` | An outbound email bounced (hard or soft bounce) |
| `message.complained` | A recipient marked an outbound email as spam |
| `message.delayed` | An outbound email delivery is delayed |
| `inbox.created` | A new inbox was created |
| `inbox.deleted` | An inbox was deleted |
| `domain.verified` | A custom domain passed DNS verification |
| `domain.failed` | A custom domain failed DNS verification |
| `subscription.updated` | The organization's billing subscription changed |

## Setting Up a Webhook

### 1. Create the Webhook

```bash
curl -X POST https://api.victorymail.dev/v1/webhooks \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://api.yourapp.com/webhooks/freemail",
    "events": ["message.received", "message.bounced"]
  }'
```

Response:

```json
{
  "id": "01HXYZ...",
  "url": "https://api.yourapp.com/webhooks/freemail",
  "events": ["message.received", "message.bounced"],
  "status": "active",
  "secret": "whsec_a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
  "filter": {},
  "delivery_stats": {
    "total": 0,
    "success": 0,
    "failed": 0,
    "last_delivered_at": null,
    "last_failed_at": null
  },
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

Save the `secret` value -- you will need it to verify webhook signatures.

### 2. Filter by Pod or Inbox (Optional)

You can scope a webhook to specific pods or inboxes using the `filter` field:

```bash
curl -X POST https://api.victorymail.dev/v1/webhooks \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://api.yourapp.com/webhooks/freemail",
    "events": ["message.received"],
    "filter": {
      "pod_ids": ["01HXYZ_POD_1"],
      "inbox_ids": ["01HXYZ_INBOX_1", "01HXYZ_INBOX_2"]
    }
  }'
```

## Webhook Payload

Every webhook delivery is an HTTP POST with these headers:

| Header | Description |
|--------|-------------|
| `Content-Type` | `application/json` |
| `X-FreeMail-Signature` | HMAC-SHA256 signature: `sha256=<hex>` |
| `X-FreeMail-Event` | Event type (e.g., `message.received`) |

The request body contains:

```json
{
  "event": "message.received",
  "data": {
    "message_id": "01HXYZ...",
    "inbox_id": "01HXYZ...",
    "from": "sender@example.com",
    "subject": "Hello!",
    "received_at": "2025-01-15T11:00:00Z"
  },
  "timestamp": "2025-01-15T11:00:01Z"
}
```

## Verifying Webhook Signatures

Every webhook delivery is signed with your webhook's secret using HMAC-SHA256. Always verify the signature before processing the event.

The signature is computed over the raw JSON request body. To verify:

1. Get the `X-FreeMail-Signature` header value (format: `sha256=<hex_digest>`)
2. Compute HMAC-SHA256 of the raw request body using your webhook secret
3. Compare the computed signature with the one in the header

### Python Example

```python
import hashlib
import hmac
from flask import Flask, request, abort

app = Flask(__name__)
WEBHOOK_SECRET = "whsec_your_secret_here"

@app.route("/webhooks/freemail", methods=["POST"])
def handle_webhook():
    # Get the signature from the header
    signature_header = request.headers.get("X-FreeMail-Signature", "")
    if not signature_header.startswith("sha256="):
        abort(400, "Missing signature")

    received_signature = signature_header[7:]  # Remove "sha256=" prefix

    # Compute expected signature
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        request.data,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(received_signature, expected_signature):
        abort(401, "Invalid signature")

    # Process the event
    payload = request.json
    event_type = payload["event"]
    data = payload["data"]

    if event_type == "message.received":
        print(f"New email from {data['from']}: {data['subject']}")
    elif event_type == "message.bounced":
        print(f"Message {data['message_id']} bounced")

    return "", 200
```

### Node.js Example

```typescript
import express from "express";
import crypto from "crypto";

const app = express();
const WEBHOOK_SECRET = "whsec_your_secret_here";

app.post(
  "/webhooks/freemail",
  express.raw({ type: "application/json" }),
  (req, res) => {
    const signatureHeader = req.headers["x-freemail-signature"] as string;
    if (!signatureHeader?.startsWith("sha256=")) {
      return res.status(400).send("Missing signature");
    }

    const receivedSignature = signatureHeader.slice(7);

    // Compute expected signature
    const expectedSignature = crypto
      .createHmac("sha256", WEBHOOK_SECRET)
      .update(req.body)
      .digest("hex");

    // Constant-time comparison
    if (
      !crypto.timingSafeEqual(
        Buffer.from(receivedSignature),
        Buffer.from(expectedSignature)
      )
    ) {
      return res.status(401).send("Invalid signature");
    }

    // Process the event
    const payload = JSON.parse(req.body.toString());
    const { event, data } = payload;

    switch (event) {
      case "message.received":
        console.log(`New email from ${data.from}: ${data.subject}`);
        break;
      case "message.bounced":
        console.log(`Message ${data.message_id} bounced`);
        break;
    }

    res.status(200).send();
  }
);

app.listen(3000);
```

## Retry Behavior

If your endpoint returns a non-2xx status code or does not respond within 10 seconds, FreeMail considers the delivery failed. Failed deliveries are retried via the SQS queue with standard retry behavior.

The `delivery_stats` on your webhook object tracks delivery success and failure counts:

```json
{
  "delivery_stats": {
    "total": 150,
    "success": 148,
    "failed": 2,
    "last_delivered_at": "2025-01-15T11:30:00Z",
    "last_failed_at": "2025-01-15T10:15:00Z"
  }
}
```

## Managing Webhooks

### Pause a Webhook

```bash
curl -X PATCH https://api.victorymail.dev/v1/webhooks/WEBHOOK_ID \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "paused"}'
```

### Update Subscribed Events

```bash
curl -X PATCH https://api.victorymail.dev/v1/webhooks/WEBHOOK_ID \
  -H "x-api-key: am_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"events": ["message.received", "message.sent", "message.bounced"]}'
```

### Delete a Webhook

```bash
curl -X DELETE https://api.victorymail.dev/v1/webhooks/WEBHOOK_ID \
  -H "x-api-key: am_live_YOUR_KEY"
```

## Best Practices

- Always verify webhook signatures before processing events.
- Respond to webhooks quickly (within 10 seconds). If you need to do heavy processing, acknowledge the webhook immediately and process asynchronously.
- Handle duplicate events gracefully. Use `message_id` or other identifiers for idempotency.
- Use filters to limit webhook deliveries to only the pods or inboxes you care about.
- Monitor `delivery_stats` to detect issues with your endpoint.
