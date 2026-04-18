"""Bounce Processor Lambda.

Processes SES bounce/complaint notifications from SNS. In addition to
marking the offending message, this Lambda increments per-org abuse
counters and triggers ``shared.abuse.evaluate_and_suspend_if_abusive`` so
chronically bouncing or complained-about orgs are auto-suspended.
"""

import json
import logging

from shared.abuse import (
    evaluate_and_suspend_if_abusive,
    increment_bounce_counter,
    increment_complaint_counter,
)
from shared.dynamo import query_gsi, update_item
from shared.models import now_iso

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point for SNS bounce/complaint notifications."""
    for record in event.get("Records", []):
        try:
            process_sns_record(record)
        except Exception:
            logger.exception("Failed to process SNS record")
            raise


def process_sns_record(record: dict) -> None:
    """Process a single SNS notification record."""
    sns_message = json.loads(record["Sns"]["Message"])
    notification_type = sns_message.get("notificationType")

    if notification_type == "Bounce":
        process_bounce(sns_message)
    elif notification_type == "Complaint":
        process_complaint(sns_message)
    else:
        logger.info("Ignoring notification type: %s", notification_type)


def process_bounce(notification: dict) -> None:
    """Mark the message bounced, bump the org's bounce counter, and
    auto-suspend the org if the rolling rate is over the SES threshold."""
    ses_message_id = notification["mail"]["messageId"]
    bounce = notification.get("bounce", {})
    bounce_type = bounce.get("bounceType", "Unknown")

    msg_item = lookup_message_by_ses_id(ses_message_id)
    if not msg_item:
        logger.warning("No message found for SES ID %s", ses_message_id)
        return

    update_item(msg_item["PK"], msg_item["SK"], {
        "status": "bounced",
        "bounce_type": bounce_type,
        "bounced_at": now_iso(),
        "updated_at": now_iso(),
    })
    logger.info("Marked message %s as bounced (%s)", msg_item.get("message_id"), bounce_type)

    org_id = msg_item.get("org_id", "")
    # Permanent ("hard") bounces count toward the abuse rate; transient and
    # undetermined bounces do not.
    if org_id and bounce_type == "Permanent":
        increment_bounce_counter(org_id)
        reason = evaluate_and_suspend_if_abusive(org_id)
        if reason:
            logger.warning("auto-suspended org %s: %s", org_id, reason)


def process_complaint(notification: dict) -> None:
    """Mark the message complained, bump the org's complaint counter, and
    auto-suspend the org if the rolling rate is over the SES threshold."""
    ses_message_id = notification["mail"]["messageId"]

    msg_item = lookup_message_by_ses_id(ses_message_id)
    if not msg_item:
        logger.warning("No message found for SES ID %s", ses_message_id)
        return

    update_item(msg_item["PK"], msg_item["SK"], {
        "status": "complained",
        "complained_at": now_iso(),
        "updated_at": now_iso(),
    })
    logger.info("Marked message %s as complained", msg_item.get("message_id"))

    org_id = msg_item.get("org_id", "")
    if org_id:
        increment_complaint_counter(org_id)
        reason = evaluate_and_suspend_if_abusive(org_id)
        if reason:
            logger.warning("auto-suspended org %s: %s", org_id, reason)


def lookup_message_by_ses_id(ses_message_id: str) -> dict | None:
    """Look up a message by its SES message ID via GSI6."""
    items, _ = query_gsi("GSI6", f"SES#{ses_message_id}", limit=1)
    if not items:
        return None
    return items[0]
