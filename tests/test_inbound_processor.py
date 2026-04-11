"""Tests for inbound email processor Lambda."""

import json

from shared.dynamo import put_item, query
from shared.models import inbox_keys, inbox_gsi1, inbox_gsi2


def _make_raw_email():
    """Create a simple raw email bytes."""
    return (
        "From: sender@example.com\r\n"
        "To: test@victorymail.dev\r\n"
        "Subject: Hello World\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "This is a test email body.\r\n"
    ).encode("utf-8")


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
