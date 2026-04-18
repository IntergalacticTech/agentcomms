"""SMS inbound processor Lambda.

Consumes AWS End User Messaging inbound SMS events via SNS and stores them
alongside email messages in the single-table DynamoDB design using
``channel: "sms"``. Reuses the same thread model so an agent polling
``/inboxes/{id}/wait`` with ``channel=sms`` can capture OTP codes delivered
to a phone number the same way it captures email OTPs.

Event shape (AWS End User Messaging SMS inbound via SNS):
    {
      "originationNumber": "+14155551234",
      "destinationNumber":  "+18005550000",
      "messageBody":        "Your code is 482917",
      "messageId":          "abc123",
      "inboundMessageId":   "def456",
      "previousPublishedMessageId": null,
      "messageKeyword":     "KEYWORD",
      "timestamp":          "2026-04-14T...",
    }
"""

import json
import logging

from shared.dynamo import put_item, query_gsi
from shared.models import (
    message_gsi1,
    message_gsi3,
    message_keys,
    now_iso,
    thread_gsi1,
    thread_keys,
)
from shared.ulid import generate_ulid
from shared.webhook_publisher import publish_event

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point: SNS wrapping End User Messaging inbound SMS events."""
    for record in event.get("Records", []):
        try:
            raw = record.get("Sns", {}).get("Message", "{}")
            sms = json.loads(raw) if isinstance(raw, str) else raw
            process_inbound_sms(sms)
        except Exception:
            logger.exception("Failed to process SMS record")
            raise


def process_inbound_sms(sms: dict) -> None:
    origination = sms.get("originationNumber") or sms.get("from", "")
    destination = sms.get("destinationNumber") or sms.get("to", "")
    body_text = sms.get("messageBody") or sms.get("body", "")
    ses_style_id = sms.get("inboundMessageId") or sms.get("messageId") or generate_ulid()

    if not destination:
        logger.warning("SMS record has no destination number, skipping")
        return

    # Look up the inbox by SMS phone number using GSI2. We store phone
    # numbers using the same GSI2 partition so one inbox can hold both an
    # email and a phone number.
    items, _ = query_gsi("GSI2", f"PHONE#{destination}", limit=1)
    if not items:
        logger.info("No inbox found for phone %s, skipping", destination)
        return

    inbox = items[0]
    if inbox.get("status") != "active":
        logger.info("Inbox for %s is not active, skipping", destination)
        return

    inbox_id = inbox["SK"].replace("INBOX#", "")
    org_id = inbox["PK"].replace("ORG#", "")

    message_id = generate_ulid()
    thread_id = generate_ulid()
    timestamp = now_iso()
    snippet = body_text[:200] if body_text else ""

    msg_item = {
        **message_keys(inbox_id, message_id),
        **message_gsi1(thread_id, message_id),
        **message_gsi3(org_id, message_id),
        "entity_type": "Message",
        "id": message_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": thread_id,
        "direction": "inbound",
        "channel": "sms",
        "status": "received",
        "from_addr": {"name": "", "address": origination},
        "to": [{"name": "", "address": destination}],
        "cc": [],
        "bcc": [],
        "reply_to": [],
        "subject": "",  # SMS has no subject
        "snippet": snippet,
        "body_text": body_text,
        "is_read": False,
        "is_starred": False,
        "labels": [],
        "category": None,
        "has_attachments": False,
        "attachment_count": 0,
        "ses_message_id": ses_style_id,
        "received_at": timestamp,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    put_item(msg_item)

    # Create a minimal thread record so /inboxes/{id}/threads lists it
    thread_item = {
        **thread_keys(inbox_id, thread_id),
        **thread_gsi1(inbox_id, thread_id),
        "entity_type": "Thread",
        "id": thread_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "channel": "sms",
        "subject": "",
        "snippet": snippet,
        "message_count": 1,
        "unread_count": 1,
        "participants": [
            {"name": "", "address": origination},
            {"name": "", "address": destination},
        ],
        "labels": [],
        "category": None,
        "is_read": False,
        "is_starred": False,
        "is_trash": False,
        "last_message_at": timestamp,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    put_item(thread_item)

    try:
        publish_event(
            "message.received",
            org_id,
            {
                "message_id": message_id,
                "inbox_id": inbox_id,
                "channel": "sms",
                "from": origination,
                "subject": "",
                "received_at": timestamp,
            },
        )
    except Exception:
        logger.exception("Failed to publish SMS webhook event")
