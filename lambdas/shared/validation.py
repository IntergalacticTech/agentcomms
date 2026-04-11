"""Request validation utilities."""

import json


def parse_body(event: dict) -> dict:
    """Parse the request body from an API Gateway event.

    Handles both string and dict bodies.
    """
    body = event.get("body")
    if body is None:
        return {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return {}
    return body


def require_fields(body: dict, fields: list[str]) -> str | None:
    """Check that all required fields are present in the body.

    Returns an error message string if any field is missing, or None if all
    fields are present.
    """
    missing = [f for f in fields if f not in body or body[f] is None]
    if missing:
        return f"Missing required fields: {', '.join(missing)}"
    return None
