"""Rate limiting using DynamoDB atomic counters."""

import os
import time
import boto3
from boto3.dynamodb.conditions import Attr

from shared.tiers import RATE_LIMITS, UNLIMITED

TABLE_NAME = os.environ.get("TABLE_NAME", "victorymail")

DEFAULT_LIMIT = RATE_LIMITS["free"]


def check_rate_limit(org_id: str, tier: str = "free") -> dict | None:
    """Check if the org has exceeded its rate limit.

    Returns None if OK, or a dict with rate limit info if exceeded.
    Uses DynamoDB atomic increment with TTL for automatic cleanup.
    """
    limits = RATE_LIMITS.get(tier, DEFAULT_LIMIT)

    # Enterprise tier: unlimited on both dimensions -> skip entirely
    if limits.get("requests_per_minute", 0) == UNLIMITED and limits.get("requests_per_day", 0) == UNLIMITED:
        return None

    now = int(time.time())
    current_minute = now // 60
    current_day = now // 86400

    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    # Check per-minute rate limit
    minute_key = f"RATE#{org_id}#MIN#{current_minute}"
    try:
        resp = table.update_item(
            Key={"PK": minute_key, "SK": minute_key},
            UpdateExpression="SET #count = if_not_exists(#count, :zero) + :one, #ttl = :ttl",
            ExpressionAttributeNames={"#count": "count", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":zero": 0,
                ":ttl": now + 120,  # TTL: 2 minutes
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(resp["Attributes"]["count"])
        if count > limits["requests_per_minute"]:
            return {
                "limited": True,
                "limit": limits["requests_per_minute"],
                "remaining": 0,
                "reset": (current_minute + 1) * 60,
                "retry_after": (current_minute + 1) * 60 - now,
            }
    except Exception:
        pass  # Fail open - don't block requests if rate limiting fails

    # Check per-day rate limit
    day_key = f"RATE#{org_id}#DAY#{current_day}"
    try:
        resp = table.update_item(
            Key={"PK": day_key, "SK": day_key},
            UpdateExpression="SET #count = if_not_exists(#count, :zero) + :one, #ttl = :ttl",
            ExpressionAttributeNames={"#count": "count", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":zero": 0,
                ":ttl": now + 90000,  # TTL: 25 hours
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(resp["Attributes"]["count"])
        if count > limits["requests_per_day"]:
            return {
                "limited": True,
                "limit": limits["requests_per_day"],
                "remaining": 0,
                "reset": (current_day + 1) * 86400,
                "retry_after": 3600,
            }
    except Exception:
        pass

    return None


def get_rate_limit_headers(org_id: str, tier: str = "free") -> dict:
    """Get rate limit headers for the response."""
    limits = RATE_LIMITS.get(tier, DEFAULT_LIMIT)
    now = int(time.time())
    current_minute = now // 60
    reset = (current_minute + 1) * 60
    return {
        "X-RateLimit-Limit": str(limits["requests_per_minute"]),
        "X-RateLimit-Reset": str(reset),
    }
