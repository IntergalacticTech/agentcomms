# FreeMail Agent Test Suite

**Base URL:** `https://api.victorymail.dev/v1`
**Auth header (all scenarios except Scenario 1):** `x-api-key: {API_KEY}`
**Content-Type for all POST/PUT:** `application/json`

Run scenarios **in order**. Record each as `PASS` or `FAIL` with a one-line reason. State you need to carry forward is called out at the end of each scenario under **State to save**.

If an early scenario fails, continue with subsequent scenarios when possible — a failure in Scenario 7 (Reply) should not stop you from running Scenario 12 (Quotas), for example. Scenarios 2-9 all depend on Scenario 1 (you need the API key) and Scenarios 4-9 depend on Scenario 3 (you need an inbox).

---

## Scenario 1: Sign Up and Get API Key

**Goal:** Create a fresh FreeMail account and capture an API key for the rest of the suite.

**Prerequisites:** None. This must run first.

**Why it matters:** Every other endpoint requires `x-api-key`. If signup is broken, nothing else in the suite can be tested.

**Steps:**

1. Generate a unique email address that embeds the current Unix timestamp so each run is independent, e.g. `e2e-agent-1712712345@victorymail.dev` (use the current epoch seconds — do not reuse a prior one).
2. Pick a strong password (at least 12 characters, mix of upper/lower/digit), e.g. `TestAgentPw!2026Xyz`.
3. POST to `/console/signup`:

   ```bash
   curl -sS -X POST https://api.victorymail.dev/v1/console/signup \
     -H 'Content-Type: application/json' \
     -d '{
       "email": "e2e-agent-1712712345@victorymail.dev",
       "password": "TestAgentPw!2026Xyz",
       "name": "E2E Agent"
     }'
   ```

**Expected response (HTTP 201):**

```json
{
  "message": "Account created. Check your email to verify.",
  "org_id": "01kp01dzcbd5mv7kfpbn96yzvs",
  "api_key": "am_live_iSgZkZ2GBcn2ZK7Z6wFG86OCLBM6hh50zuniiPqjltn"
}
```

**Success criteria:**
- HTTP status is `201`.
- Response JSON has non-empty `api_key` that starts with `am_live_`.
- Response JSON has non-empty `org_id`.
- Response JSON has a `message` field.

**Error hints:**
- `409 ALREADY_EXISTS` means your email collided — regenerate with a new timestamp and retry. Error responses look like `{"error": {"code": "ALREADY_EXISTS", "message": "..."}}`.
- `400` on password means the password is too weak — use a stronger one.

**State to save:**
- `API_KEY` = `api_key` from response. Use in `x-api-key` header for every subsequent scenario.
- `ORG_ID` = `org_id` from response.
- `TEST_EMAIL` = the signup email you generated (for the final report).

> Note: this response does NOT contain `user_id`, `tier`, or `created_at` — those live on `/organizations/me` (Scenario 2).

---

## Scenario 2: Organization Info

**Goal:** Confirm the account was created in the expected state (free tier, zero usage).

**Prerequisites:** Scenario 1 passed.

**Why it matters:** Validates that the API key works and that quotas/usage counters start clean.

**Steps:**

1. GET `/organizations/me`:

   ```bash
   curl -sS https://api.victorymail.dev/v1/organizations/me \
     -H 'x-api-key: {API_KEY}'
   ```

**Expected response (HTTP 200):**

```json
{
  "id": "01kp01dzcbd5mv7kfpbn96yzvs",
  "name": "Test",
  "email": "test@example.com",
  "tier": "free",
  "status": "active",
  "settings": {"default_domain": "victorymail.dev"},
  "quotas": {
    "max_pods": 3,
    "max_webhooks": 5,
    "max_domains": 1,
    "max_inboxes": 5,
    "max_messages_per_day": 1000,
    "max_api_keys": 5
  },
  "usage": {"inboxes": 0, "domains": 0, "pods": 0, "api_keys": 0},
  "created_at": "2026-04-12T05:08:03.595643+00:00",
  "updated_at": "2026-04-12T05:08:03.595643+00:00"
}
```

