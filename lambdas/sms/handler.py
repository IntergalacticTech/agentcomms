"""SMS outbound handler.

Sends outbound SMS via AWS End User Messaging v2 (sms-voice) using the
org's provisioned phone number. Requires that the org's 10DLC brand and
campaign have been registered — until then ``_get_origination_identity``
returns None and this endpoint returns 503 ``NOT_CONFIGURED``.

POST /inboxes/{id}/sms
    body: {"to": "+14155551234", "body": "Hello from your agent"}
"""

import logging
import os

import boto3
from botocore.exceptions import ClientError

from shared.abuse import check_send_rate, increment_send_counter, suspended_response
from shared.auth import get_org_id
from shared.dynamo import get_item, put_item
from shared.models import (
    inbox_keys,
    message_gsi1,
    message_gsi3,
    message_keys,
    now_iso,
    org_keys,
)
from shared.response import bad_request, created, error, not_found
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Shared 10DLC long code used as the origination identity until per-org
# numbers are wired up. Set via CDK env var once registration completes.
DEFAULT_ORIGINATION_NUMBER = os.environ.get("SMS_ORIGINATION_NUMBER", "")

_sms = None


def _get_sms_client():
    global _sms
    if _sms is None:
        _sms = boto3.client("pinpoint-sms-voice-v2")
    return _sms


def _get_origination_identity(inbox: dict) -> str:
    """Return the phone number the inbox should send from.

    Prefers a per-inbox number stored on the inbox record; falls back to
    the shared platform number if configured.
    """
    return inbox.get("phone_number") or DEFAULT_ORIGINATION_NUMBER


def _send_sms(event: dict) -> dict:
    org_id = get_org_id(event)
    params = event.get("pathParameters") or {}
    inbox_id = params.get("id", "")
    body = parse_body(event)

    err = require_fields(body, ["to", "body"])
    if err:
        return bad_request(err)

    destination = body["to"]
    message_body = body["body"]

    org = get_item(org_keys(org_id)["PK"], org_keys(org_id)["SK"])
    if org and org.get("status") == "suspended":
        return suspended_response()
    tier = (org or {}).get("tier", "free")

    rate_err = check_send_rate(org_id, tier)
    if rate_err:
        return rate_err

    from shared.models import inbox_keys as _ik
    keys = _ik(org_id, inbox_id)
    inbox = get_item(keys["PK"], keys["SK"])
    if not inbox:
        return not_found("Inbox")

    origination = _get_origination_identity(inbox)
    if not origination:
        return error(
            "NOT_CONFIGURED",
            "SMS is not yet enabled for this inbox. A platform phone number "
            "must be provisioned via 10DLC registration before sending.",
            503,
        )

    msg_id = generate_ulid()
    now = now_iso()
    thread_id = generate_ulid()

    try:
        resp = _get_sms_client().send_text_message(
            DestinationPhoneNumber=destination,
            OriginationIdentity=origination,
            MessageBody=message_body,
            MessageType="TRANSACTIONAL",
        )
        sms_message_id = resp.get("MessageId", "")
    except ClientError as e:
        logger.exception("send_text_message failed")
        return bad_request(f"SMS send failed: {e}")

    msg_item = {
        **message_keys(inbox_id, msg_id),
        **message_gsi1(thread_id, msg_id),
        **message_gsi3(org_id, msg_id),
        "entity_type": "Message",
        "id": msg_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "thread_id": thread_id,
        "direction": "outbound",
        "channel": "sms",
        "status": "sent",
        "from_addr": {"name": "", "address": origination},
        "to": [{"name": "", "address": destination}],
        "cc": [],
        "bcc": [],
        "subject": "",
        "snippet": message_body[:200],
        "body_text": message_body,
        "is_read": True,
        "labels": [],
        "has_attachments": False,
        "attachment_count": 0,
        "ses_message_id": sms_message_id,
        "sent_at": now,
        "created_at": now,
        "updated_at": now,
    }
    put_item(msg_item)
    increment_send_counter(org_id)

    return created({
        "id": msg_id,
        "inbox_id": inbox_id,
        "channel": "sms",
        "direction": "outbound",
        "from": origination,
        "to": destination,
        "body_text": message_body,
        "status": "sent",
        "sent_at": now,
    })


def handler(event, context):
    method = event.get("httpMethod", "")
    if method != "POST":
        return bad_request("Unknown route")
    return _send_sms(event)
