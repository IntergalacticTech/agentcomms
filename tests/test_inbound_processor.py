"""Tests for inbound email processor Lambda."""

import json

from shared.dynamo import put_item, query
from shared.models import inbox_keys, inbox_gsi1, inbox_gsi2, message_keys, message_gsi1, message_gsi3


def _make_raw_email(
    from_addr="sender@example.com",
    to_addr="test@victorymail.dev",
    subject="Hello World",
    body="This is a test email body.",
    in_reply_to="",
    references="",
):
    """Create a simple raw email bytes."""
    headers = (
        f"From: {from_addr}\r\n"
        f"To: {to_addr}\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
    )
    if in_reply_to:
        headers += f"In-Reply-To: {in_reply_to}\r\n"
    if references:
        headers += f"References: {references}\r\n"
    headers += f"\r\n{body}\r\n"
    return headers.encode("utf-8")


def _make_ses_event(message_id="test-ses-msg-001", destination=None):
    """Create an SES event structure."""
    if destination is None:
        destination = ["test@victorymail.dev"]
    return {
        "Records": [
            {
                "ses": {
                    "mail": {
                        "messageId": message_id,
                        "source": "sender@example.com",
                        "destination": destination,
                    },
                    "receipt": {
                        "action": {
                            "type": "S3",
                            "objectKeyPrefix": "inbound/",
                        }
                    },
                }
            }
        ]
    }


def test_inbound_processor_creates_message(aws_env):
    """Test that inbound processor creates a message in DynamoDB."""
    org_id = "org_01"
    inbox_id = "inbox_01"
    pod_id = "pod_01"

    # Seed inbox
    inbox_item = {
        **inbox_keys(org_id, inbox_id),
        **inbox_gsi1(pod_id, inbox_id),
        **inbox_gsi2("test@victorymail.dev", inbox_id),
        "entity_type": "inbox",
        "inbox_id": inbox_id,
        "org_id": org_id,
        "email": "test@victorymail.dev",
        "status": "active",
        "message_count": 0,
        "unread_count": 0,
    }
    put_item(inbox_item)

    # Put raw email in S3
    s3 = aws_env["s3"]
    s3.put_object(
        Bucket="victorymail-raw-email",
        Key="inbound/test-ses-msg-001",
        Body=_make_raw_email(),
    )

    # Call handler
    from inbound_processor.handler import handler

    event = _make_ses_event()
    handler(event, None)

    # Verify message was created
    messages, _ = query(pk=f"INBOX#{inbox_id}", sk_prefix="MSG#")
    assert len(messages) == 1

    msg = messages[0]
    assert msg["subject"] == "Hello World"
    assert msg["direction"] == "inbound"
    assert msg["from_address"] == "sender@example.com"
    assert msg["org_id"] == org_id
    assert msg["inbox_id"] == inbox_id

    # Verify thread was created
    threads, _ = query(pk=f"INBOX#{inbox_id}", sk_prefix="THREAD#")
    assert len(threads) == 1
    assert threads[0]["subject"] == "Hello World"

    # Verify inbox counts were updated
    from shared.dynamo import get_item

    updated_inbox = get_item(f"ORG#{org_id}", f"INBOX#{inbox_id}")
    assert updated_inbox["message_count"] == 1
    assert updated_inbox["unread_count"] == 1


def test_inbound_processor_skips_inactive_inbox(aws_env):
    """Test that inbound processor skips inactive inboxes."""
    org_id = "org_02"
    inbox_id = "inbox_02"
    pod_id = "pod_02"

    # Seed inactive inbox
    inbox_item = {
        **inbox_keys(org_id, inbox_id),
        **inbox_gsi1(pod_id, inbox_id),
        **inbox_gsi2("inactive@victorymail.dev", inbox_id),
        "entity_type": "inbox",
        "inbox_id": inbox_id,
        "org_id": org_id,
        "email": "inactive@victorymail.dev",
        "status": "disabled",
    }
    put_item(inbox_item)

    # Put raw email in S3
    s3 = aws_env["s3"]
    s3.put_object(
        Bucket="victorymail-raw-email",
        Key="inbound/test-ses-msg-002",
        Body=_make_raw_email(),
    )

    from inbound_processor.handler import handler

    event = _make_ses_event(
        message_id="test-ses-msg-002",
        destination=["inactive@victorymail.dev"],
    )
    handler(event, None)

    # Verify no message was created
    messages, _ = query(pk=f"INBOX#{inbox_id}", sk_prefix="MSG#")
    assert len(messages) == 0


