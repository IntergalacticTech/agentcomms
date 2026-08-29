"""Abuse tracking, rate limiting, and auto-suspend.

Three concerns are bundled here so handlers only have one import path:

1. **Send rate limits** — sliding-hour outbound message cap per tier
   enforced by a DynamoDB atomic counter with a 90-minute TTL. Bursts within
   the hour are allowed; exceeding the per-hour cap returns 429 until the
   bucket rolls over. Configured via ``max_messages_per_hour`` in
   ``shared/tiers.py``.

2. **Bounce / complaint feedback** — counters incremented from the
   BounceProcessor Lambda whenever SES delivers a feedback notification.
   We keep a rolling sample of the last N sends so percentage-based
   thresholds work correctly for low-volume users.

3. **Auto-suspend** — when bounce or complaint rate exceeds the SES-
   recommended thresholds, the org is set to ``status="suspended"`` and a
   webhook event is fired. Authorizer rejects all subsequent requests with
   ``403 SUSPENDED``.

Thresholds (matching SES guidance):
    - Bounce rate    > 5%   → suspend
    - Complaint rate > 0.1% → suspend

Both apply only after a warm-up window of 100 sends so a single bounce on
the second-ever send doesn't suspend the account.
"""

import logging
import os
import time
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from shared.dynamo import get_item
from shared.models import org_keys, now_iso
from shared.response import error
from shared.tiers import UNLIMITED, get_quotas

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "victorymail")

# Warm-up sample size before bounce/complaint percentages become enforceable
WARMUP_SENDS = 100

# SES-recommended thresholds
BOUNCE_RATE_LIMIT = 0.05      # 5%
COMPLAINT_RATE_LIMIT = 0.001  # 0.1%

_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


# ---------------------------------------------------------------------------
# Send rate limit (sliding hour bucket)
# ---------------------------------------------------------------------------

