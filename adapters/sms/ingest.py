# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/sms/ingest.py
"""
Lambda entry point for inbound SMS.

AWS End User Messaging publishes inbound SMS events to an SNS topic. This Lambda
is subscribed to that topic, parses the payload via SmsAdapter.ingest(), persists
the UnifiedMessage to DynamoDB, and publishes message.received to Kinesis.

Operator setup: configure End User Messaging to publish inbound SMS to the
'agentcomms-sms-inbound' SNS topic created by SmsAdapterStack.
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import IngestPayload
from core.data.repo import Repo
from core.providers.aws.events import KinesisEventPublisher
from adapters.sms.adapter import SmsAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = SmsAdapter()
_event_publisher = None


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ["AGENTCOMMS_TABLE"]
    )


def _get_event_publisher():
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = KinesisEventPublisher()
    return _event_publisher


def handler(event: dict, context) -> dict:
    """SNS trigger from agentcomms-sms-inbound topic.

    Each Records[] entry is an SNS notification whose Message contains the
    End User Messaging inbound SMS payload as JSON.
    """
    repo = Repo(_get_table())
    event_publisher = _get_event_publisher()
    processed = 0

    for record in event.get("Records", []):
        try:
            sns = record.get("Sns", {})
            raw_message = sns.get("Message", "{}")
            # Parse inner SMS JSON so we can pass the full SNS record to the adapter
            sms_payload = json.loads(raw_message) if isinstance(raw_message, str) else raw_message

            payload = IngestPayload(
                source="sns",
                headers={k: v for k, v in sns.items() if isinstance(v, str)},
                body=sms_payload,
                path_params={},
            )
            msg = _adapter.ingest(payload=payload)
            if msg is None:
                continue
            repo.put_message(msg)
            event_publisher.publish(
                event_type="message.received",
                partition_key=msg.agent_id,
                data=json.loads(msg.model_dump_json(by_alias=True)),
            )
            processed += 1
        except Exception:
            logger.exception("Failed to process SMS record")
            raise

    return {"processed": processed}
