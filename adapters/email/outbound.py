# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/email/outbound.py
"""
Outbound SQS-triggered Lambda.

Core API writes {agent_id, channel_id, outbound_message_dict} to the outbound
SQS queue. This Lambda reads from the queue, loads the channel, calls
EmailAdapter.send(), and updates the stored UnifiedMessage with the SES
MessageId + status.
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import OutboundMessage
from core.data.models import ChannelType, MessageStatus
from core.data.repo import Repo
from adapters.email.adapter import EmailAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = EmailAdapter()


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ["AGENTCOMMS_TABLE"]
    )


def handler(event: dict, context) -> dict:
    repo = Repo(_get_table())
    processed = 0

    for record in event.get("Records", []):
        body = json.loads(record["body"])
        agent_id = body["agent_id"]
        channel_id = body["channel_id"]
        msg_id = body["message_id"]
        received_at_ms = body["received_at_ms"]
        outbound_dict = body["outbound_message"]

        channel = repo.get_channel(
            agent_id=agent_id,
            channel=ChannelType.EMAIL.value,
            channel_id=channel_id,
        )
        if channel is None:
            logger.error("channel %s/%s not found", agent_id, channel_id)
            continue

        result = _adapter.send(channel=channel, message=OutboundMessage(**outbound_dict))

        # Update the stored UnifiedMessage: status + external_id
        stored = repo.get_message(
            agent_id=agent_id, received_at_ms=received_at_ms, message_id=msg_id,
        )
        if stored:
            stored.status = MessageStatus.SENT if result.status == "sent" else MessageStatus.FAILED
            stored.external_id = result.channel_native_id or stored.external_id
            repo.put_message(stored)

        processed += 1
    return {"processed": processed}