**Success criteria:**
- HTTP status `200`.
- `tier == "free"`.
- `usage.inboxes == 0`.
- `quotas.max_inboxes == 5`.
- `quotas.max_messages_per_day == 1000`.
- `id` matches the `org_id` saved in Scenario 1.

**Error hints:**
- `401` means your `x-api-key` header is missing or wrong — double-check you saved it from Scenario 1.

**State to save:** None (but note `quotas.max_inboxes` in case the tier default changes — Scenario 12 will rely on it).

> Note: the field is `id`, not `org_id`, on this endpoint. The `usage` block contains `inboxes`, `domains`, `pods`, `api_keys` only — there are no `messages_sent_today`/`messages_received_today` counters here.

---

## Scenario 3: Create an Inbox

**Goal:** Provision an email inbox under the new org.

**Prerequisites:** Scenario 1 passed.

**Why it matters:** Inboxes are the core resource. Everything mail-related (send, receive, reply, search, OTP) needs one.

**Steps:**

1. POST `/inboxes`:

   ```bash
   curl -sS -X POST https://api.victorymail.dev/v1/inboxes \
     -H 'x-api-key: {API_KEY}' \
     -H 'Content-Type: application/json' \
     -d '{"display_name": "Test Agent Inbox"}'
   ```

**Expected response (HTTP 201):**

```json
{
  "id": "01kp01dzcbd5mv7kfpbn96yzvs",
  "org_id": "01kp01dzcbd5mv7kfpbn96yzvs",
  "pod_id": "default",
  "email": "ethdn879g6hg@victorymail.dev",
  "display_name": "Test Agent Inbox",
  "status": "active",
  "settings": {},
  "forwarding": {},
  "created_at": "2026-04-12T05:08:03.595643+00:00",
  "updated_at": "2026-04-12T05:08:03.595643+00:00"
}
```

**Success criteria:**
- HTTP status `201`.
- `id` is non-empty.
- `email` ends with `@victorymail.dev`.
- `display_name == "Test Agent Inbox"`.
- `status == "active"`.

**State to save:**
- `INBOX_ID` = `id` (the field name is `id`, not `inbox_id`).
- `INBOX_EMAIL` = `email`.

---

## Scenario 4: Send Email to Self

**Goal:** Send an outbound message from the new inbox to itself, embedding an OTP in the body for Scenario 8.

**Prerequisites:** Scenario 3 passed.

**Why it matters:** Exercises the outbound pipeline and sets up the message corpus used by Scenarios 5-9.

**Steps:**

1. POST `/inboxes/{INBOX_ID}/messages`:

   ```bash
   curl -sS -X POST https://api.victorymail.dev/v1/inboxes/{INBOX_ID}/messages \
     -H 'x-api-key: {API_KEY}' \
     -H 'Content-Type: application/json' \
     -d '{
       "to":       [{"address": "{INBOX_EMAIL}"}],
       "subject":  "Test Email",
       "body_text": "Hello from the agent test suite.\n\nYour verification code is 123456\n\nThanks!",
       "body_html": "<p>Hello from the agent test suite.</p><p>Your verification code is <b>123456</b></p>"
     }'
   ```

   Replace `{INBOX_ID}` and `{INBOX_EMAIL}` with the values saved in Scenario 3.

**Expected response (HTTP 201):**

