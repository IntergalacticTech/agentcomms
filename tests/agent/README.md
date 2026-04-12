# FreeMail Agent Test Suite

## Purpose

This test suite validates the FreeMail API end-to-end by exercising the most important flows an AI agent would use: signup, inbox creation, sending and receiving mail, OTP extraction, search, custom domains, webhooks, and quota enforcement.

Unlike the Python `pytest` suite under `tests/`, this suite is written to be **executed by another AI agent** (Claude, GPT-4, OpenClaw, etc.) using natural-language reasoning and HTTP calls. There is no test runner — the agent reads `test-suite.md`, performs each scenario in order, and reports the results.

## What the Agent Needs

To execute this test suite, the agent must have:

1. **An HTTP tool** — ability to run `curl`, `fetch`, `requests`, or an equivalent (any tool that can issue `GET`/`POST`/`PUT`/`DELETE` with JSON bodies and custom headers).
2. **Scratch memory** — ability to store values between scenarios (API key, inbox ID, message ID, etc.). In-context state is fine; no persistent storage required.
3. **Internet access** — the API lives at `https://api.victorymail.dev/v1/`.
4. **A clock** — to generate a unique timestamp for the signup email.

No special credentials are needed. Scenario 1 creates a fresh account; every subsequent scenario uses the API key returned by that signup.

## How to Execute

1. Open `test-suite.md`.
2. Run each scenario **in order** (scenarios 2-12 depend on state produced by earlier scenarios).
3. For each scenario:
   - Read the **Goal** and **Steps**.
   - Execute the HTTP calls.
   - Verify the response matches the **Success criteria**.
   - Record `PASS` or `FAIL` with a one-line reason.
4. If a scenario fails, **continue with the next one** where possible (some scenarios are independent). Do not stop the whole run on the first failure.
5. At the end, print a report in the format shown below.

## Expected Output Format

After running all 12 scenarios, produce a report like this:

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

For any `FAIL`, include a short reason on the same line or in a "Failures" section below, e.g.:

```
Scenario  8: Extract OTP ............... FAIL (expected code "123456", got "" — timed out)
```

## Where to Report Results

- **Primary:** print the report to stdout / the conversation transcript so the operator can read it.
- **If a results file is requested:** write it to `tests/agent/last-run.txt` relative to the repository root.
- **On CI:** return a non-zero exit status (or the equivalent agent signal) if any scenario fails.

## Conventions Used in `test-suite.md`

- `{API_KEY}`, `{INBOX_ID}`, `{MESSAGE_ID}`, etc. are placeholders — substitute the real values you captured from earlier scenarios.
- All requests (except `POST /console/signup`) require the header `x-api-key: {API_KEY}`.
- All responses are JSON. Unless noted, a successful response has HTTP status `200` or `201`.
- Timestamps in responses are ISO-8601 UTC.
- The agent **should not hardcode any values** that are created during the run — always read them from the previous scenario's response.
