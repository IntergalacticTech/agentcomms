#!/usr/bin/env python3
"""End-to-end test suite for the live FreeMail API.

Creates a fresh test account from scratch and exercises every public endpoint
against the live production API, printing colored PASS/FAIL output and exiting
with non-zero if any test fails.

Usage:
    python3 tests/e2e/test_live_api.py

Environment variables:
    FREEMAIL_API_URL  Override the base URL (default: https://api.victorymail.dev/v1/)

This script uses only the Python standard library — no third-party deps.
"""

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

# ─── Config ─────────────────────────────────────────────────────────────────

API_URL = os.environ.get("FREEMAIL_API_URL", "https://api.victorymail.dev/v1/").rstrip("/") + "/"
USER_AGENT = "FreeMail-E2E-Test/1.0"
HTTP_TIMEOUT = 30

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"

# ─── Shared state ───────────────────────────────────────────────────────────

state: dict = {
    "api_key": None,                # primary api key from signup
    "org_id": None,
    "extra_key_id": None,           # secondary key created via POST /api-keys
    "pod_id": None,
    "inbox_id": None,               # primary test inbox
    "inbox_email": None,
    "inbox_pod_id": None,           # inbox that lives in the pod
    "extra_inbox_ids": [],          # inboxes created for quota test
    "message_id": None,
    "thread_id": None,
    "draft_id": None,
    "disposable_draft_id": None,    # draft for delete test
    "domain_id": None,
    "webhook_id": None,
    "list_id": None,
    "otp_message_id": None,
}

results: list = []  # (name, status, duration, error)


# ─── Helpers ────────────────────────────────────────────────────────────────


def api_request(method: str, path: str, api_key: str | None = None,
                body: dict | None = None) -> tuple[int, dict | str]:
    """Make an HTTP request and return (status_code, parsed_body).

    Parses JSON on success. Returns the raw text if the body is not JSON.
    Never raises on HTTP errors (4xx/5xx) — always returns the status code
    and decoded body.
    """
    if path.startswith("/"):
        path = path[1:]
    url = API_URL + path

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if api_key:
        headers["x-api-key"] = api_key

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            status = resp.getcode()
            raw = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read() if hasattr(e, "read") else b""
    except urllib.error.URLError as e:
        return 0, {"error": {"code": "NETWORK", "message": str(e)}}

    if not raw:
        return status, {}
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return status, raw.decode("utf-8", errors="replace")


def assert_equal(actual, expected, msg: str = ""):
    if actual != expected:
        raise AssertionError(
            f"{msg}: expected {expected!r}, got {actual!r}" if msg
            else f"expected {expected!r}, got {actual!r}"
        )


def assert_in(key, container, msg: str = ""):
    if key not in container:
        raise AssertionError(
            f"{msg}: expected {key!r} in {container!r}" if msg
            else f"expected {key!r} in {container!r}"
        )


def assert_status(actual: int, expected: int, body):
    if actual != expected:
        raise AssertionError(
            f"expected HTTP {expected}, got HTTP {actual}: {body!r}"
        )


def _generate_password() -> str:
    """Generate a strong password matching the Cognito policy."""
    return f"Test{secrets.token_hex(8)}Pass1!"


def test(name: str, fn, index: int, total: int) -> bool:
    """Run a test function, print PASS/FAIL, record result."""
    label = f"[{index}/{total}] {name}"
    # Pad test name to 50 chars with dots
    padding = "." * max(1, 52 - len(name))
    prefix = f"[{index}/{total}] {name} {padding} "
    sys.stdout.write(prefix)
    sys.stdout.flush()

    start = time.time()
    try:
        fn()
        dur = time.time() - start
        sys.stdout.write(f"{GREEN}PASS{RESET} ({dur:.2f}s)\n")
        sys.stdout.flush()
        results.append((name, "PASS", dur, None))
        return True
    except Exception as e:
        dur = time.time() - start
        sys.stdout.write(f"{RED}FAIL{RESET} ({dur:.2f}s)\n")
        sys.stdout.write(f"    {RED}{type(e).__name__}: {e}{RESET}\n")
        sys.stdout.flush()
        results.append((name, "FAIL", dur, str(e)))
        return False


