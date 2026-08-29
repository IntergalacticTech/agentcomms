# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# adapters/slack/outbound.py
"""
Lambda consumer for the agentcomms-slack-outbound SQS queue.

Each SQS message body is a JSON-encoded OutboundMessage + channel_id.
The handler resolves the Channel, calls SlackAdapter.send(), and logs the result.
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import OutboundMessage
from core.data.repo import Repo
from adapters.slack.adapter import SlackAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = SlackAdapter()


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    )


def handler(event: dict, context) -> dict:
    """SQS event handler for outbound Slack messages."""
    table = _get_table()
    repo = Repo(table)
    processed = 0
    failed = 0

    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            agent_id = body.get("agent_id", "")
            channel_id = body.get("channel_id", "")
            channel_type = body.get("channel", "slack")

            channel = repo.get_channel(
                agent_id=agent_id,
                channel=channel_type,
                channel_id=channel_id,
            )
            if channel is None:
                logger.error("outbound: channel not found agent=%s channel_id=%s", agent_id, channel_id)
                failed += 1
                continue

            msg = OutboundMessage(
                to=body["to"],
                body_text=body.get("body_text", ""),
                body_html=body.get("body_html"),
                subject=body.get("subject"),
            )
            result = _adapter.send(channel=channel, message=msg)
            if result.status == "sent":
                processed += 1
            else:
                logger.error("outbound send failed: %s", result.error)
                failed += 1
        except Exception as e:
            logger.exception("Error processing outbound record: %s", e)
            failed += 1

    return {"processed": processed, "failed": failed}
