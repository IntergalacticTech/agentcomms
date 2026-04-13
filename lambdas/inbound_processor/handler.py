"""Inbound Email Processor Lambda.

Processes emails received by SES -> stored in S3 -> invoked by SES rule.
"""

import email
import json
import logging
import os
from email.utils import parseaddr

from shared.dynamo import get_item, put_item, query, query_gsi, update_item, _get_table
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
from shared.webhook_publisher import publish_event

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

    # Parse threading headers
    in_reply_to = msg.get("In-Reply-To", "").strip()
    references = msg.get("References", "").strip()
    rfc_message_id = msg.get("Message-ID", "").strip()

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
            in_reply_to=in_reply_to,
            references=references,
            rfc_message_id=rfc_message_id,
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


def _extract_local_id(raw: str) -> str:
    """Extract the local part of a Message-ID header.

    Strips angle brackets and the @host suffix. For our outbound emails,
    the Message-ID header is '<{ulid}@victorymail.dev>', so this returns
    the message ULID.
    """
    if not raw:
        return ""
    raw = raw.strip().strip("<>")
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    return raw


def _find_thread_by_reply_headers(inbox_id: str, in_reply_to: str, references: str) -> dict | None:
    """Search for an existing thread by matching In-Reply-To or References headers.

    The reply's In-Reply-To header references a message we sent. AWS SES
    rewrites the Message-ID to <{ses_api_id}@email.amazonses.com>, so we
    match against the outbound message's ses_message_id field.

    Also handles:
    - Our own <{ulid}@victorymail.dev> format (direct message lookup)
    - headers.message_id for inbound-received messages whose Message-IDs
      were captured (multi-hop reply chains)
    """
    if not in_reply_to and not references:
        return None

    # Collect candidate IDs (raw RFC822 + extracted local part)
    candidate_local_ids = set()
    candidate_raw = set()
    if in_reply_to:
        candidate_raw.add(in_reply_to.strip())
        candidate_local_ids.add(_extract_local_id(in_reply_to))
    if references:
        for ref in references.split():
            ref = ref.strip()
            if ref:
                candidate_raw.add(ref)
                candidate_local_ids.add(_extract_local_id(ref))

    candidate_local_ids.discard("")

    if not candidate_raw and not candidate_local_ids:
        return None

    # Direct lookup by local id (our outbound message ulids)
    for local_id in candidate_local_ids:
        item = get_item(f"INBOX#{inbox_id}", f"MSG#{local_id}")
        if item:
            return item

    # Scan the inbox for matching messages (ses_message_id or headers.message_id)
    last_key = None
    while True:
        items, last_key = query(
            pk=f"INBOX#{inbox_id}",
            sk_prefix="MSG#",
            limit=100,
            exclusive_start_key=last_key,
        )
        for item in items:
            # Check ses_message_id (outbound messages we sent)
            ses_id = item.get("ses_message_id", "")
            if ses_id and ses_id in candidate_local_ids:
                logger.info("Thread match via ses_message_id %s", ses_id)
                return item

            # Check headers.message_id (inbound messages we received)
            headers = item.get("headers", {})
            if isinstance(headers, dict):
                msg_id = headers.get("message_id", "")
                if msg_id and (msg_id in candidate_raw or _extract_local_id(msg_id) in candidate_local_ids):
                    logger.info("Thread match via headers.message_id %s", msg_id)
                    return item
        if not last_key:
            break

    return None


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
    in_reply_to: str = "",
    references: str = "",
    rfc_message_id: str = "",
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

    # Generate message ID
    message_id = generate_ulid()
    timestamp = now_iso()

    # Check if this is a reply to an existing thread
    existing_thread_id = None
    matched_message = _find_thread_by_reply_headers(inbox_id, in_reply_to, references)
    if matched_message:
        existing_thread_id = matched_message.get("thread_id")
        logger.info(
            "Linked inbound message to existing thread %s via In-Reply-To/References",
            existing_thread_id,
        )

    thread_id = existing_thread_id or generate_ulid()

    # Store body in S3
    body_s3_key = store_body(
        org_id=org_id,
        inbox_id=inbox_id,
        message_id=message_id,
        body_text=body_text,
        body_html=body_html,
    )

    # Build snippet from body text
    snippet = ""
    if body_text:
        snippet = body_text[:200]

    # Build message item - use canonical field names that match the
    # outbound handler and SDK expectations
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
        "status": "received",
        "from_addr": {
            "name": from_name or "",
            "address": from_addr or source,
        },
        "to": [{"name": "", "address": dest_address}],
        "cc": [],
        "bcc": [],
        "reply_to": [],
        "subject": subject,
        "snippet": snippet,
        "body_s3_key": body_s3_key,
        "is_read": False,
        "is_starred": False,
        "is_spam": False,
        "is_trash": False,
        "labels": [],
        "category": None,
        "headers": {
            "message_id": rfc_message_id,
            "in_reply_to": in_reply_to,
            "references": references,
        },
        "has_attachments": len(attachment_parts) > 0,
        "attachment_count": len(attachment_parts),
        "ses_message_id": ses_message_id,
        "received_at": timestamp,
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
            "entity_type": "Attachment",
            "id": att_id,
            "message_id": message_id,
            "inbox_id": inbox_id,
            "org_id": org_id,
            "filename": att["filename"],
            "content_type": att["content_type"],
            "size": att["size"],
            "s3_bucket": ATTACHMENT_BUCKET,
            "s3_key": att_s3_key,
            "is_inline": False,
            "content_id": None,
            "created_at": timestamp,
        }
        put_item(att_item)

    if existing_thread_id:
        # Update existing thread: increment counts, update snippet and timestamp
        sender = from_addr or source
        thread_pk = f"INBOX#{inbox_id}"
        thread_sk = f"THREAD#{existing_thread_id}"
        table = _get_table()
        table.update_item(
            Key={"PK": thread_pk, "SK": thread_sk},
            UpdateExpression=(
                "SET message_count = if_not_exists(message_count, :zero) + :one, "
                "unread_count = if_not_exists(unread_count, :zero) + :one, "
                "snippet = :snippet, "
                "last_message_at = :now, "
                "updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":zero": 0,
                ":one": 1,
                ":snippet": snippet,
                ":now": timestamp,
            },
        )
    else:
        # Create new thread item
        sender_addr = from_addr or source
        thread_item = {
            **thread_keys(inbox_id, thread_id),
            **thread_gsi1(inbox_id, thread_id),
            "entity_type": "Thread",
            "id": thread_id,
            "inbox_id": inbox_id,
            "org_id": org_id,
            "subject": subject,
            "snippet": snippet,
            "message_count": 1,
            "unread_count": 1,
            "participants": [
                {"name": from_name or "", "address": sender_addr},
                {"name": "", "address": dest_address},
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

    # Publish webhook event
    try:
        publish_event("message.received", org_id, {
            "message_id": message_id,
            "inbox_id": inbox_id,
            "from": from_addr or source,
            "subject": subject,
            "received_at": timestamp,
        })
    except Exception:
        logger.exception("Failed to publish webhook event for message %s", message_id)