# ─── Test functions ─────────────────────────────────────────────────────────


def test_signup():
    ts = int(time.time())
    rand = secrets.token_hex(3)
    email = f"e2e-test-{ts}-{rand}@victorymail.dev"
    password = _generate_password()
    state["email"] = email
    state["password"] = password

    status, resp = api_request("POST", "/console/signup",
                               body={"email": email, "password": password,
                                     "name": "E2E Test"})
    assert_status(status, 201, resp)
    assert_in("api_key", resp)
    assert_in("org_id", resp)
    assert resp["api_key"].startswith("am_live_"), f"bad api_key: {resp['api_key']}"
    state["api_key"] = resp["api_key"]
    state["org_id"] = resp["org_id"]


def test_get_organization():
    status, resp = api_request("GET", "/organizations/me", state["api_key"])
    assert_status(status, 200, resp)
    assert_equal(resp.get("tier"), "free", "tier")
    assert_in("usage", resp)
    assert_in("quotas", resp)
    assert_equal(resp["quotas"].get("max_inboxes"), 5, "quotas.max_inboxes")


def test_create_api_key():
    status, resp = api_request("POST", "/api-keys", state["api_key"],
                               body={"name": "E2E Extra Key", "scope": "org"})
    assert_status(status, 201, resp)
    assert_in("key", resp)
    assert resp["key"].startswith("am_live_"), f"bad key: {resp['key']}"
    assert_in("id", resp)
    state["extra_key_id"] = resp["id"]


def test_list_api_keys():
    status, resp = api_request("GET", "/api-keys", state["api_key"])
    assert_status(status, 200, resp)
    assert_in("data", resp)
    ids = [k.get("id") for k in resp["data"]]
    assert state["extra_key_id"] in ids, f"extra key missing from list: {ids}"
    # Ensure plaintext not returned
    for k in resp["data"]:
        assert "key" not in k, "list should not return plaintext key"


def test_create_pod():
    status, resp = api_request("POST", "/pods", state["api_key"],
                               body={"name": "E2E Pod",
                                     "description": "E2E test pod"})
    assert_status(status, 201, resp)
    assert_in("id", resp)
    assert_equal(resp.get("name"), "E2E Pod", "pod name")
    state["pod_id"] = resp["id"]


def test_list_pods():
    status, resp = api_request("GET", "/pods", state["api_key"])
    assert_status(status, 200, resp)
    assert_in("data", resp)
    ids = [p.get("id") for p in resp["data"]]
    assert state["pod_id"] in ids, f"pod missing from list: {ids}"


def test_get_pod():
    status, resp = api_request("GET", f"/pods/{state['pod_id']}", state["api_key"])
    assert_status(status, 200, resp)
    assert_equal(resp.get("id"), state["pod_id"], "pod id")


def test_create_inbox_auto_email():
    status, resp = api_request("POST", "/inboxes", state["api_key"],
                               body={"display_name": "E2E Primary Inbox"})
    assert_status(status, 201, resp)
    assert_in("id", resp)
    assert_in("email", resp)
    assert resp["email"].endswith("@victorymail.dev"), \
        f"bad auto-generated email: {resp['email']}"
    state["inbox_id"] = resp["id"]
    state["inbox_email"] = resp["email"]


def test_create_inbox_with_pod():
    status, resp = api_request("POST", "/inboxes", state["api_key"],
                               body={"display_name": "E2E Pod Inbox",
                                     "pod_id": state["pod_id"]})
    assert_status(status, 201, resp)
    assert_equal(resp.get("pod_id"), state["pod_id"], "pod_id")
    state["inbox_pod_id"] = resp["id"]


