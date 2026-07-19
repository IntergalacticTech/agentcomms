# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/email/adapter.py
"""
Email channel adapter for AgentComms.

Wraps SES (outbound via SendRawEmail) and SES Inbound (parsed by normalize.py).
Implements the ChannelAdapter contract.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from typing import Any

import boto3

from core.adapters.base import (
    BridgeResult, BridgeStart, ChannelAdapter, HealthStatus, IngestPayload,
    OutboundMessage, ProvisionResult, SendResult,
)
from core.data.models import (
    Agent, Attachment, Channel, ChannelType, MessageDirection, MessageStatus,
    Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id

from adapters.email.normalize import parse_mime_bytes

# Keep DynamoDB items well under the 400KB hard limit: bodies larger than this
# (or any parsed attachments) are offloaded to S3 and referenced by key.
_MAX_INLINE_BODY_BYTES = 256 * 1024
_BODY_PREVIEW_BYTES = 8 * 1024


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


class EmailAdapter(ChannelAdapter):
    channel_name = "email"
    supports_modes = ["provision"]

    def __init__(self, blob_store: Any = None):
        self._blob_store = blob_store

    def _get_blob_store(self):
        if self._blob_store is None:
            from core.providers.aws.blob import S3BlobStore
            self._blob_store = S3BlobStore()
        return self._blob_store

    # ── provision / teardown / health ──
    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult:
        ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        domain = config["domain"]
        local_part = config["local_part"]
        address = f"{local_part}@{domain}"

        # Ensure the domain is a verified identity (creates if absent).
        try:
            resp = ses.verify_domain_dkim(Domain=domain)
            dkim_tokens = resp["DkimTokens"]
        except Exception:
            dkim_tokens = []

        channel_id = new_id("chan", suffix="em")
        status = "pending_verification" if dkim_tokens else "active"
        return ProvisionResult(
            status=status,
            channel_id=channel_id,
            details={
                "address": address,
                "domain": domain,
                "dkim_tokens": dkim_tokens,
                "dkim_verified": False,
            },
        )

    def teardown(self, *, channel: Channel) -> None:
        # Releasing a per-agent email is low-impact: we don't delete SES domain
        # identity (shared across agents); we just mark the Channel disabled in
        # the repo. The core layer handles that — no SES call needed.
        return None

    def health_check(self, *, channel: Channel) -> HealthStatus:
        ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        try:
            ses.get_send_quota()
            return HealthStatus(
                ok=True,
                last_success_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            return HealthStatus(
                ok=False,
                last_success_at=datetime.now(timezone.utc).isoformat(),
                error=str(e),
            )

    # ── ingest (inbound) ──
    def _offload_email(
        self, *, parsed, agent_id: str, message_id: str
    ) -> tuple[str, str | None, str | None, list[Attachment]]:
        """Offload large bodies + parsed attachments to the provisioned S3
        buckets, returning (body_text, body_html, body_s3_key, attachments).

        Offloading is skipped (content kept inline) when the corresponding
        bucket env var is unset, preserving small-message behavior.
        """
        import json as _json

        bodies_bucket = os.environ.get("AGENTCOMMS_BUCKET_BODIES")
        attachments_bucket = os.environ.get("AGENTCOMMS_BUCKET_ATTACHMENTS")

        body_text = parsed.body_text or ""
        body_html = parsed.body_html
        body_s3_key: str | None = None

        body_bytes = len(body_text.encode("utf-8")) + len((body_html or "").encode("utf-8"))
        if bodies_bucket and body_bytes > _MAX_INLINE_BODY_BYTES:
            blob = _json.dumps({"body_text": body_text, "body_html": body_html}).encode("utf-8")
            key = f"bodies/{agent_id}/{message_id}.json"
            self._get_blob_store().put_bytes(
                bucket=bodies_bucket, key=key, data=blob, content_type="application/json",
            )
            body_s3_key = key
            # Keep a small inline preview; full content lives in S3 at body_s3_key.
            body_text = body_text[:_BODY_PREVIEW_BYTES]
            body_html = None

        attachments: list[Attachment] = []
        for att in parsed.attachments:
            if not attachments_bucket:
                # No bucket configured — cannot persist binary content; skip so
                # we never inline attachment bytes into the DynamoDB item.
                continue
            attachment_id = new_id("att")
            safe_name = (att.filename or "attachment").replace("/", "_").replace("\\", "_")
            key = f"attachments/{agent_id}/{message_id}/{attachment_id}/{safe_name}"
            self._get_blob_store().put_bytes(
                bucket=attachments_bucket, key=key, data=att.content,
                content_type=att.content_type,
            )
            attachments.append(Attachment(
                attachment_id=attachment_id,
                filename=safe_name,
                content_type=att.content_type,
                size=att.size,
                s3_key=key,
            ))
        return body_text, body_html, body_s3_key, attachments

    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None:
        raw = payload.body if isinstance(payload.body, bytes) else bytes(payload.body)
        parsed = parse_mime_bytes(raw)

        # Resolve which agent+channel this email is for by the recipient.
        repo = Repo(_get_table())
        target_channel: Channel | None = None
        for recipient in parsed.to_addresses:
            target_channel = repo.lookup_channel_by_address(
                channel="email", address=recipient,
            )
            if target_channel:
                break
        if target_channel is None:
            return None  # no agent owns this address → drop

        # Idempotency: if we've seen this Message-ID before, drop.
        if parsed.message_id_header:
            existing = repo.lookup_message_by_external_id(
                channel="email", external_id=parsed.message_id_header,
            )
            if existing:
                return None

        message_id = new_id("msg")
        body_text, body_html, body_s3_key, attachments = self._offload_email(
            parsed=parsed,
            agent_id=target_channel.agent_id,
            message_id=message_id,
        )

        msg = UnifiedMessage(
            message_id=message_id,
            agent_id=target_channel.agent_id,
            org_id=target_channel.org_id,
            channel_id=target_channel.channel_id,
            channel=ChannelType.EMAIL,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            **{"from": Party(
                address=parsed.from_address,
                display_name=parsed.from_display_name,
            )},
            to=[Party(address=a) for a in parsed.to_addresses],
            subject=parsed.subject or None,
            body_text=body_text,
            body_html=body_html,
            body_s3_key=body_s3_key,
            attachments=attachments,
            thread_key=None,  # thread resolution handled by core after persist
            is_dm=True,       # every email to an agent inbox is direct
            received_at=datetime.now(timezone.utc),
            channel_native={
                "message_id_header": parsed.message_id_header,
                "in_reply_to": parsed.in_reply_to,
                "references": parsed.references,
            },
            external_id=parsed.message_id_header,
        )
        return msg

    # ── send (outbound) ──
    def send(self, *, channel: Channel, message: OutboundMessage) -> SendResult:
        ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        from_address = channel.config["address"]
        to_address = message.to if isinstance(message.to, str) else message.to.get("address")

        if message.body_html:
            root = MIMEMultipart("alternative")
            root.attach(MIMEText(message.body_text, "plain", "utf-8"))
            root.attach(MIMEText(message.body_html, "html", "utf-8"))
        else:
            root = MIMEText(message.body_text, "plain", "utf-8")
        root["From"] = from_address
        root["To"] = to_address
        if message.subject:
            root["Subject"] = message.subject

        # Threading headers so replies stitch into the correct conversation.
        # Message-ID: always set a stable, RFC-compliant identifier for this
        # outbound message (unique per send, unless caller overrides).
        overrides = message.channel_native_overrides or {}
        domain = from_address.split("@", 1)[1] if "@" in from_address else None
        message_id = overrides.get("message_id") or make_msgid(domain=domain)
        root["Message-ID"] = message_id

        # In-Reply-To / References: derived from the thread the reply belongs to.
        # Prefer explicit overrides, else fall back to thread_key (the parent
        # Message-ID that core threads on).
        in_reply_to = overrides.get("in_reply_to") or message.thread_key
        references = overrides.get("references")
        if references is None:
            references = [in_reply_to] if in_reply_to else []
        elif isinstance(references, str):
            references = [references]
        if in_reply_to:
            root["In-Reply-To"] = in_reply_to
        if references:
            root["References"] = " ".join(str(r) for r in references)

        try:
            resp = ses.send_raw_email(
                Source=from_address,
                Destinations=[to_address],
                RawMessage={"Data": root.as_bytes()},
            )
            return SendResult(
                channel_native_id=resp["MessageId"],
                status="sent",
            )
        except Exception as e:
            return SendResult(
                channel_native_id="",
                status="failed",
                error=str(e),
            )
