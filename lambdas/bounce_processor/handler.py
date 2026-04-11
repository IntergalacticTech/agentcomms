"""Bounce Processor Lambda.

Processes SES bounce/complaint notifications from SNS.
"""

import json
import logging

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
    """Process a bounce notification."""
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


def process_complaint(notification: dict) -> None:
    """Process a complaint notification."""
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


def lookup_message_by_ses_id(ses_message_id: str) -> dict | None:
    """Look up a message by its SES message ID via GSI6."""
    items, _ = query_gsi("GSI6", f"SES#{ses_message_id}", limit=1)
    if not items:
        return None
    return items[0]
