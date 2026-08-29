# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# adapters/telegram/ingest.py
"""
Lambda entry point for Telegram Bot API webhooks.

API Gateway POST /webhooks/telegram/{token_hash} → this handler.

Flow:
  1. Extract token_hash from path params.
  2. Decode body.
  3. Build IngestPayload with headers (including X-Telegram-Bot-Api-Secret-Token).
  4. Call TelegramAdapter.ingest() — which authenticates + parses.
  5. If returns UnifiedMessage, persist to DynamoDB + publish to Kinesis.
  6. Respond 200 OK (always — Telegram retries on non-200).
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import IngestPayload
from core.data.repo import Repo
from core.providers.aws.events import KinesisEventPublisher
from adapters.telegram.adapter import TelegramAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = TelegramAdapter()
_event_publisher = None


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    )


def _get_event_publisher():
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = KinesisEventPublisher()
    return _event_publisher


def handler(event: dict, context) -> dict:
    """API Gateway event handler for POST /webhooks/telegram/{token_hash}."""
    # Decode body
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64
        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        body_dict = json.loads(raw_body) if raw_body else {}
    except (json.JSONDecodeError, ValueError):
        logger.error("Invalid JSON body from Telegram")
        return {"statusCode": 200, "body": json.dumps({"ok": True})}

    path_params = dict(event.get("pathParameters") or {})
    headers = dict(event.get("headers") or {})

    token_hash = path_params.get("token_hash", "")
    if not token_hash:
        logger.warning("telegram ingest: no token_hash in path")
        return {"statusCode": 200, "body": json.dumps({"ok": True})}

    try:
        payload = IngestPayload(
            source="api_gateway",
            headers=headers,
            body=body_dict,
            path_params=path_params,
        )
        msg = _adapter.ingest(payload=payload)
    except Exception as e:
        logger.exception("TelegramAdapter.ingest() raised: %s", e)
        return {"statusCode": 200, "body": json.dumps({"ok": True})}

    if msg is not None:
        try:
            repo = Repo(_get_table())
            repo.put_message(msg)
            _get_event_publisher().publish(
                event_type="message.received",
                partition_key=msg.agent_id,
                data=json.loads(msg.model_dump_json(by_alias=True)),
            )
        except Exception as e:
            logger.exception("Failed to persist/publish Telegram message: %s", e)

    return {"statusCode": 200, "body": json.dumps({"ok": True})}
