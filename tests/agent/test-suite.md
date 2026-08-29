# AgentComms Agent Test Suite

**Base URL:** `https://api.agentcomms.dev/v1`
**Auth header:** `Authorization: Bearer {API_KEY}` or `x-api-key: {API_KEY}`
**Content-Type for POST/PUT/PATCH:** `application/json`

This suite is written for an AI agent or human operator to execute with `curl`,
`fetch`, `requests`, or an equivalent HTTP tool. Run scenarios in order and save
the state called out at the end of each scenario.

## Scenario 1: Bootstrap Credentials

Use an existing org-scoped API key from your hosted or self-hosted AgentComms
deployment.

Success criteria:
- API key is non-empty.
- Base URL ends in `/v1`.

State to save:
- `API_KEY`
- `BASE_URL`

## Scenario 2: Create Agent with Email

```bash
curl -sS -X POST "$BASE_URL/agents" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Agent Test Bot","provision":{"email":{}}}'
```

Success criteria:
- HTTP status is `201`.
- Response has `agent_id`.
- Response includes an email channel in `channels`.

State to save:
- `AGENT_ID`
- `EMAIL_CHANNEL_ID`
- `AGENT_EMAIL`

## Scenario 3: List Messages

```bash
curl -sS "$BASE_URL/agents/$AGENT_ID/messages?channels=email&limit=10" \
  -H "x-api-key: $API_KEY"
```

Success criteria:
- HTTP status is `200`.
- Response has `messages` as an array.

## Scenario 4: Send Email

```bash
curl -sS -X POST "$BASE_URL/agents/$AGENT_ID/messages" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"to\": [{\"address\": \"$AGENT_EMAIL\"}],
    \"channel\": \"email\",
    \"subject\": \"AgentComms test\",
    \"body_text\": \"Hello from the agent test suite. Code: 123456\"
  }"
```

Success criteria:
- HTTP status is `201`.
- Response has `message_id`.
- `status` is `sent` or `failed`; record failures but continue.

State to save:
- `OUTBOUND_MESSAGE_ID`

## Scenario 5: Wait for Inbound

If the deployment loops mail back to the same agent address, wait for the inbound
copy. Otherwise send a manual email to `AGENT_EMAIL` with body `Code: 123456`.

```bash
curl -sS -X POST "$BASE_URL/agents/$AGENT_ID/wait" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"channels":["email"],"subject_contains":"AgentComms test","timeout_sec":30}'
```

Success criteria:
- HTTP status is `200`.
- Response has `message_id`.
- Response `channel` is `email`.

State to save:
- `INBOUND_MESSAGE_ID`

## Scenario 6: Read, Reply, and Mark Read

```bash
curl -sS "$BASE_URL/agents/$AGENT_ID/messages/$INBOUND_MESSAGE_ID" \
  -H "x-api-key: $API_KEY"

curl -sS -X POST "$BASE_URL/agents/$AGENT_ID/messages/$INBOUND_MESSAGE_ID/reply" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"body":"Received by AgentComms test suite."}'

curl -sS -X POST "$BASE_URL/agents/$AGENT_ID/messages/$INBOUND_MESSAGE_ID/read" \
  -H "x-api-key: $API_KEY"
```

Success criteria:
- Read returns `200`.
- Reply returns `201`.
- Mark-read returns `204`.

## Scenario 7: Extract OTP

```bash
curl -sS -X POST "$BASE_URL/agents/$AGENT_ID/extract-otp" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"channels":["email"],"max_age_sec":600}'
```

Success criteria:
- HTTP status is `200`.
- Response `code` is `123456` when the message from Scenario 5 was present.

## Scenario 8: AI Features

```bash
curl -sS -X POST "$BASE_URL/agents/$AGENT_ID/ai/summarize" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Alice shipped login. Bob is fixing billing. No blockers.","length":"short"}'
```

Success criteria:
- HTTP status is `200`.
- Response has `summary`.

## Scenario 9: Webhooks

```bash
curl -sS -X POST "$BASE_URL/agents/$AGENT_ID/webhooks" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/agentcomms-hook","events":["message.received","message.sent"]}'
```

Success criteria:
- HTTP status is `201`.
- Response has `webhook_id`.
- Response returns the signing secret only once.

State to save:
- `WEBHOOK_ID`

## Scenario 10: Scoped API Key

```bash
curl -sS -X POST "$BASE_URL/api-keys" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"agent-test-key\",
    \"scope\": \"agent\",
    \"agent_id\": \"$AGENT_ID\"
  }"
```

Success criteria:
- HTTP status is `201`.
- Response has `key_id`, `key_prefix`, and plaintext `key`.
- Response does not include `key_hash`.

State to save:
- `SCOPED_KEY_ID`
- `SCOPED_API_KEY`

## Scenario 11: Scoped Key Isolation

```bash
curl -sS "$BASE_URL/agents/$AGENT_ID/messages?limit=1" \
  -H "Authorization: Bearer $SCOPED_API_KEY"

curl -sS "$BASE_URL/api-keys" \
  -H "Authorization: Bearer $SCOPED_API_KEY"
```

Success criteria:
- Agent message read succeeds with `200`.
- API-key administration fails with `403`.

## Scenario 12: Cleanup

```bash
curl -sS -X DELETE "$BASE_URL/api-keys/$SCOPED_KEY_ID" \
  -H "x-api-key: $API_KEY"

curl -sS -X DELETE "$BASE_URL/agents/$AGENT_ID/webhooks/$WEBHOOK_ID" \
  -H "x-api-key: $API_KEY"

curl -sS -X DELETE "$BASE_URL/agents/$AGENT_ID" \
  -H "x-api-key: $API_KEY"
```

Success criteria:
- API key delete returns `204`.
- Webhook delete returns `204`.
- Agent delete returns `204`.

## Report Format

```
AgentComms Agent Test Suite Results
===================================
Base URL: https://api.agentcomms.dev/v1
Run started:  2026-08-29T18:00:00Z
Run finished: 2026-08-29T18:03:00Z

Scenario  1: Bootstrap Credentials ..... PASS
Scenario  2: Create Agent with Email .... PASS
Scenario  3: List Messages .............. PASS
Scenario  4: Send Email ................. PASS
Scenario  5: Wait for Inbound ........... PASS
Scenario  6: Read, Reply, Mark Read ..... PASS
Scenario  7: Extract OTP ................ PASS
Scenario  8: AI Features ................ PASS
Scenario  9: Webhooks ................... PASS
Scenario 10: Scoped API Key ............. PASS
Scenario 11: Scoped Key Isolation ....... PASS
Scenario 12: Cleanup .................... PASS

Result: 12/12 PASSED
```
