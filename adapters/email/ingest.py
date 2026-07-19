# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

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
from core.providers.aws.blob import S3BlobStore
from core.providers.aws.events import KinesisEventPublisher
from adapters.email.adapter import EmailAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = EmailAdapter()
_blob_store = None
_event_publisher = None


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ["AGENTCOMMS_TABLE"]
    )


def _get_blob_store():
    global _blob_store
    if _blob_store is None:
        _blob_store = S3BlobStore()
    return _blob_store


def _get_event_publisher():
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = KinesisEventPublisher()
    return _event_publisher


def _raw_email_keys(message_id: str) -> list[str]:
    prefix = os.environ.get("AGENTCOMMS_RAW_INBOUND_PREFIX", "inbound/").strip("/")
    if not prefix:
        return [message_id]
    prefixed = f"{prefix}/{message_id}"
    return [prefixed, message_id] if prefixed != message_id else [message_id]


def handler(event: dict, context) -> dict:
    """SES-SNS trigger. Each record contains an SES notification with a mail
    action that has already placed the raw MIME in S3."""
    repo = Repo(_get_table())
    blob_store = _get_blob_store()
    event_publisher = _get_event_publisher()
    processed = 0

    for record in event.get("Records", []):
        sns = record.get("Sns", {})
        message = json.loads(sns.get("Message", "{}"))
        # SES notification payload contains {mail: {...}, receipt: {...}}
        receipt = message.get("receipt", {})
        actions = receipt.get("action", {})
        # The SES S3 action stores raw MIME under AGENTCOMMS_RAW_INBOUND_PREFIX
        # using the SES messageId as the leaf key.
        bucket = os.environ.get("AGENTCOMMS_BUCKET_RAW_INBOUND")
        message_id = message.get("mail", {}).get("messageId")
        if not (bucket and message_id):
            logger.warning("no S3 pointer in SES notification; skipping")
            continue
        raw = None
        for key in _raw_email_keys(message_id):
            try:
                raw = blob_store.get_bytes(bucket=bucket, key=key)
                break
            except Exception as e:
                logger.info("failed to fetch raw MIME at %s: %s", key, e)
        if raw is None:
            logger.warning("raw MIME not found for SES message %s", message_id)
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
        msg_dict = json.loads(msg.model_dump_json(by_alias=True))
        event_publisher.publish(
            event_type="message.received",
            partition_key=msg.agent_id,
            data=msg_dict,
        )
        processed += 1

    return {"processed": processed}