```json
{
  "id": "01kp01...",
  "thread_id": "01kp01...",
  "inbox_id": "01kp01...",
  "direction": "outbound",
  "from_addr": {"name": "Test Agent Inbox", "address": "ethdn879g6hg@victorymail.dev"},
  "to": [{"name": null, "address": "ethdn879g6hg@victorymail.dev"}],
  "cc": [],
  "bcc": [],
  "subject": "Test Email",
  "snippet": "Hello from the agent test suite...",
  "is_read": false,
  "is_starred": false,
  "labels": [],
  "category": null,
  "has_attachments": false,
  "attachment_count": 0,
  "body_text": "Hello from the agent test suite.\n\nYour verification code is 123456\n\nThanks!",
  "body_html": "<p>Hello from the agent test suite.</p><p>Your verification code is <b>123456</b></p>",
  "headers": {},
  "ses_message_id": null,
  "status": "queued",
  "received_at": "2026-04-12T...",
  "created_at": "2026-04-12T..."
}
```

**Success criteria:**
- HTTP status `201`.
- `id` is non-empty.
- `thread_id` is non-empty.
- `status` is one of `queued`, `sending`, `sent` (`queued` is most common immediately after POST).
- `direction == "outbound"`.
- `subject == "Test Email"`.

**Error hints:**
- `403 QUOTA_EXCEEDED` on the first message means your free-tier daily send quota is already consumed — unlikely on a fresh account, but retry with a fresh signup if so.

**State to save:**
- `MESSAGE_ID` = `id` (the field name is `id`, not `message_id`).
- `THREAD_ID` = `thread_id` (you will compare this in Scenario 7).

> Note: `from_addr` is always an object `{name, address}`, never a bare string. The same is true for entries in `to`, `cc`, and `bcc`.

---

## Scenario 5: List Messages

**Goal:** Confirm the message sent in Scenario 4 shows up in the inbox listing.

**Prerequisites:** Scenario 4 passed.

**Why it matters:** Validates the listing/index endpoint. If listing is broken, agents using FreeMail cannot poll for new mail.

**Steps:**

1. (Optional) Wait 1-2 seconds to give the outbound worker time to write the message.
2. GET `/inboxes/{INBOX_ID}/messages`:

   ```bash
   curl -sS https://api.victorymail.dev/v1/inboxes/{INBOX_ID}/messages \
     -H 'x-api-key: {API_KEY}'
   ```

**Expected response (HTTP 200):**

```json
{
  "data": [
    {
      "id": "01kp01...",
      "thread_id": "01kp01...",
      "inbox_id": "01kp01...",
      "subject": "Test Email",
      "from_addr": {"name": "Test Agent Inbox", "address": "ethdn879g6hg@victorymail.dev"},
      "to": [{"name": null, "address": "ethdn879g6hg@victorymail.dev"}],
      "direction": "outbound",
      "status": "queued",
      "snippet": "Hello from the agent test suite...",
      "created_at": "2026-04-12T..."
    }
  ],
  "next_page_token": null,
  "has_more": false
}
```

**Success criteria:**
- HTTP status `200`.
- `data` is an array with length `>= 1`.
- At least one entry has `subject == "Test Email"` (or `subject` contains `"Test Email"`).
- That entry's `id` matches `MESSAGE_ID` from Scenario 4 (soft check — if the API returns only the outbound copy, it still passes as long as a matching subject exists).

**Error hints:**
- Empty `data` usually means the message is still in-flight. Retry once after 2 seconds. If still empty, mark FAIL.

> Note: pagination uses `next_page_token` and `has_more`, not a `next_cursor` field. Each message's identifier field is `id` (not `message_id`), and `from_addr` is an object `{name, address}`.

---

## Scenario 6: Get Message Body

**Goal:** Retrieve the full message, including `body_text` and `body_html`.

**Prerequisites:** Scenario 4 passed.

**Why it matters:** Listing returns headers only; agents need the detail endpoint to read actual email content.

**Steps:**

1. GET `/inboxes/{INBOX_ID}/messages/{MESSAGE_ID}`:

   ```bash
   curl -sS https://api.victorymail.dev/v1/inboxes/{INBOX_ID}/messages/{MESSAGE_ID} \
     -H 'x-api-key: {API_KEY}'
   ```

**Expected response (HTTP 200):**

