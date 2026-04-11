"""S3 client helpers for email bodies and attachments."""

import json
import os

import boto3

BODY_BUCKET = os.environ.get("BODY_BUCKET", "victorymail-bodies")
ATTACHMENT_BUCKET = os.environ.get("ATTACHMENT_BUCKET", "victorymail-attachments")
EMAIL_BUCKET = os.environ.get("EMAIL_BUCKET", "victorymail-raw-email")

_s3 = None


def _get_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def store_body(
    org_id: str,
    inbox_id: str,
    message_id: str,
    body_text: str | None = None,
    body_html: str | None = None,
) -> str:
    """Store email body (text and/or HTML) in S3.

    Returns the S3 key.
    """
    s3_key = f"{org_id}/{inbox_id}/{message_id}/body.json"
    payload = {}
    if body_text is not None:
        payload["body_text"] = body_text
    if body_html is not None:
        payload["body_html"] = body_html

    _get_client().put_object(
        Bucket=BODY_BUCKET,
        Key=s3_key,
        Body=json.dumps(payload),
        ContentType="application/json",
    )
    return s3_key


def get_body(s3_key: str) -> dict:
    """Retrieve email body from S3.

    Returns dict with body_text and/or body_html.
    """
    resp = _get_client().get_object(Bucket=BODY_BUCKET, Key=s3_key)
    return json.loads(resp["Body"].read().decode("utf-8"))


def generate_attachment_presigned_url(s3_key: str, filename: str) -> str:
    """Generate a presigned URL for downloading an attachment (15 min expiry)."""
    return _get_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": ATTACHMENT_BUCKET,
            "Key": s3_key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=900,
    )
