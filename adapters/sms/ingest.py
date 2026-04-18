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
from adapters.sms.adapter import SmsAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = SmsAdapter()


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ["AGENTCOMMS_TABLE"]
    )


def _publish_event(event_type: str, msg_dict: dict) -> None:
    stream = os.environ.get("AGENTCOMMS_EVENT_STREAM")
    if not stream:
        return
    kinesis = boto3.client("kinesis")
    kinesis.put_record(
        StreamName=stream,
        PartitionKey=msg_dict["agent_id"],
        Data=json.dumps({"type": event_type, "data": msg_dict}).encode("utf-8"),
    )


def handler(event: dict, context) -> dict:
    """SNS trigger from agentcomms-sms-inbound topic.

    Each Records[] entry is an SNS notification whose Message contains the
    End User Messaging inbound SMS payload as JSON.
    """
    repo = Repo(_get_table())
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
            _publish_event("message.received", json.loads(msg.model_dump_json(by_alias=True)))
            processed += 1
        except Exception:
            logger.exception("Failed to process SMS record")
            raise

    return {"processed": processed}
