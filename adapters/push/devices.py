# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# adapters/push/devices.py
"""
Device registration helpers for the Push channel adapter.

A Device represents a mobile device registered for push notifications.
Each device corresponds to one SNS Platform Endpoint under a Platform
Application belonging to the channel's parent Org.

Device registration is idempotent: re-registering the same token returns
the existing endpoint ARN (SNS create_platform_endpoint is naturally
idempotent — it returns the existing endpoint if the token is already
registered under the same Platform Application).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict

from core.data.models import Channel
from core.data.repo import Repo
from core.data.ulid_ import new_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Device(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    channel_id: str
    platform: str          # "apns" | "fcm"
    token: str
    endpoint_arn: str
    created_at: str

    def to_dynamodb_item(self) -> dict[str, Any]:
        return {
            "PK": f"CHAN#{self.channel_id}",
            "SK": f"DEV#{self.device_id}",
            "entity": "device",
            "device_id": self.device_id,
            "channel_id": self.channel_id,
            "platform": self.platform,
            "token": self.token,
            "endpoint_arn": self.endpoint_arn,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Device:
        return cls(
            device_id=item["device_id"],
            channel_id=item["channel_id"],
            platform=item["platform"],
            token=item["token"],
            endpoint_arn=item["endpoint_arn"],
            created_at=item["created_at"],
        )


def _sns_client():
    return boto3.client("sns", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def register_device(
    repo: Repo,
    channel: Channel,
    platform: str,
    token: str,
) -> Device:
    """Register (or retrieve) an SNS Platform Endpoint for a device token.

    Calls sns.create_platform_endpoint, which is idempotent: if the token is
    already registered under the Platform Application, the existing endpoint
    ARN is returned. Stores a Device item in DynamoDB under CHAN#{channel_id}.

    Args:
        repo: Repo instance backed by DynamoDB.
        channel: Channel model with config.platform_application_arns set.
        platform: "apns" or "fcm".
        token: The device push token string.

    Returns:
        Device model with endpoint_arn populated.

    Raises:
        ValueError: if the platform is not recognized.
        RuntimeError: if SNS create_platform_endpoint fails.
    """
    platform = platform.lower()
    if platform not in ("apns", "fcm"):
        raise ValueError(f"platform must be 'apns' or 'fcm', got: {platform!r}")

    arns = channel.config.get("platform_application_arns", {})
    app_arn = arns.get(platform, "")
    if not app_arn:
        raise RuntimeError(
            f"Channel {channel.channel_id} has no Platform Application ARN for {platform}"
        )

    sns = _sns_client()
    try:
        resp = sns.create_platform_endpoint(
            PlatformApplicationArn=app_arn,
            Token=token,
            CustomUserData=channel.channel_id,
        )
        endpoint_arn = resp["EndpointArn"]
    except ClientError as e:
        raise RuntimeError(f"create_platform_endpoint failed: {e}") from e

    # Check if a device with this endpoint_arn already exists (idempotency)
    existing_devices = list_devices(repo, channel)
    for dev in existing_devices:
        if dev.endpoint_arn == endpoint_arn:
            return dev

    device_id = new_id("dev")
    now = datetime.now(timezone.utc).isoformat()
    device = Device(
        device_id=device_id,
        channel_id=channel.channel_id,
        platform=platform,
        token=token,
        endpoint_arn=endpoint_arn,
        created_at=now,
    )
    repo.table.put_item(Item=device.to_dynamodb_item())
    return device


def list_devices(repo: Repo, channel: Channel) -> list[Device]:
    """List all devices registered under the given channel.

    DynamoDB Query: PK=CHAN#{channel_id}, SK begins_with DEV#
    """
    from boto3.dynamodb.conditions import Key

    resp = repo.table.query(
        KeyConditionExpression=Key("PK").eq(f"CHAN#{channel.channel_id}")
            & Key("SK").begins_with("DEV#"),
    )
    return [Device.from_dynamodb_item(item) for item in resp.get("Items", [])]


def delete_device(repo: Repo, channel: Channel, device_id: str) -> None:
    """Delete a device: removes SNS endpoint and DynamoDB item.

    Looks up the device, deletes the SNS endpoint (best-effort), then removes
    the DynamoDB item.

    Raises:
        KeyError: if the device is not found.
    """
    resp = repo.table.get_item(
        Key={"PK": f"CHAN#{channel.channel_id}", "SK": f"DEV#{device_id}"}
    )
    item = resp.get("Item")
    if not item:
        raise KeyError(f"Device {device_id} not found in channel {channel.channel_id}")

    device = Device.from_dynamodb_item(item)
    sns = _sns_client()
    try:
        sns.delete_endpoint(EndpointArn=device.endpoint_arn)
    except ClientError:
        logger.exception("delete_endpoint failed for %s", device.endpoint_arn)

    repo.table.delete_item(
        Key={"PK": f"CHAN#{channel.channel_id}", "SK": f"DEV#{device_id}"}
    )