def test_list_inboxes():
    status, resp = api_request("GET", "/inboxes", state["api_key"])
    assert_status(status, 200, resp)
    assert_in("data", resp)
    ids = {i.get("id") for i in resp["data"]}
    assert state["inbox_id"] in ids, "primary inbox missing from list"
    assert state["inbox_pod_id"] in ids, "pod inbox missing from list"


def test_get_inbox():
    status, resp = api_request("GET", f"/inboxes/{state['inbox_id']}",
                               state["api_key"])
    assert_status(status, 200, resp)
    assert_equal(resp.get("id"), state["inbox_id"], "id")


def test_update_inbox():
    status, resp = api_request("PATCH", f"/inboxes/{state['inbox_id']}",
                               state["api_key"],
                               body={"display_name": "E2E Updated Name"})
    assert_status(status, 200, resp)
    assert_equal(resp.get("display_name"), "E2E Updated Name", "display_name")


def test_send_message():
    status, resp = api_request(
        "POST", f"/inboxes/{state['inbox_id']}/messages", state["api_key"],
        body={
            "to": [state["inbox_email"]],
            "subject": "E2E Test Message",
            "body_text": "Hello from the E2E test suite!",
            "body_html": "<p>Hello from the E2E test suite!</p>",
        },
    )
    assert_status(status, 201, resp)
    assert_in("id", resp)
    assert_equal(resp.get("status"), "queued", "status")
    state["message_id"] = resp["id"]
    state["thread_id"] = resp.get("thread_id")


def test_list_messages():
    status, resp = api_request(
        "GET", f"/inboxes/{state['inbox_id']}/messages", state["api_key"]
    )
    assert_status(status, 200, resp)
    assert_in("data", resp)
    ids = {m.get("id") for m in resp["data"]}
    assert state["message_id"] in ids, "sent message missing from list"


def test_get_message():
    status, resp = api_request(
        "GET",
        f"/inboxes/{state['inbox_id']}/messages/{state['message_id']}",
        state["api_key"],
    )
    assert_status(status, 200, resp)
    assert_in("body_text", resp)
    assert_in("body_html", resp)
    assert resp.get("body_text"), "body_text should be non-empty"


def test_update_message_starred():
    status, resp = api_request(
        "PATCH",
        f"/inboxes/{state['inbox_id']}/messages/{state['message_id']}",
        state["api_key"],
        body={"is_starred": True, "labels": ["test"]},
    )
    assert_status(status, 200, resp)
    assert_equal(resp.get("is_starred"), True, "is_starred")
    assert_equal(resp.get("labels"), ["test"], "labels")


def test_reply_to_message():
    status, resp = api_request(
        "POST",
        f"/inboxes/{state['inbox_id']}/messages/{state['message_id']}/reply",
        state["api_key"],
        body={
            "body_text": "This is a reply",
            "body_html": "<p>This is a reply</p>",
        },
    )
    assert_status(status, 201, resp)
    assert_equal(resp.get("thread_id"), state["thread_id"], "thread_id")
    subject = resp.get("subject", "")
    assert subject.startswith("Re:"), f"subject should start with Re: — got {subject!r}"


def test_forward_message():
    status, resp = api_request(
        "POST",
        f"/inboxes/{state['inbox_id']}/messages/{state['message_id']}/forward",
        state["api_key"],
        body={
            "to": ["forwarded@example.com"],
            "body_text": "Forwarding this message",
        },
    )
    assert_status(status, 201, resp)
    subject = resp.get("subject", "")
    assert subject.startswith("Fwd:"), f"subject should start with Fwd: — got {subject!r}"


def test_list_threads():
    status, resp = api_request(
        "GET", f"/inboxes/{state['inbox_id']}/threads", state["api_key"]
    )
    assert_status(status, 200, resp)
    assert_in("data", resp)
    ids = {t.get("id") for t in resp["data"]}
    assert state["thread_id"] in ids, "thread missing from list"


def test_get_thread_with_messages():
    status, resp = api_request(
        "GET",
        f"/inboxes/{state['inbox_id']}/threads/{state['thread_id']}",
        state["api_key"],
    )
    assert_status(status, 200, resp)
    assert_in("messages", resp)
    assert isinstance(resp["messages"], list), "messages should be a list"
    assert len(resp["messages"]) >= 1, "thread should contain at least one message"


