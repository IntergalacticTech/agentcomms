# SPDX-License-Identifier: Apache-2.0
"""Unit tests for push APNs platform selection (sandbox vs prod)."""
from __future__ import annotations

from adapters.push.adapter import _apns_platform


def test_default_is_sandbox(monkeypatch):
    monkeypatch.delenv("APNS_PLATFORM", raising=False)
    assert _apns_platform() == "APNS_SANDBOX"
    assert _apns_platform({}) == "APNS_SANDBOX"


def test_config_prod_selects_production():
    assert _apns_platform({"apns_platform": "prod"}) == "APNS"
    assert _apns_platform({"apns_platform": "PRODUCTION"}) == "APNS"
    assert _apns_platform({"apns_platform": "APNS"}) == "APNS"


def test_config_sandbox_stays_sandbox():
    assert _apns_platform({"apns_platform": "sandbox"}) == "APNS_SANDBOX"
    assert _apns_platform({"apns_platform": "anything-else"}) == "APNS_SANDBOX"


def test_env_prod_selects_production(monkeypatch):
    monkeypatch.setenv("APNS_PLATFORM", "production")
    assert _apns_platform() == "APNS"


def test_config_overrides_env(monkeypatch):
    monkeypatch.setenv("APNS_PLATFORM", "production")
    # config takes precedence over env
    assert _apns_platform({"apns_platform": "sandbox"}) == "APNS_SANDBOX"
