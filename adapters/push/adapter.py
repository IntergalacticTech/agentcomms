# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/push/adapter.py
"""
Push notification channel adapter for AgentComms.

Uses Amazon SNS Mobile Push for:
  - Provisioning: creates (or reuses) shared APNs + FCM Platform Applications
    at the Org level; stores ARN references in the Channel config.
  - Teardown: deletes device endpoints belonging to this channel; does NOT
    delete the shared Platform Applications.
  - Health check: verifies both Platform Application ARNs are reachable.
  - Ingest: parses SNS delivery receipts to update UnifiedMessage status.
  - Send: publishes to a device endpoint ARN via sns.Publish with
    platform-specific JSON envelope.

Push is asymmetric — all messages are DM (push is inherently direct to a
device). There is no "inbound" message from a user; "ingest" handles only
delivery receipts from SNS Mobile Push.

Device registration is a separate API surface implemented in devices.py.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from core.adapters.base import (
    ChannelAdapter, HealthStatus, IngestPayload, OutboundMessage,
    ProvisionResult, SendResult,
)
from core.data.models import (
    Agent, Channel, ChannelType, MessageStatus, UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _sns_client():
    return boto3.client("sns", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _build_apns_payload(title: str, body: str, badge: int | None = None) -> dict:
    aps: dict[str, Any] = {
        "alert": {"title": title, "body": body},
        "sound": "default",
    }
    if badge is not None:
        aps["badge"] = badge
    apns_inner = json.dumps({"aps": aps})
    return {
        "default": body,
        "APNS": apns_inner,
        "APNS_SANDBOX": apns_inner,
    }


def _build_fcm_payload(title: str, body: str) -> dict:
    fcm_inner = json.dumps({
        "notification": {"title": title, "body": body},
    })
    return {
        "default": body,
        "GCM": fcm_inner,
    }


class PushAdapter(ChannelAdapter):
    """SNS Mobile Push (APNs + FCM) channel adapter."""

    channel_name = "push"
    supports_modes = ["provision"]

    # ── provision / teardown / health ──────────────────────────────────────

    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult:
        """Ensure shared Org-level SNS Platform Applications exist and record ARNs.

        The shared APNs and FCM Platform Applications are created on first use.
        Subsequent provision calls for the same Org reuse the existing ARNs via
        SSM or passed config.

        Required config keys (provide at provisioning time or via env):
          - apns_platform_application_arn (str): existing ARN or "" to create.
          - fcm_platform_application_arn (str): existing ARN or "" to create.
          - apns_platform_credential (str): APNs private key PEM (for creation).
          - fcm_platform_credential (str): FCM server key / JSON (for creation).

        If ARNs are already supplied (non-empty), no AWS call is made.
        """
        sns = _sns_client()
        org_id = agent.org_id

        apns_arn = (
            config.get("apns_platform_application_arn")
            or os.environ.get("APNS_PLATFORM_APPLICATION_ARN", "")
        )
        fcm_arn = (
            config.get("fcm_platform_application_arn")
            or os.environ.get("FCM_PLATFORM_APPLICATION_ARN", "")
        )

        # Create APNs Platform Application if not yet present
        if not apns_arn:
            apns_cred = config.get("apns_platform_credential", "PLACEHOLDER")
            apns_principal = config.get("apns_platform_principal", "PLACEHOLDER")
            try:
                resp = sns.create_platform_application(
                    Name=f"agentcomms-apns-{org_id}",
                    Platform="APNS_SANDBOX",
                    Attributes={
                        "PlatformCredential": apns_cred,
                        "PlatformPrincipal": apns_principal,
                    },
                )
                apns_arn = resp["PlatformApplicationArn"]
                logger.info("Created APNs Platform Application: %s", apns_arn)
            except ClientError as e:
                logger.exception("create_platform_application (APNs) failed")
                raise RuntimeError(f"Push provision (APNs) failed: {e}") from e

        # Create FCM Platform Application if not yet present
        if not fcm_arn:
            fcm_cred = config.get("fcm_platform_credential", "PLACEHOLDER")
            try:
                resp = sns.create_platform_application(
                    Name=f"agentcomms-fcm-{org_id}",
                    Platform="GCM",
                    Attributes={
                        "PlatformCredential": fcm_cred,
                    },
                )
                fcm_arn = resp["PlatformApplicationArn"]
                logger.info("Created FCM Platform Application: %s", fcm_arn)
            except ClientError as e:
                logger.exception("create_platform_application (FCM) failed")
                raise RuntimeError(f"Push provision (FCM) failed: {e}") from e

        channel_id = new_id("chan", suffix="ps")
        return ProvisionResult(
            status="active",
            channel_id=channel_id,
            details={
                "platform_application_arns": {
                    "apns": apns_arn,
                    "fcm": fcm_arn,
                },
            },
        )

    def teardown(self, *, channel: Channel) -> None:
        """Delete all device endpoints registered under this channel.

        Does NOT delete the shared Platform Applications — those are Org-level
        resources managed separately.
        """
        arns = channel.config.get("platform_application_arns", {})
        sns = _sns_client()

        for platform, app_arn in arns.items():
            if not app_arn:
                continue
            try:
                paginator = sns.get_paginator("list_endpoints_by_platform_application")
                for page in paginator.paginate(PlatformApplicationArn=app_arn):
                    for ep in page.get("Endpoints", []):
                        ep_arn = ep.get("EndpointArn", "")
                        # Only delete endpoints whose CustomUserData matches our channel_id
                        attrs = ep.get("Attributes", {})
                        if attrs.get("CustomUserData") == channel.channel_id:
                            try:
                                sns.delete_endpoint(EndpointArn=ep_arn)
                                logger.info("Deleted endpoint %s for channel %s", ep_arn, channel.channel_id)
                            except ClientError:
                                logger.exception("delete_endpoint failed for %s", ep_arn)
            except ClientError:
                logger.exception("list_endpoints_by_platform_application failed for %s", app_arn)

    def health_check(self, *, channel: Channel) -> HealthStatus:
        """Verify both Platform Application ARNs respond to GetPlatformApplicationAttributes."""
        arns = channel.config.get("platform_application_arns", {})
        apns_arn = arns.get("apns", "")
        fcm_arn = arns.get("fcm", "")
        now = datetime.now(timezone.utc).isoformat()

        if not apns_arn or not fcm_arn:
            return HealthStatus(
                ok=False,
                last_success_at=now,
                error="missing platform_application_arns in channel config",
            )

        sns = _sns_client()
        for label, arn in [("apns", apns_arn), ("fcm", fcm_arn)]:
            try:
                sns.get_platform_application_attributes(PlatformApplicationArn=arn)
            except ClientError as e:
                return HealthStatus(ok=False, last_success_at=now, error=f"{label}: {e}")

        return HealthStatus(ok=True, last_success_at=now)

    # ── ingest (delivery receipts) ──────────────────────────────────────────

    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None:
        """Parse an SNS delivery-receipt notification and update message status.

        SNS Mobile Push publishes delivery receipts to a configured SNS topic.
        The receipt JSON contains 'notification.messageId' (our SNS publish
        MessageId) and a 'status' field (SUCCESSFUL / FAILED).

        We look up the matching UnifiedMessage via GSI6 (external_id =
        SNS MessageId) and update its status to delivered or failed.

        Returns the updated UnifiedMessage or None if the message was not found.
        """
        body = payload.body
        if isinstance(body, bytes):
            body = json.loads(body)

        # Unwrap SNS notification wrapper if present
        if "Message" in body and isinstance(body["Message"], str):
            try:
                body = json.loads(body["Message"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Extract fields from the delivery receipt
        notification = body.get("notification", {})
        sns_message_id = notification.get("messageId") or body.get("messageId", "")
        raw_status = (
            body.get("status")
            or notification.get("deliveryStatus", {}).get("providerResponse", "")
        ).upper()

        if not sns_message_id:
            logger.warning("ingest: delivery receipt missing messageId")
            return None

        new_status = (
            MessageStatus.DELIVERED if "SUCCESS" in raw_status
            else MessageStatus.FAILED
        )

        repo = Repo(_get_table())
        existing = repo.lookup_message_by_external_id(
            channel="push", external_id=sns_message_id,
        )
        if existing is None:
            logger.info(
                "ingest: no UnifiedMessage found for push messageId %s", sns_message_id
            )
            return None

        existing.status = new_status
        repo.put_message(existing)
        return existing

    # ── send (outbound) ─────────────────────────────────────────────────────

    def send(self, *, channel: Channel, message: OutboundMessage) -> SendResult:
        """Publish a push notification to a device endpoint ARN.

        message.to must be the device endpoint ARN prefixed with the platform:
          "push:apns:arn:aws:sns:us-east-1:123456789012:endpoint/APNS_SANDBOX/..."
          "push:fcm:arn:aws:sns:us-east-1:123456789012:endpoint/GCM/..."

        The method strips the "push:{platform}:" prefix, determines the payload
        envelope from the platform, and calls sns.Publish.

        channel_native_overrides may contain:
          - title (str): notification title
          - badge (int): APNs badge count
        """
        to_raw = (
            message.to if isinstance(message.to, str)
            else message.to.get("address", "")
        )

        # Determine platform from prefix
        platform = "apns"  # default
        endpoint_arn = to_raw
        if to_raw.startswith("push:apns:"):
            platform = "apns"
            endpoint_arn = to_raw[len("push:apns:"):]
        elif to_raw.startswith("push:fcm:"):
            platform = "fcm"
            endpoint_arn = to_raw[len("push:fcm:"):]

        overrides = message.channel_native_overrides or {}
        title = overrides.get("title") or message.subject or ""
        badge = overrides.get("badge")
        body_text = message.body_text

        if platform == "apns":
            sns_payload = _build_apns_payload(title, body_text, badge)
        else:
            sns_payload = _build_fcm_payload(title, body_text)

        sns = _sns_client()
        try:
            resp = sns.publish(
                TargetArn=endpoint_arn,
                Message=json.dumps(sns_payload),
                MessageStructure="json",
            )
            return SendResult(
                channel_native_id=resp.get("MessageId", ""),
                status="sent",
            )
        except ClientError as e:
            logger.exception("sns.Publish failed for endpoint %s", endpoint_arn)
            return SendResult(
                channel_native_id="",
                status="failed",
                error=str(e),
            )