def test_create_draft():
    status, resp = api_request(
        "POST", f"/inboxes/{state['inbox_id']}/drafts", state["api_key"],
        body={
            "to": ["draft@example.com"],
            "subject": "E2E Draft",
            "body_text": "Draft body",
        },
    )
    assert_status(status, 201, resp)
    assert_in("id", resp)
    state["draft_id"] = resp["id"]


def test_update_draft():
    status, resp = api_request(
        "PATCH",
        f"/inboxes/{state['inbox_id']}/drafts/{state['draft_id']}",
        state["api_key"],
        body={"body_text": "Updated draft body"},
    )
    assert_status(status, 200, resp)
    assert_equal(resp.get("body_text"), "Updated draft body", "body_text")


def test_list_drafts():
    status, resp = api_request(
        "GET", f"/inboxes/{state['inbox_id']}/drafts", state["api_key"]
    )
    assert_status(status, 200, resp)
    assert_in("data", resp)
    ids = {d.get("id") for d in resp["data"]}
    assert state["draft_id"] in ids, "draft missing from list"


def test_delete_draft():
    # Create a dedicated disposable draft then delete it.
    status, resp = api_request(
        "POST", f"/inboxes/{state['inbox_id']}/drafts", state["api_key"],
        body={"to": ["temp@example.com"], "subject": "Temp",
              "body_text": "temp"},
    )
    assert_status(status, 201, resp)
    disposable = resp["id"]
    state["disposable_draft_id"] = disposable

    status, resp = api_request(
        "DELETE",
        f"/inboxes/{state['inbox_id']}/drafts/{disposable}",
        state["api_key"],
    )
    assert_status(status, 204, resp)


def test_create_domain():
    status, resp = api_request(
        "POST", "/domains", state["api_key"],
        body={"domain": f"mail.e2e-test-{int(time.time())}.example"},
    )
    assert_status(status, 201, resp)
    assert_in("id", resp)
    assert_in("dns_records", resp)
    dns = resp["dns_records"]
    assert_in("mx", dns)
    assert_in("spf", dns)
    assert_in("dkim", dns)
    assert_in("dmarc", dns)
    assert_equal(len(dns["dkim"]), 3, "dkim record count")
    state["domain_id"] = resp["id"]


def test_get_domain_zone_file():
    status, resp = api_request(
        "GET", f"/domains/{state['domain_id']}/zone-file", state["api_key"]
    )
    assert_status(status, 200, resp)
    # zone-file returns plain text (text/dns), so resp is a string
    assert isinstance(resp, str) and "IN" in resp and "MX" in resp, \
        f"zone file doesn't look right: {resp!r}"


def test_verify_domain():
    status, resp = api_request(
        "POST", f"/domains/{state['domain_id']}/verify", state["api_key"]
    )
    assert_status(status, 200, resp)
    assert_equal(resp.get("status"), "verifying", "status")


def test_create_webhook():
    status, resp = api_request(
        "POST", "/webhooks", state["api_key"],
        body={
            "url": "https://example.com/webhook/e2e",
            "events": ["message.sent", "message.received"],
            "filter": {"inbox_id": state["inbox_id"]},
        },
    )
    assert_status(status, 201, resp)
    assert_in("id", resp)
    assert_in("secret", resp)
    assert resp["secret"].startswith("whsec_"), f"bad secret: {resp['secret']}"
    state["webhook_id"] = resp["id"]


def test_update_webhook():
    status, resp = api_request(
        "PATCH", f"/webhooks/{state['webhook_id']}", state["api_key"],
        body={"events": ["message.sent"]},
    )
    assert_status(status, 200, resp)
    assert_equal(resp.get("events"), ["message.sent"], "events")