```json
{
  "id": "01kp01...",
  "thread_id": "01kp01...",
  "inbox_id": "01kp01...",
  "subject": "Test Email",
  "from_addr": {"name": "Test Agent Inbox", "address": "ethdn879g6hg@victorymail.dev"},
  "to": [{"name": null, "address": "ethdn879g6hg@victorymail.dev"}],
  "cc": [],
  "bcc": [],
  "body_text": "Hello from the agent test suite.\n\nYour verification code is 123456\n\nThanks!",
  "body_html": "<p>Hello from the agent test suite.</p><p>Your verification code is <b>123456</b></p>",
  "headers": {},
  "direction": "outbound",
  "status": "queued",
  "is_read": false,
  "is_starred": false,
  "labels": [],
  "has_attachments": false,
  "attachment_count": 0,
  "snippet": "Hello from the agent test suite...",
  "received_at": "2026-04-12T...",
  "created_at": "2026-04-12T..."
}
```

**Success criteria:**
- HTTP status `200`.
- `body_text` is present and contains the string `"verification code is 123456"`.
- `body_html` is present and non-empty.
- `id` matches the `MESSAGE_ID` you requested.
- `from_addr` is an object containing an `address` field (not a bare string).

---

## Scenario 7: Reply to Message

**Goal:** Reply to the Scenario 4 message and verify the reply lands in the same thread with a `Re:` subject prefix.

**Prerequisites:** Scenarios 4 and 6 passed.

**Why it matters:** Threading is a core feature. Agents running multi-turn email conversations rely on the reply endpoint preserving `thread_id` and munging the subject.

**Steps:**

1. POST `/inboxes/{INBOX_ID}/messages/{MESSAGE_ID}/reply`:

   ```bash
   curl -sS -X POST https://api.victorymail.dev/v1/inboxes/{INBOX_ID}/messages/{MESSAGE_ID}/reply \
     -H 'x-api-key: {API_KEY}' \
     -H 'Content-Type: application/json' \
     -d '{"body_text": "Reply test"}'
   ```

**Expected response (HTTP 201):**

```json
{
  "id": "01kp01...new-message-id...",
  "thread_id": "01kp01...same-as-original...",
  "inbox_id": "01kp01...",
  "direction": "outbound",
  "from_addr": {"name": "Test Agent Inbox", "address": "ethdn879g6hg@victorymail.dev"},
  "to": [{"name": null, "address": "ethdn879g6hg@victorymail.dev"}],
  "cc": [],
  "bcc": [],
  "subject": "Re: Test Email",
  "body_text": "Reply test",
  "body_html": null,
  "snippet": "Reply test",
  "is_read": false,
  "is_starred": false,
  "labels": [],
  "has_attachments": false,
  "attachment_count": 0,
  "headers": {},
  "ses_message_id": null,
  "status": "queued",
  "received_at": "2026-04-12T...",
  "created_at": "2026-04-12T..."
}
```

**Success criteria:**
- HTTP status `201`.
- `subject` starts with `"Re:"` (case-insensitive).
- `thread_id` equals `THREAD_ID` from Scenario 4.
- `direction == "outbound"`.
- `to` is a non-empty array; `to[0].address` matches the original message's `from_addr.address` (the reply handler reads `original.get("from_addr")` — which is an object `{name, address}` — and uses its `address` field to populate `to`).
- `id` is a NEW id, not the same as `MESSAGE_ID` from Scenario 4.

---

## Scenario 8: Extract OTP

**Goal:** Use the `extract-otp` convenience endpoint to pull the verification code out of the Scenario 4 message.

**Prerequisites:** Scenario 4 passed.

**Why it matters:** `extract-otp` combines wait-for-email + OTP parsing into a single call — it's the #1 reason agents use FreeMail instead of rolling their own IMAP client. This scenario proves it works end-to-end.

**Steps:**

