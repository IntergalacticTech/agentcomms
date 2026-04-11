"""Tests for the Attachments Lambda handler."""

import json

from shared.dynamo import put_item
from shared.models import attachment_keys, now_iso
from attachments.handler import handler


ORG_ID = "org_test123"
INBOX_ID = "inbox_test456"
MESSAGE_ID = "msg_test789"


def _make_event(method, path="/", path_params=None, query_params=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params,
        "body": None,
        "requestContext": {
            "authorizer": {"org_id": ORG_ID},
        },
    }


def test_list_attachments(aws_env):
    """Test listing attachments for a message."""
    now = now_iso()
    att_id = "att_001"
    item = {
        **attachment_keys(MESSAGE_ID, att_id),
        "id": att_id,
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size": 12345,
        "is_inline": False,
        "content_id": "",
        "s3_key": f"{ORG_ID}/{INBOX_ID}/{MESSAGE_ID}/{att_id}",
        "created_at": now,
    }
    put_item(item)

    event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/messages/{MESSAGE_ID}/attachments",
        path_params={"id": INBOX_ID, "mid": MESSAGE_ID},
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["data"]) == 1
    att = body["data"][0]
    assert att["id"] == att_id
    assert att["filename"] == "report.pdf"
    assert att["content_type"] == "application/pdf"
    assert att["size"] == 12345


def test_get_attachment_redirect(aws_env):
    """Test getting an attachment returns a 302 redirect to presigned URL."""
    now = now_iso()
    att_id = "att_002"
    s3_key = f"{ORG_ID}/{INBOX_ID}/{MESSAGE_ID}/{att_id}"
    item = {
        **attachment_keys(MESSAGE_ID, att_id),
        "id": att_id,
        "filename": "photo.jpg",
        "content_type": "image/jpeg",
        "size": 54321,
        "is_inline": False,
        "content_id": "",
        "s3_key": s3_key,
        "created_at": now,
    }
    put_item(item)

    event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/messages/{MESSAGE_ID}/attachments/{att_id}",
        path_params={"id": INBOX_ID, "mid": MESSAGE_ID, "aid": att_id},
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 302
    assert "Location" in resp["headers"]
    location = resp["headers"]["Location"]
    assert "victorymail-attachments" in location
    assert "photo.jpg" in location
