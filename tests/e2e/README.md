# FreeMail Live API E2E Tests

`test_live_api.py` is a standalone end-to-end test suite that exercises every
public endpoint of the live FreeMail API against a fresh account created at
run time. It is a plain Python script — not a pytest module — and has **zero
third-party dependencies** (it uses only `urllib.request` from the standard
library).

## What it does

1. Creates a brand new test account via `POST /console/signup` using a random
   `e2e-test-<timestamp>-<rand>@victorymail.dev` email and a strong password
   matching the Cognito policy (8+ chars, upper, lower, digit).
2. Uses the returned API key to run 45 sequential tests covering every
   endpoint — organizations, api-keys, pods, inboxes, messages, threads,
   drafts, domains, webhooks, mailing lists, search, metrics, billing, AI
   (tier-guard), wait-for-email, extract-OTP, and quota enforcement.
3. Prints a colored `PASS`/`FAIL` line for each test with elapsed time and
   tracks a pass/fail tally.
4. Attempts a best-effort cleanup of every resource it created — extra
   inboxes, pod, list, webhook, domain, and API key — at the end of the run.
5. Exits with code `0` if every test passed, or `1` if any failed.

## Resources created

Each run spins up a fresh organization plus:

- 1 organization + default API key (from signup)
- 1 extra API key
- 1 pod
- 2 primary inboxes (one plain, one attached to the pod)
- A handful of extra inboxes used to exercise the quota limit (created until
  the free-tier ceiling of 5 is hit, then cleaned up)
- 1 outbound message (replied to + forwarded)
- 1 OTP test message
- 1 draft (plus a disposable draft that gets deleted immediately)
- 1 test domain
- 1 webhook
- 1 mailing list with two members

The cleanup phase deletes everything it can. The Cognito user and
organization row itself are not deleted (FreeMail has no "delete org"
endpoint), but each run uses a unique email so they do not collide.

## Running it

From the repository root:

```bash
python3 tests/e2e/test_live_api.py
```

That's it. Python 3.10 or newer is required.

### Pointing at a different environment

Set `FREEMAIL_API_URL` to override the default base URL. The script appends
the trailing slash if needed.

```bash
# Default — production
python3 tests/e2e/test_live_api.py

# Staging / dev stack
FREEMAIL_API_URL=https://api-dev.victorymail.dev/v1/ \
    python3 tests/e2e/test_live_api.py

# Local SAM / LocalStack
FREEMAIL_API_URL=http://localhost:3000/v1/ \
    python3 tests/e2e/test_live_api.py
```

## Output

Example successful run:

```
FreeMail Live API E2E Test Suite
================================
API: https://api.victorymail.dev/v1/

[1/45] test_signup ................................. PASS (0.45s)
[2/45] test_get_organization ....................... PASS (0.12s)
...
[45/45] test_delete_api_key ........................ PASS (0.08s)

================================
Results: 45 passed, 0 failed
Duration: 32.4s
Cleanup: removed 7 resources
```

On failure, each failed test's error message is repeated at the bottom so
you can see everything at a glance even if the terminal scrolled.