1. POST `/inboxes/{INBOX_ID}/extract-otp`:

   ```bash
   curl -sS -X POST https://api.victorymail.dev/v1/inboxes/{INBOX_ID}/extract-otp \
     -H 'x-api-key: {API_KEY}' \
     -H 'Content-Type: application/json' \
     -d '{"timeout": 5, "subject_contains": "Test Email"}'
   ```

**Expected response (HTTP 200):**

```json
{
  "code": "123456",
  "message_id": "01kp01...",
  "from": "ethdn879g6hg@victorymail.dev",
  "subject": "Test Email"
}
```

**Success criteria:**
- HTTP status `200`.
- `code == "123456"` (exact match — this is the value placed in the body in Scenario 4).
- `message_id` is non-empty.
- `subject` is present (matches the message that was extracted from).

**Error hints:**
- If `code` is `null`, the matching message was found but no OTP could be parsed from its body. Confirm Scenario 4's `body_text` contained `"verification code is 123456"` verbatim.
- A `408 TIMEOUT` (with body `{"error": {"code": "TIMEOUT", "message": "..."}}`) means no matching message landed within the timeout window — unusual since Scenario 5 already saw it, but retry once with `"timeout": 15`.

---

## Scenario 9: Search Messages

**Goal:** Verify the cross-inbox search endpoint returns the test messages.

**Prerequisites:** Scenario 4 passed (and ideally Scenario 7 so there are two messages to match).

**Why it matters:** Search is how agents find messages across multiple inboxes without knowing IDs up front.

**Steps:**

1. POST `/search`:

   ```bash
   curl -sS -X POST https://api.victorymail.dev/v1/search \
     -H 'x-api-key: {API_KEY}' \
     -H 'Content-Type: application/json' \
     -d '{"query": "Test", "limit": 10}'
   ```

**Expected response (HTTP 200):**

```json
{
  "data": [
    {
      "id": "01kp01...",
      "thread_id": "01kp01...",
      "inbox_id": "01kp01...",
      "subject": "Test Email",
      "from_addr": {"name": "Test Agent Inbox", "address": "ethdn879g6hg@victorymail.dev"},
      "to": [{"name": null, "address": "ethdn879g6hg@victorymail.dev"}],
      "snippet": "Hello from the agent test suite...",
      "direction": "outbound",
      "status": "queued",
      "created_at": "2026-04-12T..."
    }
  ],
  "total": 2
}
```

**Success criteria:**
- HTTP status `200`.
- `data` is an array with length `>= 1`.
- At least one entry has `subject` containing `"Test"`.
- `total` is an integer `>= 1`.

> Note: search uses `total` (an integer count), not a `next_cursor` field.

---

## Scenario 10: Create and Verify Custom Domain

**Goal:** Add a custom sending domain, verify DNS records are generated, and fetch the BIND-format zone file.

**Prerequisites:** Scenario 1 passed.

**Why it matters:** Custom domains are the primary paid feature. Zone-file generation is what lets users copy-paste DNS records into Route53/Cloudflare.

**Steps:**

1. POST `/domains`:

   ```bash
   curl -sS -X POST https://api.victorymail.dev/v1/domains \
     -H 'x-api-key: {API_KEY}' \
     -H 'Content-Type: application/json' \
     -d '{"domain": "mail.agent-test.example"}'
   ```

**Expected response (HTTP 201):**

```json
{
  "id": "01kp01...",
  "domain": "mail.agent-test.example",
  "status": "pending",
  "mx_verified": false,
  "spf_verified": false,
  "dkim_verified": false,
  "dmarc_verified": false,
  "dns_records": {
    "mx": {
      "type": "MX",
      "name": "mail.agent-test.example",
      "value": "10 inbound-smtp.us-east-1.amazonaws.com"
    },
    "spf": {
      "type": "TXT",
      "name": "mail.agent-test.example",
      "value": "v=spf1 include:amazonses.com ~all"
    },
    "dkim": [
      {"type": "CNAME", "name": "s1._domainkey.mail.agent-test.example", "value": "s1.dkim.victorymail.dev"},
      {"type": "CNAME", "name": "s2._domainkey.mail.agent-test.example", "value": "s2.dkim.victorymail.dev"},
      {"type": "CNAME", "name": "s3._domainkey.mail.agent-test.example", "value": "s3.dkim.victorymail.dev"}
    ],
    "dmarc": {
      "type": "TXT",
      "name": "_dmarc.mail.agent-test.example",
      "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc@victorymail.dev"
    }
  },
  "created_at": "2026-04-12T..."
}
```

