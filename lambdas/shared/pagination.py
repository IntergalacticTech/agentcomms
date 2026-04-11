"""Cursor-based pagination utilities."""

import base64
import json


def encode_page_token(last_evaluated_key: dict | None) -> str | None:
    """Encode a DynamoDB LastEvaluatedKey as a base64 page token."""
    if not last_evaluated_key:
        return None
    return base64.urlsafe_b64encode(
        json.dumps(last_evaluated_key).encode()
    ).decode()


def decode_page_token(token: str | None) -> dict | None:
    """Decode a base64 page token back to a DynamoDB ExclusiveStartKey."""
    if not token:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(token.encode()))
    except (ValueError, json.JSONDecodeError):
        return None


def get_pagination_params(event: dict) -> tuple[int, str | None, bool]:
    """Extract pagination params from query string.

    Returns (limit, page_token, ascending).
    """
    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", "25"))
        limit = max(1, min(limit, 100))
    except (ValueError, TypeError):
        limit = 25

    page_token = params.get("page_token")
    ascending = params.get("order", "desc") != "desc"

    return limit, page_token, ascending


def paginated_response(items: list[dict], last_key: dict | None) -> dict:
    """Build a paginated response dict."""
    return {
        "data": items,
        "next_page_token": encode_page_token(last_key),
        "has_more": last_key is not None,
    }
