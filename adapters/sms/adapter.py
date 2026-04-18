# adapters/sms/adapter.py
"""
SMS channel adapter for AgentComms.

Uses AWS End User Messaging v2 (pinpoint-sms-voice-v2) for:
  - Provisioning 10DLC long-code phone numbers (provision / teardown)
  - Health-check via DescribePhoneNumbers
  - Inbound SMS routing (parse SNS → UnifiedMessage)
  - Outbound SMS sending (SendTextMessage)

Implements the ChannelAdapter contract from core/adapters/base.py.
"""
from __future__ import annotations

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
    Agent, Channel, ChannelType, MessageDirection, MessageStatus, Party,
    UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id

from adapters.sms.normalize import parse_sns_record

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _sms_client():
    return boto3.client(
        "pinpoint-sms-voice-v2",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


class SmsAdapter(ChannelAdapter):
    """AWS End User Messaging v2 SMS channel adapter."""

    channel_name = "sms"
    supports_modes = ["provision"]

    # ── provision / teardown / health ──

    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult:
        """Request a 10DLC long-code phone number via End User Messaging v2.

        Required config keys:
          - country (str, default "US"): ISO-3166 2-letter country code.

        Optional:
          - ten_dlc_brand_id (str): pre-registered brand ID.
          - ten_dlc_campaign_id (str): pre-registered campaign ID.

        Returns:
          channel_id, phone_e164, ten_dlc_status = "pending_brand_registration"
        """
        country = config.get("country", "US")
        brand_id = config.get(
            "ten_dlc_brand_id",
            os.environ.get("TEN_DLC_BRAND_ID", ""),
        )
        campaign_id = config.get(
            "ten_dlc_campaign_id",
            os.environ.get("TEN_DLC_CAMPAIGN_ID", ""),
        )

        client = _sms_client()
        kwargs: dict[str, Any] = {
            "IsoCountryCode": country,
            "MessageType": "TRANSACTIONAL",
            "NumberCapabilities": ["SMS"],
            "NumberType": "LONG_CODE",
        }

        try:
            resp = client.request_phone_number(**kwargs)
            phone_number_id = resp.get("PhoneNumberId", "")
            phone_number_arn = resp.get("PhoneNumberArn", "")
            phone_e164 = resp.get("PhoneNumber", "")
            status_raw = resp.get("Status", "PENDING")
        except ClientError as e:
            logger.exception("request_phone_number failed")
            raise RuntimeError(f"SMS provision failed: {e}") from e

        channel_id = new_id("chan", suffix="sm")
        return ProvisionResult(
            status="provisioning",
            channel_id=channel_id,
            details={
                "phone_e164": phone_e164,
                "phone_number_id": phone_number_id,
                "phone_number_arn": phone_number_arn,
                "ten_dlc_status": "pending_brand_registration",
                "ten_dlc_brand_id": brand_id,
                "ten_dlc_campaign_id": campaign_id,
                "aws_status": status_raw,
                "country": country,
            },
        )

    def teardown(self, *, channel: Channel) -> None:
        """Release the provisioned phone number back to AWS."""
        phone_number_id = channel.config.get("phone_number_id")
        if not phone_number_id:
            logger.warning(
                "teardown: channel %s has no phone_number_id; skipping release",
                channel.channel_id,
            )
            return None

        client = _sms_client()
        try:
            client.release_phone_number(PhoneNumberId=phone_number_id)
        except ClientError as e:
            # Log but don't raise — best-effort teardown
            logger.error("release_phone_number failed: %s", e)
        return None

    def health_check(self, *, channel: Channel) -> HealthStatus:
        """Verify the phone number is still active in End User Messaging."""
        phone_number_id = channel.config.get("phone_number_id")
        client = _sms_client()
        now = datetime.now(timezone.utc).isoformat()

        if not phone_number_id:
            return HealthStatus(
                ok=False,
                last_success_at=now,
                error="no phone_number_id in channel config",
            )

        try:
            resp = client.describe_phone_numbers(
                Filters=[{"Name": "phone-number-id", "Values": [phone_number_id]}]
            )
            numbers = resp.get("PhoneNumbers", [])
            if not numbers:
                return HealthStatus(
                    ok=False,
                    last_success_at=now,
                    error="phone number not found",
                )
            status = numbers[0].get("Status", "")
            if status == "ACTIVE":
                return HealthStatus(ok=True, last_success_at=now)
            return HealthStatus(
                ok=False,
                last_success_at=now,
                error=f"phone number status: {status}",
            )
        except ClientError as e:
            return HealthStatus(ok=False, last_success_at=now, error=str(e))

    # ── ingest (inbound) ──

    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None:
        """Parse SNS inbound-SMS JSON; route to the correct channel via GSI2.

        The payload.body must be either:
          - A dict with the raw SNS Records[] entry (already deserialized), or
          - A dict that IS the inner SMS payload (originationNumber, etc.)

        Returns None if no channel is registered for the destination phone.
        """
        body = payload.body
        if isinstance(body, bytes):
            import json as _json
            body = _json.loads(body)

        # If the payload is a full SNS event (has "Records"), take first record.
        # If it's already the inner SMS dict, use it directly.
        if "Records" in body:
            record = body["Records"][0]
            sms = parse_sns_record(record)
        elif "Sns" in body:
            sms = parse_sns_record(body)
        else:
            # Inner payload passed directly
            sms = parse_sns_record(body)

        if not sms.to_number:
            logger.warning("ingest: no destination number in payload")
            return None

        # Look up the channel by the destination phone number
        repo = Repo(_get_table())
        channel = repo.lookup_channel_by_address(
            channel="sms", address=sms.to_number,
        )
        if channel is None:
            logger.info("ingest: no channel for phone %s", sms.to_number)
            return None

        # Idempotency: if we already stored this inboundMessageId, drop.
        if sms.message_id:
            existing = repo.lookup_message_by_external_id(
                channel="sms", external_id=sms.message_id,
            )
            if existing:
                logger.info("ingest: duplicate message_id %s, skipping", sms.message_id)
                return None

        msg = UnifiedMessage(
            message_id=new_id("msg"),
            agent_id=channel.agent_id,
            org_id=channel.org_id,
            channel_id=channel.channel_id,
            channel=ChannelType.SMS,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            **{"from": Party(address=sms.from_number)},
            to=[Party(address=sms.to_number)],
            subject=None,
            body_text=sms.body,
            is_dm=True,  # every inbound SMS to an agent number is a DM
            received_at=datetime.now(timezone.utc),
            channel_native={
                "message_segments": sms.message_segments,
                "carrier_id": sms.carrier_id,
                "country": sms.country,
            },
            external_id=sms.message_id or None,
        )
        return msg

    # ── send (outbound) ──

    def send(self, *, channel: Channel, message: OutboundMessage) -> SendResult:
        """Send an outbound SMS via End User Messaging v2 SendTextMessage.

        channel.config must contain:
          - phone_number_arn (str): the origination identity ARN.
        message.to must be the E.164 destination phone number.
        """
        phone_number_arn = channel.config.get("phone_number_arn", "")
        to_address = (
            message.to if isinstance(message.to, str) else message.to.get("address", "")
        )

        client = _sms_client()
        try:
            resp = client.send_text_message(
                OriginationIdentity=phone_number_arn,
                DestinationPhoneNumber=to_address,
                MessageBody=message.body_text,
                MessageType="TRANSACTIONAL",
            )
            return SendResult(
                channel_native_id=resp.get("MessageId", ""),
                status="sent",
            )
        except ClientError as e:
            logger.exception("send_text_message failed")
            return SendResult(
                channel_native_id="",
                status="failed",
                error=str(e),
            )
