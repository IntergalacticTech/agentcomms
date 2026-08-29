# SPDX-License-Identifier: Apache-2.0
"""Unit tests for Slack signing (raw-bytes HMAC) and OAuth redirect handling."""
from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import patch

from adapters.slack.signing import verify_slack_request
from adapters.slack import oauth


def _sign(secret: str, ts: str, body: bytes) -> str:
    basestring = b"v0:" + ts.encode("utf-8") + b":" + body
    mac = hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256)
    return f"v0={mac.hexdigest()}"


def test_verify_slack_request_over_raw_bytes():
    secret = "shhh"
    ts = str(int(time.time()))
    body = b'{"type":"event_callback"}'
    sig = _sign(secret, ts, body)
    assert verify_slack_request(secret, ts, body, sig) is True


def test_verify_slack_request_handles_non_utf8_bytes():
    # A body with bytes that are not valid UTF-8 must still verify: the old
    # implementation decoded with errors="replace" and corrupted them.
    secret = "shhh"
    ts = str(int(time.time()))
    body = b"\xff\xfe\x00payload"
    sig = _sign(secret, ts, body)
    assert verify_slack_request(secret, ts, body, sig) is True


def test_verify_slack_request_rejects_tampered_body():
    secret = "shhh"
    ts = str(int(time.time()))
    sig = _sign(secret, ts, b"original")
    assert verify_slack_request(secret, ts, b"tampered", sig) is False


def test_verify_slack_request_rejects_stale_timestamp():
    secret = "shhh"
    ts = str(int(time.time()) - 10_000)
    body = b"x"
    sig = _sign(secret, ts, body)
    assert verify_slack_request(secret, ts, body, sig) is False


def test_get_oauth_callback_url_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv(
        "AGENTCOMMS_SLACK_OAUTH_CALLBACK_URL",
        "https://api.example.com/prod/webhooks/slack/oauth/callback",
    )
    assert (
        oauth.get_oauth_callback_url()
        == "https://api.example.com/prod/webhooks/slack/oauth/callback"
    )


def test_get_oauth_callback_url_falls_back_to_host_and_stage(monkeypatch):
    monkeypatch.delenv("AGENTCOMMS_SLACK_OAUTH_CALLBACK_URL", raising=False)
    monkeypatch.setenv("AGENTCOMMS_API_HOST", "api.example.com")
    monkeypatch.setenv("AGENTCOMMS_API_STAGE", "prod")
    assert (
        oauth.get_oauth_callback_url()
        == "https://api.example.com/prod/webhooks/slack/oauth/callback"
    )


def test_build_oauth_url_uses_callback_not_return_url(monkeypatch):
    monkeypatch.setenv(
        "AGENTCOMMS_SLACK_OAUTH_CALLBACK_URL",
        "https://api.example.com/prod/webhooks/slack/oauth/callback",
    )
    with patch.object(oauth, "get_client_id", return_value="CID"):
        url = oauth.build_oauth_url(
            return_url="https://tenant.example.org/done", state="nonce123"
        )
    # redirect_uri must be the AgentComms callback, NOT the tenant return_url.
    assert "redirect_uri=https%3A%2F%2Fapi.example.com%2Fprod%2Fwebhooks" in url
    assert "tenant.example.org" not in url
    assert "state=nonce123" in url


def test_is_safe_return_url():
    assert oauth.is_safe_return_url("https://good.example.com/cb") is True
    assert oauth.is_safe_return_url("http://good.example.com/cb") is False
    assert oauth.is_safe_return_url("javascript:alert(1)") is False
    assert oauth.is_safe_return_url("") is False


def test_is_safe_return_url_allowlist(monkeypatch):
    monkeypatch.setenv("AGENTCOMMS_ALLOWED_REDIRECT_HOSTS", "good.example.com")
    assert oauth.is_safe_return_url("https://good.example.com/cb") is True
    assert oauth.is_safe_return_url("https://evil.example.com/cb") is False
