"""Push notification Lambda handler.

Device-token registration and mobile push delivery via Amazon SNS Mobile Push.
Each registered device becomes an SNS platform endpoint; publishes fan out via
the endpoint ARN. First 1M publishes/month are free, then $0.50/M.

Registering a device requires that the caller's organization has a platform
application ARN configured for the target platform (iOS APNs or Android FCM).
Platform applications are provisioned out-of-band by FreeMail ops and stored
in SSM Parameter Store so each agent-app can share one.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

from shared.auth import get_org_id
from shared.dynamo import delete_item, get_item, put_item, query
from shared.models import (
    device_gsi1,
    device_keys,
    inbox_keys,
    now_iso,
)
from shared.response import bad_request, created, no_content, not_found, success
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Optional platform application ARNs from env vars. Ops sets these per
# stage after registering the app with APNs/FCM. If unset the register
# endpoint returns 503 so callers know push isn't wired up yet.
APNS_PLATFORM_APP_ARN = os.environ.get("APNS_PLATFORM_APP_ARN", "")
FCM_PLATFORM_APP_ARN = os.environ.get("FCM_PLATFORM_APP_ARN", "")

DEVICE_FIELDS = [
    "id", "inbox_id", "platform", "endpoint_arn", "enabled",
    "created_at", "updated_at",
]

_sns = None


def _get_sns():
    global _sns
    if _sns is None:
        _sns = boto3.client("sns")
    return _sns


def _filter_device(item: dict) -> dict:
    return {k: item[k] for k in DEVICE_FIELDS if k in item}


def _platform_arn(platform: str) -> str:
    if platform == "apns":
        return APNS_PLATFORM_APP_ARN
    if platform == "fcm":
        return FCM_PLATFORM_APP_ARN
    return ""


def _register_device(inbox_id: str, body: dict) -> dict:
    err = require_fields(body, ["platform", "token"])
    if err:
        return bad_request(err)
    platform = body["platform"].lower()
    token = body["token"]

    if platform not in ("apns", "fcm"):
        return bad_request("platform must be 'apns' or 'fcm'")

    platform_arn = _platform_arn(platform)
    if not platform_arn:
        return {
            "statusCode": 503,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": {
                    "code": "NOT_CONFIGURED",
                    "message": (
                        f"Push is not yet configured for platform '{platform}'. "
                        "Contact support to enable push notifications on your account."
                    ),
                }
            }),
        }

    try:
        resp = _get_sns().create_platform_endpoint(
            PlatformApplicationArn=platform_arn,
            Token=token,
            CustomUserData=inbox_id,
        )
        endpoint_arn = resp["EndpointArn"]
    except ClientError as e:
        logger.exception("create_platform_endpoint failed")
        return bad_request(f"SNS create_platform_endpoint failed: {e}")

    device_id = generate_ulid()
    now = now_iso()
    item = {
        **device_keys(inbox_id, device_id),
        **device_gsi1(inbox_id, device_id),
        "entity_type": "Device",
        "id": device_id,
        "inbox_id": inbox_id,
        "platform": platform,
        "endpoint_arn": endpoint_arn,
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return created(_filter_device(item))


def _list_devices(inbox_id: str) -> dict:
    items, _ = query(pk=f"INBOX#{inbox_id}", sk_prefix="DEVICE#", limit=100)
    return success({"data": [_filter_device(i) for i in items]})


def _delete_device(inbox_id: str, device_id: str) -> dict:
    keys = device_keys(inbox_id, device_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Device")
    # Best-effort delete the SNS endpoint too
    endpoint_arn = existing.get("endpoint_arn", "")
    if endpoint_arn:
        try:
            _get_sns().delete_endpoint(EndpointArn=endpoint_arn)
        except ClientError:
            logger.exception("delete_endpoint failed")
    delete_item(keys["PK"], keys["SK"])
    return no_content()


def _send_push(inbox_id: str, body: dict) -> dict:
    title = body.get("title", "")
    message = body.get("message", "")
    data = body.get("data", {}) or {}
    if not title and not message:
        return bad_request("title or message is required")

    items, _ = query(pk=f"INBOX#{inbox_id}", sk_prefix="DEVICE#", limit=100)
    if not items:
        return bad_request("No registered devices for this inbox")

    sent = 0
    failed = 0
    for device in items:
        if not device.get("enabled"):
            continue
        endpoint_arn = device.get("endpoint_arn", "")
        if not endpoint_arn:
            continue
        platform = device.get("platform", "")
        payload = _build_payload(platform, title, message, data)
        try:
            _get_sns().publish(
                TargetArn=endpoint_arn,
                Message=json.dumps(payload),
                MessageStructure="json",
            )
            sent += 1
        except ClientError:
            logger.exception("SNS publish failed for endpoint %s", endpoint_arn)
            failed += 1

    return success({"sent": sent, "failed": failed})


def _build_payload(platform: str, title: str, message: str, data: dict) -> dict:
    """Build SNS platform-specific JSON envelope."""
    if platform == "apns":
        apns = {
            "aps": {
                "alert": {"title": title, "body": message},
                "sound": "default",
            },
            "data": data,
        }
        return {
            "default": message,
            "APNS": json.dumps(apns),
            "APNS_SANDBOX": json.dumps(apns),
        }
    if platform == "fcm":
        fcm = {
            "notification": {"title": title, "body": message},
            "data": {k: str(v) for k, v in data.items()},
        }
        return {"default": message, "GCM": json.dumps(fcm)}
    return {"default": message}


def handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    params = event.get("pathParameters") or {}
    inbox_id = params.get("id", "")
    device_id = params.get("did", "")
    # get_org_id is called primarily for ACL enforcement elsewhere; we trust
    # the authorizer to pin inbox access.
    org_id = get_org_id(event)
    body = parse_body(event) if method in ("POST",) else {}

    if method == "POST" and path.endswith("/devices"):
        return _register_device(inbox_id, body)
    if method == "GET" and path.endswith("/devices"):
        return _list_devices(inbox_id)
    if method == "DELETE" and device_id:
        return _delete_device(inbox_id, device_id)
    if method == "POST" and path.endswith("/push"):
        return _send_push(inbox_id, body)
    return bad_request("Unknown route")