def test_list_webhooks():
    status, resp = api_request("GET", "/webhooks", state["api_key"])
    assert_status(status, 200, resp)
    assert_in("data", resp)
    ids = {w.get("id") for w in resp["data"]}
    assert state["webhook_id"] in ids, "webhook missing from list"


def test_create_mailing_list():
    status, resp = api_request(
        "POST", "/lists", state["api_key"],
        body={
            "name": "E2E List",
            "inbox_id": state["inbox_id"],
            "members": [
                {"address": "alice@example.com", "name": "Alice"},
                {"address": "bob@example.com", "name": "Bob"},
            ],
        },
    )
    assert_status(status, 201, resp)
    assert_in("id", resp)
    assert_equal(resp.get("member_count"), 2, "member_count")
    state["list_id"] = resp["id"]


def test_get_list_with_members():
    status, resp = api_request(
        "GET", f"/lists/{state['list_id']}", state["api_key"]
    )
    assert_status(status, 200, resp)
    assert_in("members", resp)
    addresses = {m.get("address") for m in resp["members"]}
    assert "alice@example.com" in addresses, "alice missing from members"
    assert "bob@example.com" in addresses, "bob missing from members"


def test_search_messages():
    status, resp = api_request(
        "POST", "/search", state["api_key"],
        body={"query": "E2E Test Message"},
    )
    assert_status(status, 200, resp)
    assert_in("data", resp)
    # Search is eventually-consistent; don't assert non-empty but require
    # that the endpoint responds.


def test_metrics_usage():
    status, resp = api_request("GET", "/metrics/usage", state["api_key"])
    assert_status(status, 200, resp)
    assert_in("inboxes", resp)
    assert_in("tier", resp)
    assert_in("quotas", resp)
    assert_equal(resp.get("tier"), "free", "tier")


def test_metrics_query():
    status, resp = api_request(
        "POST", "/metrics/query", state["api_key"],
        body={"metric": "messages_sent", "period": "day"},
    )
    assert_status(status, 200, resp)
    # The API returns "data" as the list of data points.
    assert_in("data", resp)
    assert isinstance(resp["data"], list)


def test_ai_forbidden_for_free_tier():
    status, resp = api_request(
        "POST", "/ai/categorize", state["api_key"],
        body={
            "message_id": state["message_id"],
            "inbox_id": state["inbox_id"],
            "categories": ["work", "personal"],
        },
    )
    assert_status(status, 403, resp)
    assert_equal(resp.get("error", {}).get("code"), "FORBIDDEN", "error.code")


def test_billing_status_free():
    status, resp = api_request("GET", "/billing/status", state["api_key"])
    assert_status(status, 200, resp)
    assert_equal(resp.get("tier"), "free", "tier")
    assert_equal(resp.get("stripe_customer_id"), None, "stripe_customer_id")


def test_wait_for_email_timeout():
    status, resp = api_request(
        "POST", f"/inboxes/{state['inbox_id']}/wait", state["api_key"],
        body={
            "timeout": 2,
            "filter": {"subject_contains": "nonexistent-needle-that-never-matches-xyz"},
        },
    )
    assert_status(status, 408, resp)
    assert_equal(resp.get("error", {}).get("code"), "TIMEOUT", "error.code")


def test_wait_for_email_finds_match():
    status, resp = api_request(
        "POST", f"/inboxes/{state['inbox_id']}/wait", state["api_key"],
        body={
            "timeout": 2,
            "filter": {"subject_contains": "E2E Test Message"},
        },
    )
    assert_status(status, 200, resp)
    # Response is the matching message item directly
    assert_in("id", resp)
    assert "E2E Test Message" in resp.get("subject", ""), \
        f"wrong match: {resp.get('subject')!r}"


