"""Inbound Email Processor Lambda.

Processes emails received by SES -> stored in S3 -> invoked by SES rule.
"""

import email
import json
import logging
import os
from email.utils import parseaddr

from shared.dynamo import get_item, put_item, query_gsi, _get_table
from shared.models import (
    attachment_keys,
    message_gsi1,
    message_gsi3,
    message_gsi6,
    message_keys,
    now_iso,
    thread_gsi1,
    thread_keys,
)
from shared.s3 import store_body, _get_client, ATTACHMENT_BUCKET, EMAIL_BUCKET
from shared.ulid import generate_ulid

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point for SES inbound email processing."""
    for record in event.get("Records", []):
        try:
            process_ses_record(record)
        except Exception:
            logger.exception("Failed to process SES record")
            raise


def process_ses_record(record: dict) -> None:
    """Process a single SES event record."""
    ses_data = record["ses"]
    mail = ses_data["mail"]
    receipt = ses_data["receipt"]

    ses_message_id = mail["messageId"]
    source = mail.get("source", "")
    destinations = mail.get("destination", [])

    # Build S3 key and fetch raw email
    action = receipt.get("action", {})
    prefix = action.get("objectKeyPrefix", "inbound/")
    s3_key = f"{prefix}{ses_message_id}"

    raw_email = fetch_raw_email(s3_key)
    msg = email.message_from_bytes(raw_email)

    # Parse common headers
    from_name, from_addr = parseaddr(msg.get("From", ""))
    subject = msg.get("Subject", "(no subject)")

    # Extract body text and html
    body_text, body_html = extract_body(msg)

    # Extract attachments info
    attachment_parts = extract_attachments(msg)

    # Process for each destination
    for dest_address in destinations:
        process_destination(
            dest_address=dest_address,
            ses_message_id=ses_message_id,
            from_name=from_name,
            from_addr=from_addr,
            source=source,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachment_parts=attachment_parts,
        )


def fetch_raw_email(s3_key: str) -> bytes:
    """Fetch raw email bytes from S3."""
    s3 = _get_client()
    resp = s3.get_object(Bucket=EMAIL_BUCKET, Key=s3_key)
    return resp["Body"].read()


def extract_body(msg: email.message.Message) -> tuple:
    """Extract text and HTML body from email message."""
    body_text = None
    body_html = None

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                continue
            if content_type == "text/plain" and body_text is None:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode("utf-8", errors="replace")
            elif content_type == "text/html" and body_html is None:
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode("utf-8", errors="replace")
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            decoded = payload.decode("utf-8", errors="replace")
            if content_type == "text/html":
                body_html = decoded
            else:
                body_text = decoded

    return body_text, body_html


def extract_attachments(msg: email.message.Message) -> list:
    """Extract attachment parts from email."""
    attachments = []
    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in content_disposition or "inline" in content_disposition:
            filename = part.get_filename() or "unnamed"
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if payload:
                attachments.append({
                    "filename": filename,
                    "content_type": content_type,
                    "data": payload,
                    "size": len(payload),
                })
    return attachments


def process_destination(
    dest_address: str,
    ses_message_id: str,
    from_name: str,
    from_addr: str,
    source: str,
    subject: str,
    body_text: str | None,
    body_html: str | None,
    attachment_parts: list,
) -> None:
    """Process inbound email for a single destination address."""
    # Look up inbox by email address
    items, _ = query_gsi("GSI2", f"EMAIL#{dest_address}", limit=1)
    if not items:
        logger.info("No inbox found for %s, skipping", dest_address)
        return

    inbox = items[0]
    if inbox.get("status") != "active":
        logger.info("Inbox for %s is not active, skipping", dest_address)
        return

    inbox_id = inbox["SK"].replace("INBOX#", "")
    org_id = inbox["PK"].replace("ORG#", "")

    # Generate IDs
    message_id = generate_ulid()
    thread_id = generate_ulid()
    timestamp = now_iso()

    # Store body in S3
    body_s3_key = store_body(
        org_id=org_id,
        inbox_id=inbox_id,
        message_id=message_id,
        body_text=body_text,
        body_html=body_html,
    )

    # Build message item
    msg_item = {
        **message_keys(inbox_id, message_id),
        **message_gsi1(thread_id, message_id),
        **message_gsi3(org_id, message_id),
        "entity_type": "message",
        "message_id": message_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": thread_id,
        "direction": "inbound",
        "status": "received",
        "from_address": from_addr or source,
        "from_name": from_name,
        "to_addresses": [dest_address],
        "subject": subject,
        "body_s3_key": body_s3_key,
        "has_attachments": len(attachment_parts) > 0,
        "attachment_count": len(attachment_parts),
        "ses_message_id": ses_message_id,
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    # Add GSI6 for SES message ID lookup
    if ses_message_id:
        msg_item.update(message_gsi6(ses_message_id, message_id))

    put_item(msg_item)

    # Process attachments
    for att in attachment_parts:
        att_id = generate_ulid()
        att_s3_key = f"{org_id}/{inbox_id}/{message_id}/{att_id}/{att['filename']}"

        # Upload to attachments bucket
        s3 = _get_client()
        s3.put_object(
            Bucket=ATTACHMENT_BUCKET,
            Key=att_s3_key,
            Body=att["data"],
            ContentType=att["content_type"],
        )

        att_item = {
            **attachment_keys(message_id, att_id),
            "entity_type": "attachment",
            "attachment_id": att_id,
            "message_id": message_id,
            "filename": att["filename"],
            "content_type": att["content_type"],
            "size": att["size"],
            "s3_key": att_s3_key,
            "created_at": timestamp,
        }
        put_item(att_item)

    # Create thread item
    thread_item = {
        **thread_keys(inbox_id, thread_id),
        **thread_gsi1(inbox_id, thread_id),
        "entity_type": "thread",
        "thread_id": thread_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "subject": subject,
        "last_message_at": timestamp,
        "message_count": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    put_item(thread_item)

    # Update inbox counts
    table = _get_table()
    table.update_item(
        Key={"PK": f"ORG#{org_id}", "SK": f"INBOX#{inbox_id}"},
        UpdateExpression="SET message_count = if_not_exists(message_count, :zero) + :one, "
                         "unread_count = if_not_exists(unread_count, :zero) + :one, "
                         "updated_at = :now",
        ExpressionAttributeValues={
            ":zero": 0,
            ":one": 1,
            ":now": timestamp,
        },
    )

    logger.info("Processed inbound message %s for inbox %s", message_id, inbox_id)