def check_send_rate(org_id: str, tier: str = "free") -> Optional[dict]:
    """Atomically increment the current hour's send counter for ``org_id``
    and return None if the org is still under quota, or a 429-style error
    response dict if the cap was hit.

    The counter key includes the current hour bucket, so when the hour
    rolls over a fresh counter starts. The DDB record carries a TTL so
    expired buckets self-clean.
    """
    quotas = get_quotas(tier)
    cap = quotas.get("max_messages_per_hour", 0)
    if cap < 0:
        return None  # Enterprise → unlimited

    now = int(time.time())
    hour_bucket = now // 3600
    bucket_key = f"SENDRATE#{org_id}#H{hour_bucket}"

    table = _get_table()
    try:
        resp = table.update_item(
            Key={"PK": bucket_key, "SK": bucket_key},
            UpdateExpression="SET #c = if_not_exists(#c, :z) + :one, #ttl = :ttl",
            ExpressionAttributeNames={"#c": "count", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":z": 0,
                # Keep the row 90 minutes so a request right at the hour
                # boundary still sees an accurate count
                ":ttl": now + 5400,
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(resp["Attributes"]["count"])
    except ClientError:
        # Fail open — never block sends because of an infrastructure hiccup.
        logger.exception("send rate counter update failed for %s", org_id)
        return None

    if cap == 0 or count > cap:
        reset_at = (hour_bucket + 1) * 3600
        retry_after = max(reset_at - now, 1)
        return {
            "statusCode": 429,
            "headers": {
                "Content-Type": "application/json",
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(cap),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_at),
            },
            "body": (
                '{"error": {"code": "RATE_LIMITED", "message": '
                f'"Send rate limit exceeded for tier \'{tier}\' '
                f'({cap}/hour). Retry in {retry_after}s or upgrade for higher limits."'
                "}}"
            ),
        }
    return None


# ---------------------------------------------------------------------------
# Send / bounce / complaint counters
# ---------------------------------------------------------------------------

def increment_send_counter(org_id: str) -> None:
    """Bump the org's lifetime send counter. Called from messages handler
    after a successful enqueue."""
    _bump_counter(org_id, "sends_total")


def increment_bounce_counter(org_id: str) -> None:
    _bump_counter(org_id, "bounces_total")


def increment_complaint_counter(org_id: str) -> None:
    _bump_counter(org_id, "complaints_total")


def _bump_counter(org_id: str, field: str) -> None:
    keys = org_keys(org_id)
    try:
        _get_table().update_item(
            Key={"PK": keys["PK"], "SK": keys["SK"]},
            UpdateExpression="SET #f = if_not_exists(#f, :z) + :one, #u = :now",
            ExpressionAttributeNames={"#f": field, "#u": "updated_at"},
            ExpressionAttributeValues={":one": 1, ":z": 0, ":now": now_iso()},
        )
    except ClientError:
        logger.exception("counter %s bump failed for %s", field, org_id)


# ---------------------------------------------------------------------------
# Auto-suspend
# ---------------------------------------------------------------------------

def evaluate_and_suspend_if_abusive(org_id: str) -> Optional[str]:
    """Check the org's bounce + complaint rates against the thresholds and
    suspend the account if they're over. Returns the reason string when a
    suspension occurs, or None otherwise. Idempotent — calling on an
    already-suspended org is a no-op.
    """
    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return None
    if org.get("status") == "suspended":
        return None

    sends = int(org.get("sends_total", 0))
    bounces = int(org.get("bounces_total", 0))
    complaints = int(org.get("complaints_total", 0))

    if sends < WARMUP_SENDS:
        return None  # Not enough data

    bounce_rate = bounces / sends
    complaint_rate = complaints / sends

    reason = None
    if complaint_rate > COMPLAINT_RATE_LIMIT:
        reason = (
            f"complaint_rate={complaint_rate:.4%} > "
            f"{COMPLAINT_RATE_LIMIT:.2%} (SES guidance). "
            f"{complaints} complaints across {sends} sends."
        )
    elif bounce_rate > BOUNCE_RATE_LIMIT:
        reason = (
            f"bounce_rate={bounce_rate:.4%} > "
            f"{BOUNCE_RATE_LIMIT:.2%} (SES guidance). "
            f"{bounces} bounces across {sends} sends."
        )

    if not reason:
        return None

    suspend_org(org_id, reason)
    return reason


def suspend_org(org_id: str, reason: str) -> None:
    keys = org_keys(org_id)
    try:
        _get_table().update_item(
            Key={"PK": keys["PK"], "SK": keys["SK"]},
            UpdateExpression=(
                "SET #s = :sus, suspended_reason = :r, suspended_at = :now, "
                "updated_at = :now"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":sus": "suspended",
                ":r": reason,
                ":now": now_iso(),
            },
        )
        logger.warning("suspended org %s: %s", org_id, reason)
    except ClientError:
        logger.exception("failed to suspend org %s", org_id)
        return

    # Best-effort webhook
    try:
        from shared.webhook_publisher import publish_event
        publish_event("abuse.suspended", org_id, {
            "org_id": org_id,
            "reason": reason,
            "suspended_at": now_iso(),
        })
    except Exception:
        logger.exception("failed to publish abuse.suspended event")


def unsuspend_org(org_id: str) -> bool:
    """Operator action — clear the suspended flag and reset abuse counters
    so the warm-up window starts fresh."""
    keys = org_keys(org_id)
    try:
        _get_table().update_item(
            Key={"PK": keys["PK"], "SK": keys["SK"]},
            UpdateExpression=(
                "SET #s = :a, sends_total = :z, bounces_total = :z, "
                "complaints_total = :z, suspended_reason = :empty, "
                "updated_at = :now REMOVE suspended_at"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":a": "active",
                ":z": 0,
                ":empty": "",
                ":now": now_iso(),
            },
        )
        return True
    except ClientError:
        logger.exception("failed to unsuspend org %s", org_id)
        return False


def suspended_response() -> dict:
    return error(
        "SUSPENDED",
        "This account has been suspended due to abuse signals (excessive "
        "bounces or spam complaints). Contact support to appeal.",
        403,
    )