def test_extract_otp_from_email():
    # Send a message containing a verification code.
    status, resp = api_request(
        "POST", f"/inboxes/{state['inbox_id']}/messages", state["api_key"],
        body={
            "to": [state["inbox_email"]],
            "subject": "E2E OTP Test",
            "body_text": "Your verification code is 847291. Please do not share.",
        },
    )
    assert_status(status, 201, resp)
    state["otp_message_id"] = resp["id"]

    # Give the write a brief moment to be consistent.
    time.sleep(0.5)

    status, resp = api_request(
        "POST", f"/inboxes/{state['inbox_id']}/extract-otp", state["api_key"],
        body={"timeout": 5, "subject_contains": "E2E OTP Test"},
    )
    assert_status(status, 200, resp)
    assert_equal(resp.get("code"), "847291", "otp code")


def test_quota_enforcement_inboxes():
    # Free tier is 5 inboxes. We already have 2 (primary + pod).
    # Create until the 6th attempt is rejected.
    created_ids: list[str] = []
    quota_hit = False
    # Try up to 10 additional creates to be safe.
    for _ in range(10):
        status, resp = api_request(
            "POST", "/inboxes", state["api_key"],
            body={"display_name": "E2E Quota Inbox"},
        )
        if status == 201:
            created_ids.append(resp["id"])
            continue
        if status == 403:
            err = resp.get("error", {}) if isinstance(resp, dict) else {}
            if err.get("code") == "QUOTA_EXCEEDED":
                quota_hit = True
                break
        raise AssertionError(
            f"unexpected response during quota test: HTTP {status} {resp!r}"
        )
    state["extra_inbox_ids"] = created_ids
    assert quota_hit, f"expected quota exceeded after some creates, created {len(created_ids)}"


def test_delete_inbox():
    # Delete one of the quota-test inboxes. If there are none (shouldn't happen),
    # fall back to deleting the inbox_pod_id as a last resort.
    target = None
    if state["extra_inbox_ids"]:
        target = state["extra_inbox_ids"].pop()
    elif state.get("inbox_pod_id"):
        target = state["inbox_pod_id"]
        state["inbox_pod_id"] = None

    assert target is not None, "no inbox available to delete"
    status, resp = api_request(
        "DELETE", f"/inboxes/{target}", state["api_key"]
    )
    assert_status(status, 204, resp)


def test_delete_webhook():
    status, resp = api_request(
        "DELETE", f"/webhooks/{state['webhook_id']}", state["api_key"]
    )
    assert_status(status, 204, resp)
    state["webhook_id"] = None


def test_delete_domain():
    status, resp = api_request(
        "DELETE", f"/domains/{state['domain_id']}", state["api_key"]
    )
    assert_status(status, 204, resp)
    state["domain_id"] = None


def test_delete_api_key():
    status, resp = api_request(
        "DELETE", f"/api-keys/{state['extra_key_id']}", state["api_key"]
    )
    assert_status(status, 204, resp)
    state["extra_key_id"] = None


# ─── Cleanup ────────────────────────────────────────────────────────────────


def cleanup() -> int:
    """Best-effort cleanup of any resources still dangling after the test run.

    Returns the number of resources removed.
    """
    removed = 0
    if not state.get("api_key"):
        return removed
    key = state["api_key"]

    # Delete any quota inboxes still around
    for inbox_id in list(state.get("extra_inbox_ids", [])):
        s, _ = api_request("DELETE", f"/inboxes/{inbox_id}", key)
        if s == 204:
            removed += 1

    # Delete primary + pod inboxes
    for iid_key in ("inbox_id", "inbox_pod_id"):
        iid = state.get(iid_key)
        if iid:
            s, _ = api_request("DELETE", f"/inboxes/{iid}", key)
            if s == 204:
                removed += 1

    # Delete pod (only works if no inboxes are attached; best-effort)
    if state.get("pod_id"):
        s, _ = api_request("DELETE", f"/pods/{state['pod_id']}", key)
        if s == 204:
            removed += 1

    # Delete list
    if state.get("list_id"):
        s, _ = api_request("DELETE", f"/lists/{state['list_id']}", key)
        if s == 204:
            removed += 1

    # Delete webhook if still there
    if state.get("webhook_id"):
        s, _ = api_request("DELETE", f"/webhooks/{state['webhook_id']}", key)
        if s == 204:
            removed += 1

    # Delete domain if still there
    if state.get("domain_id"):
        s, _ = api_request("DELETE", f"/domains/{state['domain_id']}", key)
        if s == 204:
            removed += 1

    # Delete extra api key if still there
    if state.get("extra_key_id"):
        s, _ = api_request("DELETE", f"/api-keys/{state['extra_key_id']}", key)
        if s == 204:
            removed += 1

    return removed


