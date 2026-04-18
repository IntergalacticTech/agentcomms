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
from typing import Any

import boto3

from core.adapters.base import (
    BridgeResult, BridgeStart, ChannelAdapter, HealthStatus, IngestPayload,
    OutboundMessage, ProvisionResult, SendResult,
)
from core.data.models import (
    Agent, Channel, ChannelType, MessageDirection, MessageStatus, Party,
    UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id

from adapters.email.normalize import parse_mime_bytes


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


class EmailAdapter(ChannelAdapter):
    channel_name = "email"
    supports_modes = ["provision"]

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

        msg = UnifiedMessage(
            message_id=new_id("msg"),
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
            body_text=parsed.body_text,
            body_html=parsed.body_html,
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
