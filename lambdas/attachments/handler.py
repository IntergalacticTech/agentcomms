"""Attachments Lambda handler."""

from shared.auth import get_org_id
from shared.dynamo import get_item, query
from shared.models import attachment_keys
from shared.response import not_found, bad_request, success
from shared.s3 import generate_attachment_presigned_url

ATTACHMENT_LIST_FIELDS = [
    "id", "filename", "content_type", "size", "is_inline", "content_id", "created_at",
]


def _filter_attachment(item: dict) -> dict:
    return {k: item[k] for k in ATTACHMENT_LIST_FIELDS if k in item}


def _list_attachments(message_id: str) -> dict:
    """List all attachments for a message."""
    items, _ = query(
        pk=f"MSG#{message_id}",
        sk_prefix="ATTACH#",
        limit=100,
    )
    filtered = [_filter_attachment(i) for i in items]
    return success({"data": filtered})


def _get_attachment(message_id: str, attachment_id: str) -> dict:
    """Get a single attachment and redirect to presigned URL."""
    item = get_item(f"MSG#{message_id}", f"ATTACH#{attachment_id}")
    if not item:
        return not_found("Attachment")

    presigned_url = generate_attachment_presigned_url(item["s3_key"], item["filename"])
    return {
        "statusCode": 302,
        "headers": {
            "Location": presigned_url,
            "Access-Control-Allow-Origin": "*",
        },
    }


def handler(event, context):
    """Route attachment requests."""
    method = event.get("httpMethod", "")
    params = event.get("pathParameters") or {}
    message_id = params.get("mid", "")
    attachment_id = params.get("aid", "")

    if method != "GET":
        return bad_request("Unsupported method")

    if attachment_id:
        return _get_attachment(message_id, attachment_id)
    return _list_attachments(message_id)