**Success criteria for the POST:**
- HTTP status `201`.
- `status == "pending"`.
- `mx_verified`, `spf_verified`, `dkim_verified`, `dmarc_verified` are all `false`.
- `dns_records` is an OBJECT (not an array) with keys `mx`, `spf`, `dkim`, `dmarc`.
- `dns_records.mx.type == "MX"` and its `value` contains `"inbound-smtp"`.
- `dns_records.spf.type == "TXT"` and its `value` starts with `"v=spf1"`.
- `dns_records.dkim` is an array of exactly **3 CNAME records**, each with a `name` containing `_domainkey`.
- `dns_records.dmarc.type == "TXT"`, `name` starts with `_dmarc.`, and `value` starts with `"v=DMARC1"`.

**State to save:**
- `DOMAIN_ID` = `id` (the field name is `id`, not `domain_id`).

2. GET `/domains/{DOMAIN_ID}/zone-file`:

   ```bash
   curl -sS https://api.victorymail.dev/v1/domains/{DOMAIN_ID}/zone-file \
     -H 'x-api-key: {API_KEY}'
   ```

**Expected response (HTTP 200):**
A plain-text BIND zone file with `Content-Type: text/dns` (NOT JSON). The body starts with a comment line like `; Zone file for mail.agent-test.example` and contains BIND-style records, e.g.:

```
; Zone file for mail.agent-test.example
mail.agent-test.example.          IN  MX    10 inbound-smtp.us-east-1.amazonaws.com.
mail.agent-test.example.          IN  TXT   "v=spf1 include:amazonses.com ~all"
s1._domainkey.mail.agent-test.example. IN CNAME s1.dkim.victorymail.dev.
s2._domainkey.mail.agent-test.example. IN CNAME s2.dkim.victorymail.dev.
s3._domainkey.mail.agent-test.example. IN CNAME s3.dkim.victorymail.dev.
_dmarc.mail.agent-test.example.   IN  TXT   "v=DMARC1; p=quarantine; ..."
```

**Success criteria for the zone-file GET:**
- HTTP status `200`.
- `Content-Type` response header contains `text/dns`.
- The body is plain text starting with `; Zone file for ` (do NOT attempt to parse it as JSON).
- The body contains the substring `"IN  MX"` or `"IN MX"`.
- The body contains `"_domainkey"`.
- The body contains `"_dmarc"`.

---

## Scenario 11: Create Webhook

**Goal:** Register a webhook subscription for inbound/outbound events and verify a signing secret is returned.

**Prerequisites:** Scenario 1 passed.

**Why it matters:** Webhooks let agents react to new mail without polling. The `whsec_` secret is needed to verify HMAC signatures on incoming callbacks.

**Steps:**

1. POST `/webhooks`:

   ```bash
   curl -sS -X POST https://api.victorymail.dev/v1/webhooks \
     -H 'x-api-key: {API_KEY}' \
     -H 'Content-Type: application/json' \
     -d '{
       "url": "https://httpbin.org/post",
       "events": ["message.received", "message.sent"]
     }'
   ```

**Expected response (HTTP 201):**

```json
{
  "id": "01kp01...",
  "url": "https://httpbin.org/post",
  "events": ["message.received", "message.sent"],
  "status": "active",
  "secret": "whsec_abcdef0123456789...",
  "filter": {},
  "delivery_stats": {"total": 0, "success": 0, "failed": 0},
  "created_at": "2026-04-12T..."
}
```

