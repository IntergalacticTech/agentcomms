"""Personas Lambda handler.

Persistent identity profiles an AI agent uses across sessions. Each persona
holds a consistent set of first/last name, date of birth, address, phone, and
free-form metadata so multi-turn interactions with external services present
as the same user every time.

POST /personas with ``{"generate": true}`` and no fields returns a plausible
generated profile via Bedrock Claude Haiku so agents can spin up a new identity
in one call.
"""

import json
import logging

import boto3

from shared.auth import get_org_id
from shared.dynamo import delete_item, get_item, put_item, query, update_item
from shared.models import now_iso, persona_gsi1, persona_keys
from shared.pagination import (
    decode_page_token,
    get_pagination_params,
    paginated_response,
)
from shared.response import bad_request, created, no_content, not_found, success
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

PERSONA_FIELDS = [
    "id", "label", "first_name", "last_name", "date_of_birth",
    "address_line_1", "address_line_2", "city", "state", "postal_code",
    "country", "phone", "email", "occupation", "bio", "metadata",
    "inbox_id", "created_at", "updated_at",
]

_bedrock = None


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


def _filter_persona(item: dict) -> dict:
    return {k: item[k] for k in PERSONA_FIELDS if k in item}


def _generate_persona_via_bedrock(hint: str | None = None) -> dict:
    """Ask Bedrock for a plausible persona JSON blob."""
    prompt_parts = [
        "Generate a plausible synthetic person for an AI agent to use as a "
        "persistent identity when interacting with online services. The "
        "person must NOT be a real human. Return JSON only, no prose.",
        "",
        "Schema:",
        '{',
        '  "first_name": string,',
        '  "last_name": string,',
        '  "date_of_birth": "YYYY-MM-DD",',
        '  "address_line_1": string,',
        '  "city": string,',
        '  "state": string,',
        '  "postal_code": string,',
        '  "country": "US",',
        '  "phone": "+1XXXXXXXXXX",',
        '  "occupation": string,',
        '  "bio": "2 sentence description"',
        '}',
    ]
    if hint:
        prompt_parts.extend(["", f"Hint: {hint}"])
    prompt = "\n".join(prompt_parts)

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = _get_bedrock().invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(body),
    )
    result = json.loads(resp["body"].read())
    text = result["content"][0]["text"].strip()
    # Strip code fences if Claude decided to wrap the JSON
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _list_personas(org_id: str, event: dict) -> dict:
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)
    items, last_key = query(
        pk=f"ORG#{org_id}",
        sk_prefix="PERSONA#",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )
    filtered = [_filter_persona(i) for i in items]
    return success(paginated_response(filtered, last_key))


def _get_persona(org_id: str, persona_id: str) -> dict:
    keys = persona_keys(org_id, persona_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Persona")
    return success(_filter_persona(item))


def _create_persona(org_id: str, body: dict) -> dict:
    should_generate = bool(body.get("generate"))
    if should_generate:
        try:
            generated = _generate_persona_via_bedrock(hint=body.get("hint"))
        except Exception as e:
            logger.exception("persona generation failed")
            return bad_request(f"Persona generation failed: {e}")
        for k, v in generated.items():
            body.setdefault(k, v)

    if not body.get("first_name") and not body.get("label"):
        return bad_request(
            "Persona must have at least a 'label' or 'first_name'. "
            "Pass 'generate': true to have one produced for you."
        )

    persona_id = generate_ulid()
    now = now_iso()
    label = body.get("label") or f"{body.get('first_name', '')} {body.get('last_name', '')}".strip()

    item = {
        **persona_keys(org_id, persona_id),
        **persona_gsi1(org_id, persona_id),
        "entity_type": "Persona",
        "id": persona_id,
        "org_id": org_id,
        "label": label,
        "first_name": body.get("first_name", ""),
        "last_name": body.get("last_name", ""),
        "date_of_birth": body.get("date_of_birth", ""),
        "address_line_1": body.get("address_line_1", ""),
        "address_line_2": body.get("address_line_2", ""),
        "city": body.get("city", ""),
        "state": body.get("state", ""),
        "postal_code": body.get("postal_code", ""),
        "country": body.get("country", "US"),
        "phone": body.get("phone", ""),
        "email": body.get("email", ""),
        "occupation": body.get("occupation", ""),
        "bio": body.get("bio", ""),
        "metadata": body.get("metadata", {}) or {},
        "inbox_id": body.get("inbox_id", ""),
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)
    return created(_filter_persona(item))


def _update_persona(org_id: str, persona_id: str, body: dict) -> dict:
    keys = persona_keys(org_id, persona_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Persona")

    allowed = {
        "label", "first_name", "last_name", "date_of_birth",
        "address_line_1", "address_line_2", "city", "state", "postal_code",
        "country", "phone", "email", "occupation", "bio", "metadata",
        "inbox_id",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return bad_request("No valid fields to update")
    updates["updated_at"] = now_iso()
    updated = update_item(keys["PK"], keys["SK"], updates)
    return success(_filter_persona(updated))


def _delete_persona(org_id: str, persona_id: str) -> dict:
    keys = persona_keys(org_id, persona_id)
    existing = get_item(keys["PK"], keys["SK"])
    if not existing:
        return not_found("Persona")
    delete_item(keys["PK"], keys["SK"])
    return no_content()


def handler(event, context):
    method = event.get("httpMethod", "")
    params = event.get("pathParameters") or {}
    persona_id = params.get("id", "")
    org_id = get_org_id(event)
    body = parse_body(event) if method in ("POST", "PATCH") else {}

    if method == "GET":
        if persona_id:
            return _get_persona(org_id, persona_id)
        return _list_personas(org_id, event)
    if method == "POST":
        return _create_persona(org_id, body)
    if method == "PATCH" and persona_id:
        return _update_persona(org_id, persona_id, body)
    if method == "DELETE" and persona_id:
        return _delete_persona(org_id, persona_id)
    return bad_request("Unknown route")
