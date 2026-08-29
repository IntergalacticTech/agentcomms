"""AI-powered email features Lambda handler (Starter tier and above)."""

import json

import boto3

from shared.auth import get_org_id
from shared.dynamo import get_item, update_item
from shared.models import org_keys, message_keys
from shared.response import success, bad_request, error
from shared.s3 import get_body
from shared.tiers import ai_enabled
from shared.validation import parse_body, require_fields

BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

_bedrock = None


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


def _check_ai_tier(org_id: str) -> dict | None:
    """Return an error response if the org's tier doesn't have AI, else None."""
    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return error("NOT_FOUND", "Organization not found.", 404)
    if not ai_enabled(org.get("tier", "free")):
        return error(
            "FORBIDDEN",
            "AI features require a Starter subscription or higher. Upgrade at https://console.victorymail.dev/billing",
            403,
        )
    return None


def _get_message_and_body(inbox_id: str, message_id: str) -> tuple[dict | None, str, str]:
    """Fetch message from DynamoDB and body from S3.

    Returns (error_response_or_None, subject, body_text).
    """
    keys = message_keys(inbox_id, message_id)
    msg = get_item(keys["PK"], keys["SK"])
    if not msg:
        return error("NOT_FOUND", "Message not found.", 404), "", ""

    subject = msg.get("subject", "")
    body_text = ""
    if msg.get("body_s3_key"):
        try:
            body_data = get_body(msg["body_s3_key"])
            body_text = body_data.get("body_text", "") or ""
        except Exception:
            pass

    return None, subject, body_text


def _invoke_bedrock(prompt: str, max_tokens: int = 256) -> str:
    """Call Bedrock Claude and return the text response."""
    response = _get_bedrock().invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"].strip()


def handle_categorize(event: dict) -> dict:
    """Categorize a message using Bedrock Claude."""
    org_id = get_org_id(event)
    tier_err = _check_ai_tier(org_id)
    if tier_err:
        return tier_err

    body = parse_body(event)
    err = require_fields(body, ["message_id", "inbox_id", "categories"])
    if err:
        return bad_request(err)

    message_id = body["message_id"]
    inbox_id = body["inbox_id"]
    categories = body["categories"]

    msg_err, subject, body_text = _get_message_and_body(inbox_id, message_id)
    if msg_err:
        return msg_err

    prompt = f"""Classify the following email into exactly one of these categories: {', '.join(categories)}

Subject: {subject}

Body:
{body_text[:2000]}

Respond with only the category name, nothing else."""

    raw = _invoke_bedrock(prompt, max_tokens=50)
    category = raw.lower()

    # Update message with category
    keys = message_keys(inbox_id, message_id)
    update_item(keys["PK"], keys["SK"], {"category": category})

    return success({"message_id": message_id, "category": category})


def handle_extract(event: dict) -> dict:
    """Extract structured data from a message using Bedrock Claude."""
    org_id = get_org_id(event)
    tier_err = _check_ai_tier(org_id)
    if tier_err:
        return tier_err

    body = parse_body(event)
    err = require_fields(body, ["message_id", "inbox_id", "schema"])
    if err:
        return bad_request(err)

    message_id = body["message_id"]
    inbox_id = body["inbox_id"]
    schema = body["schema"]

    msg_err, subject, body_text = _get_message_and_body(inbox_id, message_id)
    if msg_err:
        return msg_err

    schema_str = json.dumps(schema, indent=2)
    prompt = f"""Extract the following fields from this email. Return valid JSON matching this schema:

{schema_str}

If a field cannot be found, use null.

Subject: {subject}

Body:
{body_text[:3000]}

Respond with only the JSON object, nothing else."""

    raw = _invoke_bedrock(prompt, max_tokens=256)
    try:
        extracted = json.loads(raw)
    except json.JSONDecodeError:
        extracted = {"_raw": raw}

    return success({"message_id": message_id, "extracted": extracted})


def handle_summarize(event: dict) -> dict:
    """Summarize a message using Bedrock Claude."""
    org_id = get_org_id(event)
    tier_err = _check_ai_tier(org_id)
    if tier_err:
        return tier_err

    body = parse_body(event)
    err = require_fields(body, ["message_id", "inbox_id"])
    if err:
        return bad_request(err)

    message_id = body["message_id"]
    inbox_id = body["inbox_id"]

    msg_err, subject, body_text = _get_message_and_body(inbox_id, message_id)
    if msg_err:
        return msg_err

    prompt = f"""Summarize the following email in 2-3 sentences.

Subject: {subject}

Body:
{body_text[:3000]}

Respond with only the summary, nothing else."""

    summary = _invoke_bedrock(prompt, max_tokens=256)

    return success({"message_id": message_id, "summary": summary})


def handler(event, context):
    """Route AI requests."""
    path = event.get("path", "")
    if path.endswith("/categorize"):
        return handle_categorize(event)
    elif path.endswith("/extract"):
        return handle_extract(event)
    elif path.endswith("/summarize"):
        return handle_summarize(event)
    return bad_request("Not found")
