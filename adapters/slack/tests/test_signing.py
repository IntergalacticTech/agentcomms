# adapters/slack/tests/test_signing.py
"""Tests for Slack request signature verification (Task 1a)."""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from adapters.slack.signing import verify_slack_request


SIGNING_SECRET = "8f742231b10e8888abcd99babd0a5e90"


def _make_valid_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Helper to generate a valid Slack signature for testing."""
    body_str = body.decode("utf-8")
    basestring = f"v0:{timestamp}:{body_str}"
    mac = hmac.new(secret.encode(), basestring.encode(), hashlib.sha256)
    return f"v0={mac.hexdigest()}"


# ── Test 1: valid signature + recent timestamp ──────────────────────────────

def test_valid_signature_returns_true():
    body = b"token=xoxb&team_id=T012AB3C4&event_id=Ev0PV52K25"
    timestamp = str(int(time.time()))
    sig = _make_valid_signature(SIGNING_SECRET, timestamp, body)
    assert verify_slack_request(SIGNING_SECRET, timestamp, body, sig) is True


# ── Test 2: bad signature returns False ─────────────────────────────────────

def test_bad_signature_returns_false():
    body = b"token=xoxb&team_id=T012AB3C4"
    timestamp = str(int(time.time()))
    assert verify_slack_request(
        SIGNING_SECRET, timestamp, body, "v0=badhexvalue"
    ) is False


# ── Test 3: stale timestamp returns False ───────────────────────────────────

def test_stale_timestamp_returns_false():
    body = b"token=xoxb&team_id=T012AB3C4"
    # 10 minutes in the past
    old_timestamp = str(int(time.time()) - 601)
    sig = _make_valid_signature(SIGNING_SECRET, old_timestamp, body)
    assert verify_slack_request(SIGNING_SECRET, old_timestamp, body, sig) is False


# ── Test 4: tampered body returns False ─────────────────────────────────────

def test_tampered_body_returns_false():
    original_body = b"token=xoxb&team_id=T012AB3C4"
    tampered_body = b"token=xoxb&team_id=T012AB3C4&injected=evil"
    timestamp = str(int(time.time()))
    sig = _make_valid_signature(SIGNING_SECRET, timestamp, original_body)
    # Verify with tampered body — should fail
    assert verify_slack_request(SIGNING_SECRET, timestamp, tampered_body, sig) is False


# ── Test 5: future timestamp within 5 min is accepted ───────────────────────

def test_near_future_timestamp_accepted():
    body = b"payload=test"
    # 2 minutes in the future (clock skew)
    future_ts = str(int(time.time()) + 120)
    sig = _make_valid_signature(SIGNING_SECRET, future_ts, body)
    assert verify_slack_request(SIGNING_SECRET, future_ts, body, sig) is True


# ── Test 6: non-numeric timestamp returns False ──────────────────────────────

def test_non_numeric_timestamp_returns_false():
    body = b"payload=test"
    assert verify_slack_request(SIGNING_SECRET, "not-a-timestamp", body, "v0=abc") is False
