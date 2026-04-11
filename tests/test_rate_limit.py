"""Tests for rate limiting."""

import time

import pytest

from shared.rate_limit import RATE_LIMITS, check_rate_limit


def test_under_limit_passes(aws_env):
    """check_rate_limit returns None when under limit."""
    result = check_rate_limit("org_rate_01", tier="free")
    assert result is None


def test_over_minute_limit_blocked(aws_env):
    """check_rate_limit returns limited=True when over per-minute limit."""
    org_id = "org_rate_02"
    table = aws_env["table"]
    now = int(time.time())
    current_minute = now // 60
    minute_key = f"RATE#{org_id}#MIN#{current_minute}"

    # Pre-seed the counter to just at the limit
    table.put_item(Item={
        "PK": minute_key,
        "SK": minute_key,
        "count": RATE_LIMITS["free"]["requests_per_minute"],
        "ttl": now + 120,
    })

    # Next call should exceed the limit
    result = check_rate_limit(org_id, tier="free")
    assert result is not None
    assert result["limited"] is True
    assert result["remaining"] == 0
    assert result["limit"] == RATE_LIMITS["free"]["requests_per_minute"]
    assert result["retry_after"] > 0


def test_pro_tier_higher_limit(aws_env):
    """Pro tier has higher limits than free tier."""
    org_id = "org_rate_03"
    table = aws_env["table"]
    now = int(time.time())
    current_minute = now // 60
    minute_key = f"RATE#{org_id}#MIN#{current_minute}"

    # Set counter above free limit (60) but below pro limit (600)
    table.put_item(Item={
        "PK": minute_key,
        "SK": minute_key,
        "count": 100,
        "ttl": now + 120,
    })

    # Free tier should be blocked
    result_free = check_rate_limit(org_id, tier="free")
    assert result_free is not None
    assert result_free["limited"] is True

    # Pro tier should pass (counter is now 102 after two check_rate_limit
    # calls incrementing it, but still well under 600)
    # Reset counter to 100 for clean pro test
    table.put_item(Item={
        "PK": minute_key,
        "SK": minute_key,
        "count": 100,
        "ttl": now + 120,
    })
    result_pro = check_rate_limit(org_id, tier="pro")
    assert result_pro is None
