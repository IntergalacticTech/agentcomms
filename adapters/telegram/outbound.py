# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/telegram/outbound.py
"""
SQS Lambda consumer for async Telegram outbound sends.

Each SQS message contains:
  {
    "channel_id": "chan_tg_...",
    "agent_id":   "agt_...",
    "to":         "telegram:chat:12345",
    "body_text":  "Hello!",
    "body_html":  null,
    "thread_key": null
  }
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import OutboundMessage
from core.data.repo import Repo
from adapters.telegram.adapter import TelegramAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = TelegramAdapter()


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    )


def handler(event: dict, context) -> None:
    """SQS event handler for Telegram outbound sends."""
    repo = Repo(_get_table())
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            channel_id = body["channel_id"]
            agent_id = body["agent_id"]

            channel = repo.get_channel(
                agent_id=agent_id,
                channel="telegram",
                channel_id=channel_id,
            )
            if channel is None:
                logger.error("outbound: channel %s not found", channel_id)
                continue

            message = OutboundMessage(
                to=body["to"],
                body_text=body.get("body_text", ""),
                body_html=body.get("body_html"),
                subject=body.get("subject"),
                thread_key=body.get("thread_key"),
            )
            result = _adapter.send(channel=channel, message=message)
            logger.info("outbound send result: %s channel_native_id=%s", result.status, result.channel_native_id)
        except Exception as e:
            logger.exception("outbound worker failed for record: %s", e)
