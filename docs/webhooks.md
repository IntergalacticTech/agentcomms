# Webhooks

Webhooks deliver AgentComms events to your HTTPS endpoint. They are scoped under an agent.

## Create a Webhook

```bash
curl -sS -X POST https://api.agentcomms.dev/v1/agents/agt_.../webhooks \
  -H "Authorization: Bearer ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://api.example.com/webhooks/agentcomms",
    "events": ["message.received", "message.sent"]
  }'
```

Response:

```json
{
  "webhook_id": "wh_...",
  "agent_id": "agt_...",
  "url": "https://api.example.com/webhooks/agentcomms",
  "events": ["message.received", "message.sent"],
  "status": "active",
  "secret": "whsec_..."
}
```

Store `secret` securely. It is used to verify deliveries.

## Events

Core events should use stable names:

| Event | Meaning |
|---|---|
| `message.received` | Inbound direct message or explicit mention persisted |
| `message.sent` | Outbound message accepted/sent |
| `message.failed` | Outbound send failed |
| `channel.created` | Agent channel was provisioned or bridged |
| `channel.deleted` | Agent channel was removed |
| `domain.verified` | Domain verification succeeded |

Adapters may add provider-specific event metadata in `data.channel_native`.

## Delivery Shape

```json
{
  "event": "message.received",
  "agent_id": "agt_...",
  "data": {
    "message_id": "msg_...",
    "channel": "email",
    "from": {"address": "alice@example.com"},
    "subject": "Question",
    "received_at": "2026-08-29T18:00:00+00:00"
  },
  "timestamp": "2026-08-29T18:00:01+00:00"
}
```

Recommended headers:

| Header | Description |
|---|---|
| `Content-Type` | `application/json` |
| `X-AgentComms-Signature` | HMAC-SHA256 signature, `sha256=<hex>` |
| `X-AgentComms-Event` | Event name |

## Verify Signatures

Compute HMAC-SHA256 over the raw request body with the webhook secret, then compare in constant time.

Python:

```python
import hashlib
import hmac
from flask import Flask, abort, request

app = Flask(__name__)
WEBHOOK_SECRET = "whsec_your_secret"

@app.post("/webhooks/agentcomms")
def handle_agentcomms():
    header = request.headers.get("X-AgentComms-Signature", "")
    if not header.startswith("sha256="):
        abort(400, "missing signature")

    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        request.data,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(header[7:], expected):
        abort(401, "invalid signature")

    payload = request.get_json()
    return {"ok": True, "event": payload["event"]}
```

Node:

```typescript
import crypto from "crypto";
import express from "express";

const app = express();
const secret = "whsec_your_secret";

app.post("/webhooks/agentcomms", express.raw({ type: "application/json" }), (req, res) => {
  const header = String(req.headers["x-agentcomms-signature"] ?? "");
  if (!header.startsWith("sha256=")) return res.status(400).send("missing signature");

  const expected = crypto.createHmac("sha256", secret).update(req.body).digest("hex");
  const received = header.slice(7);

  if (!crypto.timingSafeEqual(Buffer.from(received), Buffer.from(expected))) {
    return res.status(401).send("invalid signature");
  }

  res.status(204).send();
});
```

## Manage Webhooks

```bash
curl -sS https://api.agentcomms.dev/v1/agents/agt_.../webhooks \
  -H "Authorization: Bearer ak_live_YOUR_KEY"
```

```bash
curl -sS -X PATCH https://api.agentcomms.dev/v1/agents/agt_.../webhooks/wh_... \
  -H "Authorization: Bearer ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"events": ["message.received"]}'
```

```bash
curl -sS -X DELETE https://api.agentcomms.dev/v1/agents/agt_.../webhooks/wh_... \
  -H "Authorization: Bearer ak_live_YOUR_KEY"
```

## Operational Notes

- Acknowledge quickly with a 2xx response and do slow work asynchronously.
- Handle duplicate deliveries with `event_id` or provider-native IDs once durable webhook delivery is enabled.
- Subscribe narrowly by agent and event type.
- Failed delivery retry/dead-letter behavior is part of the durable async delivery roadmap.
