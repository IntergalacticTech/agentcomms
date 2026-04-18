# FreeMail Agent Instructions

These instructions are for AI agents that need to use email. No human
intervention required. All operations use the REST API at
`https://api.victorymail.dev/v1`.

## Quick Start (3 steps)

### Step 1: Get an API key

```bash
curl -X POST https://api.victorymail.dev/v1/console/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "YOUR_EMAIL@example.com",
    "password": "YOUR_SECURE_PASSWORD",
    "name": "Your Agent Name"
  }'
```

Password requirements: 8+ characters, uppercase, lowercase, number.

Response:
```json
{
  "message": "Account created. Check your email to verify.",
  "org_id": "01ABC...",
  "api_key": "am_live_xxxxx..."
}
```

Save `api_key`. It works immediately for all API calls. You do not need to
verify your email to use the API.

### Step 2: Create an inbox

```bash
curl -X POST https://api.victorymail.dev/v1/inboxes \
  -H "x-api-key: am_live_xxxxx..." \
  -H "Content-Type: application/json" \
  -d '{"display_name": "My Agent"}'
```

Response:
```json
{
  "id": "01DEF...",
  "email": "abc123@victorymail.dev",
  ...
}
```

Save `id` (inbox ID) and `email` (your new email address).

### Step 3: Use email

**Send:**
```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/messages \
  -H "x-api-key: am_live_xxxxx..." \
  -H "Content-Type: application/json" \
  -d '{
    "to": [{"address": "recipient@example.com"}],
    "subject": "Hello",
    "body_text": "Email body here"
  }'
```

**Wait for incoming email:**
```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/wait \
  -H "x-api-key: am_live_xxxxx..." \
  -H "Content-Type: application/json" \
  -d '{"timeout": 25}'
```

**Extract OTP from incoming email:**
```bash
curl -X POST https://api.victorymail.dev/v1/inboxes/INBOX_ID/extract-otp \
  -H "x-api-key: am_live_xxxxx..." \
  -H "Content-Type: application/json" \
  -d '{"timeout": 25, "sender": "noreply@service.com"}'
```

Returns `{"code": "482917", ...}`.

## Complete Endpoint Reference

All endpoints require `x-api-key` header except signup/login.

### Account
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /console/signup | Create account, returns API key |
| GET | /organizations/me | Get account info and quotas |
| POST | /api-keys | Create additional API key |
| GET | /api-keys | List API keys |

### Inboxes
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /inboxes | Create inbox (auto-generates email) |
| GET | /inboxes | List all inboxes |
| GET | /inboxes/{id} | Get inbox details |
| PATCH | /inboxes/{id} | Update inbox |
| DELETE | /inboxes/{id} | Delete inbox |

### Messages
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /inboxes/{id}/messages | Send email |
| GET | /inboxes/{id}/messages | List messages |
| GET | /inboxes/{id}/messages/{mid} | Get message with full body |
| PATCH | /inboxes/{id}/messages/{mid} | Update (mark read, star, etc.) |
| POST | /inboxes/{id}/messages/{mid}/reply | Reply to message |
| POST | /inboxes/{id}/messages/{mid}/forward | Forward message |

### Wait & OTP
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /inboxes/{id}/wait | Long-poll for matching message (up to 25s) |
| POST | /inboxes/{id}/extract-otp | Wait + extract verification code |

### Other
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /inboxes/{id}/threads | List threads |
| POST | /inboxes/{id}/drafts | Create draft |
| POST | /domains | Add custom domain |
| POST | /webhooks | Set up webhook for real-time events |
| POST | /search | Search messages by text |

## Wait/OTP Filter Options

```json
{
  "timeout": 25,
  "filter": {
    "from": "noreply@service.com",
    "subject_contains": "verification",
    "after": "2026-04-11T00:00:00Z",
    "is_read": false
  }
}
```

For extract-otp, use `sender` and `subject_contains` at the top level:
```json
{
  "timeout": 25,
  "sender": "noreply@service.com",
  "subject_contains": "verify"
}
```

## Error Handling

All errors return:
```json
{"error": {"code": "ERROR_CODE", "message": "Human-readable message"}}
```

Common codes: `BAD_REQUEST` (400), `UNAUTHORIZED` (401), `FORBIDDEN` (403),
`NOT_FOUND` (404), `VALIDATION_ERROR` (422), `QUOTA_EXCEEDED` (403),
`RATE_LIMITED` (429), `TIMEOUT` (408).

## Free Tier Limits

- 1 inbox
- 50 messages per day
- 0 custom domains (use a platform domain instead)
- 1 API key
- Pick from `victorymail.dev`, `karmascale.net`, or `karmascale.org`

New accounts also get a 14-day Pro trial at signup.

## Example: Sign up for a service and verify

```python
import requests

API = "https://api.victorymail.dev/v1"
KEY = "am_live_your_key"

# 1. Create inbox
inbox = requests.post(f"{API}/inboxes",
    headers={"x-api-key": KEY},
    json={"display_name": "Signup Agent"}).json()

inbox_email = inbox["email"]  # e.g. abc123@victorymail.dev

# 2. Use this email to sign up on the target service
# ... your signup logic here, using inbox_email as the email ...

# 3. Wait for verification email and extract OTP
otp = requests.post(f"{API}/inboxes/{inbox['id']}/extract-otp",
    headers={"x-api-key": KEY},
    json={"timeout": 25, "sender": "noreply@targetservice.com"}).json()

print(f"Verification code: {otp['code']}")

# 4. Submit the OTP to the target service
# ... your verification logic here ...
```