def test_inbound_reply_links_to_existing_thread(aws_env):
    """Test that an inbound reply is linked to the existing thread via In-Reply-To."""
    org_id = "org_03"
    inbox_id = "inbox_03"
    pod_id = "pod_03"
    original_thread_id = "thread_orig_01"
    original_message_id = "msg_orig_01"
    original_rfc_message_id = "<original-123@victorymail.dev>"

    # Seed inbox
    inbox_item = {
        **inbox_keys(org_id, inbox_id),
        **inbox_gsi1(pod_id, inbox_id),
        **inbox_gsi2("reply-test@victorymail.dev", inbox_id),
        "entity_type": "inbox",
        "inbox_id": inbox_id,
        "org_id": org_id,
        "email": "reply-test@victorymail.dev",
        "status": "active",
        "message_count": 1,
        "unread_count": 0,
    }
    put_item(inbox_item)

    # Seed the original outbound message with headers.message_id
    from shared.models import now_iso, thread_keys, thread_gsi1

    ts = now_iso()
    orig_msg = {
        **message_keys(inbox_id, original_message_id),
        **message_gsi1(original_thread_id, original_message_id),
        **message_gsi3(org_id, original_message_id),
        "entity_type": "message",
        "message_id": original_message_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": original_thread_id,
        "direction": "outbound",
        "status": "sent",
        "subject": "Original Subject",
        "headers": {"message_id": original_rfc_message_id},
        "created_at": ts,
        "updated_at": ts,
    }
    put_item(orig_msg)

    # Seed the original thread
    thread_item = {
        **thread_keys(inbox_id, original_thread_id),
        **thread_gsi1(inbox_id, original_thread_id),
        "entity_type": "thread",
        "thread_id": original_thread_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "subject": "Original Subject",
        "snippet": "",
        "last_message_at": ts,
        "message_count": 1,
        "unread_count": 0,
        "created_at": ts,
        "updated_at": ts,
    }
    put_item(thread_item)

    # Create raw reply email with In-Reply-To header
    raw_reply = _make_raw_email(
        from_addr="replier@example.com",
        to_addr="reply-test@victorymail.dev",
        subject="Re: Original Subject",
        body="This is a reply.",
        in_reply_to=original_rfc_message_id,
    )

    # Put raw email in S3
    s3 = aws_env["s3"]
    s3.put_object(
        Bucket="victorymail-raw-email",
        Key="inbound/test-ses-msg-reply-001",
        Body=raw_reply,
    )

    from inbound_processor.handler import handler

    event = _make_ses_event(
        message_id="test-ses-msg-reply-001",
        destination=["reply-test@victorymail.dev"],
    )
    handler(event, None)

    # Verify the reply message was linked to the existing thread
    messages, _ = query(pk=f"INBOX#{inbox_id}", sk_prefix="MSG#")
    assert len(messages) == 2  # original + reply

    reply_msg = [m for m in messages if m["direction"] == "inbound"][0]
    assert reply_msg["thread_id"] == original_thread_id
    assert reply_msg["subject"] == "Re: Original Subject"

    # Verify NO new thread was created (still just 1 thread)
    threads, _ = query(pk=f"INBOX#{inbox_id}", sk_prefix="THREAD#")
    assert len(threads) == 1
    assert threads[0]["thread_id"] == original_thread_id

    # Verify thread was updated with new counts and snippet
    thread = threads[0]
    assert thread["message_count"] == 2
    assert "This is a reply." in thread["snippet"]


def test_inbound_no_reply_creates_new_thread(aws_env):
    """Test that an inbound email without In-Reply-To creates a new thread."""
    org_id = "org_04"
    inbox_id = "inbox_04"
    pod_id = "pod_04"

    # Seed inbox
    inbox_item = {
        **inbox_keys(org_id, inbox_id),
        **inbox_gsi1(pod_id, inbox_id),
        **inbox_gsi2("newthread@victorymail.dev", inbox_id),
        "entity_type": "inbox",
        "inbox_id": inbox_id,
        "org_id": org_id,
        "email": "newthread@victorymail.dev",
        "status": "active",
        "message_count": 0,
        "unread_count": 0,
    }
    put_item(inbox_item)

    # Put raw email in S3 (no In-Reply-To header)
    s3 = aws_env["s3"]
    s3.put_object(
        Bucket="victorymail-raw-email",
        Key="inbound/test-ses-msg-new-001",
        Body=_make_raw_email(
            to_addr="newthread@victorymail.dev",
            subject="Fresh Email",
            body="Brand new conversation.",
        ),
    )

    from inbound_processor.handler import handler

    event = _make_ses_event(
        message_id="test-ses-msg-new-001",
        destination=["newthread@victorymail.dev"],
    )
    handler(event, None)

    # Verify a new thread was created
    threads, _ = query(pk=f"INBOX#{inbox_id}", sk_prefix="THREAD#")
    assert len(threads) == 1
    assert threads[0]["subject"] == "Fresh Email"
    assert threads[0]["message_count"] == 1
