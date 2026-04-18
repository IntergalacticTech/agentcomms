"""Canonical tier definitions for FreeMail.

Single source of truth for quotas, rate limits, and tier metadata.
All handlers that need to know about tiers (signup, billing, quotas,
rate_limit, ai, organizations) must import from here.

Sentinel convention: ``-1`` means unlimited. ``0`` means zero allowed
(hard block). Any positive integer is the enforced cap.
"""

from typing import Literal

Tier = Literal["free", "starter", "pro", "enterprise"]

TIERS: tuple[Tier, ...] = ("free", "starter", "pro", "enterprise")
DEFAULT_TIER: Tier = "free"

# -1 sentinel = unlimited
UNLIMITED = -1


FREE_QUOTAS = {
    "max_inboxes": 1,
    "max_messages_per_day": 50,
    "max_messages_per_hour": 10,
    "max_api_keys": 1,
    "max_pods": 1,
    "max_domains": 0,
    "max_webhooks": 1,
    "max_storage_mb": 100,
    "retention_days": 7,
    "ai_calls_per_month": 0,
}

STARTER_QUOTAS = {
    "max_inboxes": 5,
    "max_messages_per_day": 500,
    "max_messages_per_hour": 100,
    "max_api_keys": 5,
    "max_pods": 2,
    "max_domains": 1,
    "max_webhooks": 3,
    "max_storage_mb": 1024,
    "retention_days": 30,
    "ai_calls_per_month": 100,
}

PRO_QUOTAS = {
    "max_inboxes": 100,
    "max_messages_per_day": 5000,
    "max_messages_per_hour": 1000,
    "max_api_keys": 25,
    "max_pods": 10,
    "max_domains": 10,
    "max_webhooks": 25,
    "max_storage_mb": 25 * 1024,
    "retention_days": 365,
    "ai_calls_per_month": 2000,
}

ENTERPRISE_QUOTAS = {
    "max_inboxes": UNLIMITED,
    "max_messages_per_day": UNLIMITED,
    "max_messages_per_hour": UNLIMITED,
    "max_api_keys": UNLIMITED,
    "max_pods": UNLIMITED,
    "max_domains": UNLIMITED,
    "max_webhooks": UNLIMITED,
    "max_storage_mb": UNLIMITED,
    "retention_days": UNLIMITED,
    "ai_calls_per_month": UNLIMITED,
}

TIER_QUOTAS: dict[str, dict] = {
    "free": FREE_QUOTAS,
    "starter": STARTER_QUOTAS,
    "pro": PRO_QUOTAS,
    "enterprise": ENTERPRISE_QUOTAS,
}


# Per-tier API request rate limits (requests/min and requests/day)
RATE_LIMITS: dict[str, dict] = {
    "free": {"requests_per_minute": 30, "requests_per_day": 5000},
    "starter": {"requests_per_minute": 120, "requests_per_day": 50000},
    "pro": {"requests_per_minute": 600, "requests_per_day": 500000},
    "enterprise": {"requests_per_minute": UNLIMITED, "requests_per_day": UNLIMITED},
}


# Tiers that have AI features unlocked
AI_ENABLED_TIERS: frozenset[str] = frozenset({"starter", "pro", "enterprise"})


def get_quotas(tier: str) -> dict:
    """Return the quota dict for a tier name, defaulting to free."""
    return TIER_QUOTAS.get(tier, FREE_QUOTAS)


def get_rate_limits(tier: str) -> dict:
    """Return the rate-limit dict for a tier name, defaulting to free."""
    return RATE_LIMITS.get(tier, RATE_LIMITS["free"])


def ai_enabled(tier: str) -> bool:
    """Whether this tier has access to AI features."""
    return tier in AI_ENABLED_TIERS
