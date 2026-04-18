# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/slack/ingest.py
"""
Lambda entry point for Slack Events API webhooks.

API Gateway POST /webhooks/slack/events → this handler.

Flow:
  1. If body is url_verification challenge, return challenge BEFORE signature check
     (Slack requires the response within 3 seconds, and sends no signature for verification).
  2. Verify X-Slack-Signature using signing secret from SSM.
  3. Parse event_callback, call SlackAdapter.ingest().
  4. Persist UnifiedMessage to DynamoDB + publish to Kinesis.
  5. Return 200 OK to Slack (required within 3s to avoid retries).
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import IngestPayload
from core.data.repo import Repo
from adapters.slack.adapter import SlackAdapter
from adapters.slack.signing import verify_slack_request
from adapters.slack.oauth import get_signing_secret

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = SlackAdapter()


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
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
    """API Gateway event handler for POST /webhooks/slack/events."""
    # Decode body
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64
        raw_body = base64.b64decode(raw_body)
    elif isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    # Parse JSON early to check for url_verification
    try:
        body_dict = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError):
        logger.error("Invalid JSON body")
        return {"statusCode": 400, "body": json.dumps({"error": "invalid json"})}

    # Step 1: url_verification BEFORE signature check (Slack requirement)
    if body_dict.get("type") == "url_verification":
        challenge = body_dict.get("challenge", "")
        logger.info("Slack url_verification challenge received")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"challenge": challenge}),
        }

    # Step 2: verify Slack signature
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")

    try:
        signing_secret = get_signing_secret()
    except Exception as e:
        logger.error("Failed to retrieve signing secret: %s", e)
        return {"statusCode": 500, "body": json.dumps({"error": "configuration error"})}

    if not verify_slack_request(signing_secret, timestamp, raw_body, signature):
        logger.warning("Slack signature verification failed")
        return {"statusCode": 401, "body": json.dumps({"error": "invalid signature"})}

    # Step 3: parse and ingest
    try:
        payload = IngestPayload(
            source="api_gateway",
            headers=dict(event.get("headers") or {}),
            body=raw_body,
            path_params=dict(event.get("pathParameters") or {}),
        )
        msg = _adapter.ingest(payload=payload)
    except Exception as e:
        logger.exception("SlackAdapter.ingest() raised: %s", e)
        # Still return 200 to prevent Slack retries
        return {"statusCode": 200, "body": json.dumps({"ok": True})}

    # Step 4: persist + publish
    if msg is not None:
        try:
            repo = Repo(_get_table())
            repo.put_message(msg)
            _publish_event(
                "message.received",
                json.loads(msg.model_dump_json(by_alias=True)),
            )
        except Exception as e:
            logger.exception("Failed to persist/publish Slack message: %s", e)

    # Step 5: respond 200 OK
    return {"statusCode": 200, "body": json.dumps({"ok": True})}