**Success criteria:**
- HTTP status `201`.
- `id` is non-empty (the field name is `id`, not `webhook_id`).
- `secret` starts with `"whsec_"`.
- `events` is a list containing both `"message.received"` and `"message.sent"`.
- `url == "https://httpbin.org/post"`.
- `status == "active"`.

---

## Scenario 12: Quota Enforcement

**Goal:** Prove that the free-tier inbox quota (5 inboxes) is enforced with a `403 QUOTA_EXCEEDED` on the 6th create attempt.

**Prerequisites:** Scenario 3 passed. This scenario assumes exactly **one** inbox already exists from Scenario 3 (the `Test Agent Inbox`). If you created additional inboxes during debugging, adjust the loop count accordingly.

**Why it matters:** Quota enforcement is a billing-critical code path. If it's broken, free users can provision unlimited resources.

**Steps:**

1. Create inboxes in a loop until the API rejects you. You should succeed exactly 4 more times (inboxes 2, 3, 4, 5), then fail on the 6th attempt (inbox 6):

   ```bash
   for i in 2 3 4 5 6; do
     echo "Attempt #$i:"
     curl -sS -w '\nHTTP %{http_code}\n' -X POST \
       https://api.victorymail.dev/v1/inboxes \
       -H 'x-api-key: {API_KEY}' \
       -H 'Content-Type: application/json' \
       -d "{\"display_name\": \"Quota Test $i\"}"
   done
   ```

   (An agent can do this as 5 separate HTTP calls rather than a shell loop.)

**Expected behavior:**
- Attempts **#2, #3, #4, #5** return HTTP `201` with a new inbox `id` each time (filling the free-tier cap of 5).
- Attempt **#6** returns HTTP `403` with a body like:

  ```json
  {
    "error": {
      "code": "QUOTA_EXCEEDED",
      "message": "You have reached your inboxes limit (5). Upgrade to increase your quota."
    }
  }
  ```

**Success criteria:**
- The first four additional creates (attempts #2-#5) all succeed with HTTP `201`.
- The sixth attempt returns HTTP `403`.
- The `403` body's `error.code` equals `"QUOTA_EXCEEDED"`.
- The `403` body's `error.message` mentions `"inboxes"` and contains the limit `"5"`.

**Error hints:**
- If attempt #6 returns `201`, the quota check is broken — mark FAIL and note the actual count of inboxes in the report.
- If an earlier attempt fails with `403`, it means the account started with more than 1 inbox — re-check Scenario 3 and make sure you didn't run the suite twice against the same key.
- A `429` (rate limit) is **not** the same as `403 QUOTA_EXCEEDED`. If you see `429`, back off a second and retry the same attempt — do not count it as a quota rejection.

---

## Final Reporting

After Scenario 12, print the summary report in the exact format shown in `README.md`. Example:

```
FreeMail Agent Test Suite Results
==================================
Test Account: e2e-agent-1712712345@victorymail.dev
API Key: am_live_abcdef1234567890abc... (first 20 chars)
Run started:  2026-04-10T14:22:11Z
Run finished: 2026-04-10T14:23:47Z

Scenario  1: Sign Up and Get API Key ... PASS
Scenario  2: Organization Info ......... PASS
Scenario  3: Create an Inbox ........... PASS
Scenario  4: Send Email to Self ........ PASS
Scenario  5: List Messages ............. PASS
Scenario  6: Get Message Body .......... PASS
Scenario  7: Reply to Message .......... PASS
Scenario  8: Extract OTP ............... PASS
Scenario  9: Search Messages ........... PASS
Scenario 10: Custom Domain ............. PASS
Scenario 11: Create Webhook ............ PASS
Scenario 12: Quota Enforcement ......... PASS

Result: 12/12 PASSED
```

If any scenario failed, append a `Failures` section with one bullet per failure, including the scenario number, what you expected, and what you observed (including HTTP status and response body excerpt).
