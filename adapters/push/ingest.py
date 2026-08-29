# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# adapters/push/ingest.py
"""
Lambda entry point for push delivery receipts.

SNS Mobile Push publishes delivery receipts to an SNS topic when a notification
is delivered (or fails) to an APNs/FCM endpoint. This Lambda is subscribed to
'agentcomms-push-delivery'. It parses the receipt via PushAdapter.ingest() and
updates the previously-stored UnifiedMessage status in DynamoDB.

Operator setup:
  - In the SNS Platform Application settings, set the "Delivery status logging"
    SNS topic to 'agentcomms-push-delivery' (created by PushAdapterStack).
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import IngestPayload
from core.data.repo import Repo
from adapters.push.adapter import PushAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = PushAdapter()


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ["AGENTCOMMS_TABLE"]
    )


def handler(event: dict, context) -> dict:
    """SNS trigger from agentcomms-push-delivery topic.

    Each Records[] entry is an SNS notification whose Message contains the
    SNS Mobile Push delivery receipt payload as JSON.
    """
    processed = 0

    for record in event.get("Records", []):
        try:
            sns = record.get("Sns", {})
            raw_message = sns.get("Message", "{}")
            receipt = json.loads(raw_message) if isinstance(raw_message, str) else raw_message

            payload = IngestPayload(
                source="sns",
                headers={k: v for k, v in sns.items() if isinstance(v, str)},
                body=receipt,
                path_params={},
            )
            msg = _adapter.ingest(payload=payload)
            if msg is None:
                logger.info("Delivery receipt did not match any stored message")
                continue
            processed += 1
        except Exception:
            logger.exception("Failed to process push delivery receipt")
            raise

    return {"processed": processed}
