# SPDX-License-Identifier: FSL-1.1-Apache-2.0
"""Unit tests for EmailAdapter S3 offload and outbound threading headers."""
from __future__ import annotations

import email as email_lib
from unittest.mock import MagicMock, patch

import pytest

from core.adapters.base import OutboundMessage
from core.data.models import Channel, ChannelMode, ChannelStatus, ChannelType
from adapters.email.adapter import EmailAdapter
from adapters.email.normalize import ParsedAttachment, ParsedEmail


class FakeBlobStore:
    def __init__(self):
        self.puts = []

    def put_bytes(self, *, bucket, key, data, content_type=None):
        self.puts.append({"bucket": bucket, "key": key, "data": data, "ct": content_type})
        return key


def _parsed(body_text="hi", body_html=None, attachments=None) -> ParsedEmail:
    return ParsedEmail(
        from_address="sender@remote.example",
        from_display_name="Sender",
        to_addresses=["agent@bot.example.com"],
        subject="Subject",
        message_id_header="<mid@remote.example>",
        body_text=body_text,
        body_html=body_html,
        attachments=attachments or [],
    )


def test_large_body_offloaded_to_s3(monkeypatch):
    monkeypatch.setenv("AGENTCOMMS_BUCKET_BODIES", "bodies-bkt")
    monkeypatch.setenv("AGENTCOMMS_BUCKET_ATTACHMENTS", "att-bkt")
    blob = FakeBlobStore()
    adapter = EmailAdapter(blob_store=blob)

    big = "x" * (300 * 1024)
    parsed = _parsed(body_text=big, body_html="<p>" + big + "</p>")
    body_text, body_html, body_s3_key, attachments = adapter._offload_email(
        parsed=parsed, agent_id="agt_1", message_id="msg_1"
    )

    assert body_s3_key == "bodies/agt_1/msg_1.json"
    assert body_html is None
    assert len(body_text) <= 8 * 1024  # truncated preview
    assert any(p["bucket"] == "bodies-bkt" for p in blob.puts)


def test_small_body_stays_inline(monkeypatch):
    monkeypatch.setenv("AGENTCOMMS_BUCKET_BODIES", "bodies-bkt")
    monkeypatch.delenv("AGENTCOMMS_BUCKET_ATTACHMENTS", raising=False)
    blob = FakeBlobStore()
    adapter = EmailAdapter(blob_store=blob)

    parsed = _parsed(body_text="short", body_html="<p>short</p>")
    body_text, body_html, body_s3_key, attachments = adapter._offload_email(
        parsed=parsed, agent_id="a", message_id="m"
    )
    assert body_s3_key is None
    assert body_text == "short"
    assert body_html == "<p>short</p>"
    assert blob.puts == []


def test_attachments_offloaded_with_references(monkeypatch):
    monkeypatch.delenv("AGENTCOMMS_BUCKET_BODIES", raising=False)
    monkeypatch.setenv("AGENTCOMMS_BUCKET_ATTACHMENTS", "att-bkt")
    blob = FakeBlobStore()
    adapter = EmailAdapter(blob_store=blob)

    att = ParsedAttachment(
        filename="report.pdf", content_type="application/pdf", size=5, content=b"%PDF-"
    )
    parsed = _parsed(attachments=[att])
    _, _, _, attachments = adapter._offload_email(
        parsed=parsed, agent_id="agt_1", message_id="msg_1"
    )
    assert len(attachments) == 1
    a = attachments[0]
    assert a.filename == "report.pdf"
    assert a.s3_key.startswith("attachments/agt_1/msg_1/")
    assert a.s3_key.endswith("/report.pdf")
    assert len(blob.puts) == 1
    assert blob.puts[0]["bucket"] == "att-bkt"


def test_attachments_skipped_without_bucket(monkeypatch):
    # No attachments bucket configured → do not inline binary content.
    monkeypatch.delenv("AGENTCOMMS_BUCKET_BODIES", raising=False)
    monkeypatch.delenv("AGENTCOMMS_BUCKET_ATTACHMENTS", raising=False)
    blob = FakeBlobStore()
    adapter = EmailAdapter(blob_store=blob)
    att = ParsedAttachment(
        filename="a.bin", content_type="application/octet-stream", size=3, content=b"abc"
    )
    parsed = _parsed(attachments=[att])
    _, _, _, attachments = adapter._offload_email(
        parsed=parsed, agent_id="a", message_id="m"
    )
    assert attachments == []
    assert blob.puts == []


def _channel() -> Channel:
    return Channel(
        channel_id="chan_em_1",
        agent_id="agt_1",
        org_id="org_1",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        status=ChannelStatus.ACTIVE,
        config={"address": "agent@bot.example.com"},
    )


def _capture_raw_email(send_call_kwargs):
    raw = send_call_kwargs["RawMessage"]["Data"]
    if isinstance(raw, bytes):
        return email_lib.message_from_bytes(raw)
    return email_lib.message_from_string(raw)


def test_send_sets_threading_headers():
    fake_ses = MagicMock()
    fake_ses.send_raw_email.return_value = {"MessageId": "ses-1"}

    adapter = EmailAdapter()
    out = OutboundMessage(
        to="user@remote.example",
        body_text="reply body",
        subject="Re: Subject",
        thread_key="<parent-mid@remote.example>",
    )
    with patch("adapters.email.adapter.boto3.client", return_value=fake_ses):
        result = adapter.send(channel=_channel(), message=out)

    assert result.status == "sent"
    parsed = _capture_raw_email(fake_ses.send_raw_email.call_args.kwargs)
    assert parsed["In-Reply-To"] == "<parent-mid@remote.example>"
    assert "<parent-mid@remote.example>" in parsed["References"]
    msg_id = parsed["Message-ID"]
    assert msg_id and msg_id.startswith("<") and msg_id.endswith(">")
    assert "@bot.example.com>" in msg_id  # stable id anchored to sender domain


def test_send_message_id_override_and_references():
    fake_ses = MagicMock()
    fake_ses.send_raw_email.return_value = {"MessageId": "ses-2"}

    adapter = EmailAdapter()
    out = OutboundMessage(
        to="user@remote.example",
        body_text="body",
        channel_native_overrides={
            "message_id": "<custom@bot.example.com>",
            "in_reply_to": "<a@x>",
            "references": ["<a@x>", "<b@x>"],
        },
    )
    with patch("adapters.email.adapter.boto3.client", return_value=fake_ses):
        adapter.send(channel=_channel(), message=out)

    parsed = _capture_raw_email(fake_ses.send_raw_email.call_args.kwargs)
    assert parsed["Message-ID"] == "<custom@bot.example.com>"
    assert parsed["In-Reply-To"] == "<a@x>"
    assert parsed["References"] == "<a@x> <b@x>"
