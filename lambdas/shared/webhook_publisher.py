"""Publish webhook events to the webhook SQS queue."""

import json
import os

import boto3

WEBHOOK_QUEUE_URL = os.environ.get("WEBHOOK_QUEUE_URL", "")


def publish_event(event_type: str, org_id: str, data: dict):
    """Send a webhook event to the webhook delivery queue.

    No-op if WEBHOOK_QUEUE_URL is not configured.
    """
    if not WEBHOOK_QUEUE_URL:
        return
    sqs = boto3.client("sqs")
    sqs.send_message(
        QueueUrl=WEBHOOK_QUEUE_URL,
        MessageBody=json.dumps({
            "event_type": event_type,
            "org_id": org_id,
            "data": data,
        }),
    )
