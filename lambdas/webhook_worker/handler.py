"""Webhook Delivery Worker Lambda.

Triggered by SQS (webhook queue). Delivers webhook events to customer endpoints.
"""

import hashlib
import hmac
import json
import logging
import urllib.request
import urllib.error

from shared.dynamo import query_gsi, _get_table
from shared.models import now_iso

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DELIVERY_TIMEOUT = 10  # seconds


def handler(event, context):
    """Lambda entry point for SQS webhook delivery."""
    for record in event.get("Records", []):
        try:
            process_record(record)
        except Exception:
            logger.exception("Failed to process webhook record")
            raise


def process_record(record: dict) -> None:
    """Process a single SQS record containing a webhook event."""
    body = json.loads(record["body"])
    event_type = body["event_type"]
    org_id = body["org_id"]
    data = body["data"]

    # Look up all webhooks for this org
    webhooks, _ = query_gsi("GSI1", f"ORG#{org_id}#WEBHOOKS")

    for webhook in webhooks:
        try:
            maybe_deliver(webhook, event_type, data)
        except Exception:
            logger.exception(
                "Error delivering webhook %s for org %s",
                webhook.get("id", "unknown"),
                org_id,
            )


def maybe_deliver(webhook: dict, event_type: str, data: dict) -> None:
    """Check filters and deliver webhook if applicable."""
    # Must be active
    if webhook.get("status") != "active":
        return

    # Must subscribe to this event type
    events = webhook.get("events", [])
    if event_type not in events:
        return

    # Check filters (pod_ids, inbox_ids)
    wh_filter = webhook.get("filter", {})
    if wh_filter:
        pod_ids = wh_filter.get("pod_ids")
        if pod_ids and data.get("pod_id") not in pod_ids:
            return

        inbox_ids = wh_filter.get("inbox_ids")
        if inbox_ids and data.get("inbox_id") not in inbox_ids:
            return

    deliver(webhook, event_type, data)


def deliver(webhook: dict, event_type: str, data: dict) -> None:
    """Build payload, sign, and POST to the webhook URL."""
    url = webhook["url"]
    secret = webhook.get("secret", "")
    org_id = webhook.get("org_id", "")
    webhook_id = webhook.get("id", "")

    payload = {
        "event": event_type,
        "data": data,
        "timestamp": now_iso(),
    }
    payload_json = json.dumps(payload, separators=(",", ":"))

    # Compute HMAC-SHA256 signature
    signature = hmac.new(
        secret.encode(), payload_json.encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-FreeMail-Signature": f"sha256={signature}",
        "X-FreeMail-Event": event_type,
    }

    req = urllib.request.Request(
        url,
        data=payload_json.encode(),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=DELIVERY_TIMEOUT) as resp:
            status = resp.status
        if 200 <= status < 300:
            _update_stats(org_id, webhook_id, success=True)
            logger.info("Webhook %s delivered to %s (status %s)", webhook_id, url, status)
        else:
            _update_stats(org_id, webhook_id, success=False)
            logger.warning("Webhook %s failed: %s returned %s", webhook_id, url, status)
    except Exception as exc:
        _update_stats(org_id, webhook_id, success=False)
        logger.warning("Webhook %s failed: %s - %s", webhook_id, url, exc)


def _update_stats(org_id: str, webhook_id: str, success: bool) -> None:
    """Increment delivery_stats counters on the webhook item."""
    now = now_iso()
    table = _get_table()

    if success:
        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"WEBHOOK#{webhook_id}"},
            UpdateExpression=(
                "SET delivery_stats.#total = if_not_exists(delivery_stats.#total, :zero) + :one, "
                "delivery_stats.#success = if_not_exists(delivery_stats.#success, :zero) + :one, "
                "delivery_stats.last_delivered_at = :now"
            ),
            ExpressionAttributeNames={
                "#total": "total",
                "#success": "success",
            },
            ExpressionAttributeValues={
                ":zero": 0,
                ":one": 1,
                ":now": now,
            },
        )
    else:
        table.update_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"WEBHOOK#{webhook_id}"},
            UpdateExpression=(
                "SET delivery_stats.#total = if_not_exists(delivery_stats.#total, :zero) + :one, "
                "delivery_stats.#failed = if_not_exists(delivery_stats.#failed, :zero) + :one, "
                "delivery_stats.last_failed_at = :now"
            ),
            ExpressionAttributeNames={
                "#total": "total",
                "#failed": "failed",
            },
            ExpressionAttributeValues={
                ":zero": 0,
                ":one": 1,
                ":now": now,
            },
        )