# ─── Main ───────────────────────────────────────────────────────────────────


TESTS = [
    ("test_signup", test_signup),
    ("test_get_organization", test_get_organization),
    ("test_create_api_key", test_create_api_key),
    ("test_list_api_keys", test_list_api_keys),
    ("test_create_pod", test_create_pod),
    ("test_list_pods", test_list_pods),
    ("test_get_pod", test_get_pod),
    ("test_create_inbox_auto_email", test_create_inbox_auto_email),
    ("test_create_inbox_with_pod", test_create_inbox_with_pod),
    ("test_list_inboxes", test_list_inboxes),
    ("test_get_inbox", test_get_inbox),
    ("test_update_inbox", test_update_inbox),
    ("test_send_message", test_send_message),
    ("test_list_messages", test_list_messages),
    ("test_get_message", test_get_message),
    ("test_update_message_starred", test_update_message_starred),
    ("test_reply_to_message", test_reply_to_message),
    ("test_forward_message", test_forward_message),
    ("test_list_threads", test_list_threads),
    ("test_get_thread_with_messages", test_get_thread_with_messages),
    ("test_create_draft", test_create_draft),
    ("test_update_draft", test_update_draft),
    ("test_list_drafts", test_list_drafts),
    ("test_delete_draft", test_delete_draft),
    ("test_create_domain", test_create_domain),
    ("test_get_domain_zone_file", test_get_domain_zone_file),
    ("test_verify_domain", test_verify_domain),
    ("test_create_webhook", test_create_webhook),
    ("test_update_webhook", test_update_webhook),
    ("test_list_webhooks", test_list_webhooks),
    ("test_create_mailing_list", test_create_mailing_list),
    ("test_get_list_with_members", test_get_list_with_members),
    ("test_search_messages", test_search_messages),
    ("test_metrics_usage", test_metrics_usage),
    ("test_metrics_query", test_metrics_query),
    ("test_ai_forbidden_for_free_tier", test_ai_forbidden_for_free_tier),
    ("test_billing_status_free", test_billing_status_free),
    ("test_wait_for_email_timeout", test_wait_for_email_timeout),
    ("test_wait_for_email_finds_match", test_wait_for_email_finds_match),
    ("test_extract_otp_from_email", test_extract_otp_from_email),
    ("test_quota_enforcement_inboxes", test_quota_enforcement_inboxes),
    ("test_delete_inbox", test_delete_inbox),
    ("test_delete_webhook", test_delete_webhook),
    ("test_delete_domain", test_delete_domain),
    ("test_delete_api_key", test_delete_api_key),
]


def main() -> int:
    print("FreeMail Live API E2E Test Suite")
    print("================================")
    print(f"API: {API_URL}")
    print()

    overall_start = time.time()
    passed = 0
    failed = 0
    total = len(TESTS)

    for i, (name, fn) in enumerate(TESTS, start=1):
        ok = test(name, fn, i, total)
        if ok:
            passed += 1
        else:
            failed += 1

    duration = time.time() - overall_start

    print()
    print("================================")
    color = GREEN if failed == 0 else RED
    print(f"Results: {color}{passed} passed, {failed} failed{RESET}")
    print(f"Duration: {duration:.1f}s")

    print(f"{DIM}Cleaning up dangling resources...{RESET}")
    removed = cleanup()
    print(f"Cleanup: removed {removed} resource{'s' if removed != 1 else ''}")

    if failed > 0:
        print()
        print(f"{RED}Failed tests:{RESET}")
        for name, stat, _, err in results:
            if stat == "FAIL":
                print(f"  - {name}: {err}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
