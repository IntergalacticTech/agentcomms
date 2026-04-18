# adapters/email/ingest.py
"""
Lambda entry point for inbound email.

SES deposits raw MIME to S3, then publishes an SNS event that triggers this
Lambda. We fetch the raw MIME from S3, run it through EmailAdapter.ingest(),
persist the UnifiedMessage, and publish message.received to Kinesis.
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import IngestPayload
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
    """SES-SNS trigger. Each record contains an SES notification with a mail
    action that has already placed the raw MIME in S3."""
    s3 = boto3.client("s3")
    repo = Repo(_get_table())
    processed = 0

    for record in event.get("Records", []):
        sns = record.get("Sns", {})
        message = json.loads(sns.get("Message", "{}"))
        # SES notification payload contains {mail: {...}, receipt: {...}}
        receipt = message.get("receipt", {})
        actions = receipt.get("action", {})
        # If configured via a LambdaAction preceded by S3Action, the raw MIME
        # is at the S3 object referenced by the SES messageId.
        bucket = os.environ.get("AGENTCOMMS_BUCKET_RAW_INBOUND")
        key = message.get("mail", {}).get("messageId")  # SES uses this as S3 key
        if not (bucket and key):
            logger.warning("no S3 pointer in SES notification; skipping")
            continue
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            raw = obj["Body"].read()
        except Exception as e:
            logger.exception("failed to fetch raw MIME: %s", e)
            continue

        payload = IngestPayload(
            source="sns",
            headers={k: v for k, v in sns.items() if isinstance(v, str)},
            body=raw,
            path_params={},
        )
        msg = _adapter.ingest(payload=payload)
        if msg is None:
            continue
        repo.put_message(msg)
        _publish_event("message.received", json.loads(msg.model_dump_json(by_alias=True)))
        processed += 1

    return {"processed": processed}
