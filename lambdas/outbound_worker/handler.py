"""Outbound Email Worker Lambda.

SQS consumer that reads messages from DynamoDB, builds MIME, and sends via SES.
"""

import json
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import boto3

from shared.domains import DEFAULT_PLATFORM_DOMAIN, split_address
from shared.dynamo import get_item, update_item
from shared.models import message_keys, now_iso
from shared.s3 import get_body

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SES_CONFIG_SET = os.environ.get("SES_CONFIG_SET", "")


def handler(event, context):
    """Lambda entry point for SQS outbound email processing."""
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        process_message(
            message_id=body["message_id"],
            inbox_id=body["inbox_id"],
        )


def process_message(message_id: str, inbox_id: str) -> None:
    """Process a single outbound message."""
    # Get message from DynamoDB
    keys = message_keys(inbox_id, message_id)
    msg = get_item(keys["PK"], keys["SK"])

    if not msg:
        logger.warning("Message %s not found, skipping", message_id)
        return

    if msg.get("status") != "queued":
        logger.info("Message %s status is %s, skipping", message_id, msg.get("status"))
        return

    # Fetch body from S3
    body_s3_key = msg.get("body_s3_key")
    if not body_s3_key:
        logger.error("Message %s has no body_s3_key", message_id)
        update_item(keys["PK"], keys["SK"], {
            "status": "failed",
            "error": "No body_s3_key",
            "updated_at": now_iso(),
        })
        return

    body_data = get_body(body_s3_key)

    # Build MIME message
    mime_msg = build_mime_message(msg, body_data)

    # Send via SES v2
    try:
        ses = boto3.client("sesv2")
        send_kwargs = {
            "Content": {
                "Raw": {
                    "Data": mime_msg.as_bytes(),
                },
            },
        }
        if SES_CONFIG_SET:
            send_kwargs["ConfigurationSetName"] = SES_CONFIG_SET

        resp = ses.send_email(**send_kwargs)
        ses_message_id = resp.get("MessageId", "")

        # Update message status to sent
        update_item(keys["PK"], keys["SK"], {
            "status": "sent",
            "ses_message_id": ses_message_id,
            "sent_at": now_iso(),
            "updated_at": now_iso(),
        })
        logger.info("Sent message %s, SES ID: %s", message_id, ses_message_id)

    except ses.exceptions.MessageRejected as e:
        logger.error("Message %s rejected by SES: %s", message_id, str(e))
        update_item(keys["PK"], keys["SK"], {
            "status": "failed",
            "error": str(e),
            "updated_at": now_iso(),
        })

    except Exception as e:
        logger.error("Failed to send message %s: %s", message_id, str(e))
        # Re-raise for SQS retry
        raise


def _from_address(msg: dict) -> tuple[str, str]:
    """Return (display_name, address) for the sender, normalizing legacy
    string-shaped from_addr records alongside the canonical object shape."""
    raw = msg.get("from_addr")
    if isinstance(raw, dict):
        return raw.get("name", ""), raw.get("address", "")
    if isinstance(raw, str):
        return "", raw
    return "", ""


def build_mime_message(msg: dict, body_data: dict) -> MIMEMultipart:
    """Build a MIME message from message record and body data."""
    mime = MIMEMultipart("alternative")

    from_name, from_address = _from_address(msg)

    # Stamp our own Message-ID so we can match it on inbound replies. Uses
    # the sender's actual domain so every platform domain threads correctly.
    _, sender_domain = split_address(from_address)
    if not sender_domain:
        sender_domain = DEFAULT_PLATFORM_DOMAIN
    message_id = msg.get("id", "")
    if message_id:
        mime["Message-ID"] = f"<{message_id}@{sender_domain}>"

    if from_address:
        mime["From"] = f"{from_name} <{from_address}>" if from_name else from_address

    mime["Subject"] = msg.get("subject", "")

    # Handle To addresses (list of {name, address} dicts)
    to_list = msg.get("to", [])
    to_addresses = []
    for recipient in to_list:
        if isinstance(recipient, dict):
            to_addresses.append(recipient.get("address", ""))
        else:
            to_addresses.append(str(recipient))
    mime["To"] = ", ".join(to_addresses)

    # CC addresses
    cc_list = msg.get("cc", [])
    if cc_list:
        cc_addresses = [r.get("address", "") if isinstance(r, dict) else str(r) for r in cc_list]
        mime["Cc"] = ", ".join(cc_addresses)

    # Optional headers
    headers = msg.get("headers", {})
    if isinstance(headers, dict):
        if headers.get("in_reply_to"):
            mime["In-Reply-To"] = headers["in_reply_to"]
        if headers.get("references"):
            mime["References"] = headers["references"]

    # Add body parts
    body_text = body_data.get("body_text")
    body_html = body_data.get("body_html")

    if body_text:
        mime.attach(MIMEText(body_text, "plain"))
    if body_html:
        mime.attach(MIMEText(body_html, "html"))

    # If neither, add empty text part
    if not body_text and not body_html:
        mime.attach(MIMEText("", "plain"))

    return mime
