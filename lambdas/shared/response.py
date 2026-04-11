"""API Gateway response builders with CORS headers."""

import json
from decimal import Decimal

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key",
    "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
}


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB."""

    def default(self, o):
        if isinstance(o, Decimal):
            if o % 1 == 0:
                return int(o)
            return float(o)
        return super().default(o)


def _response(body: dict | None, status_code: int) -> dict:
    resp = {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
    }
    if body is not None:
        resp["body"] = json.dumps(body, cls=DecimalEncoder)
    else:
        resp["body"] = ""
    return resp


def success(body: dict, status_code: int = 200) -> dict:
    return _response(body, status_code)


def created(body: dict) -> dict:
    return _response(body, 201)


def no_content() -> dict:
    return _response(None, 204)


def error(code: str, message: str, status_code: int = 400) -> dict:
    return _response({"error": {"code": code, "message": message}}, status_code)


def not_found(resource: str) -> dict:
    return error("NOT_FOUND", f"{resource} not found", 404)


def forbidden(message: str) -> dict:
    return error("FORBIDDEN", message, 403)


def bad_request(message: str) -> dict:
    return error("BAD_REQUEST", message, 400)


def validation_error(message: str) -> dict:
    return error("VALIDATION_ERROR", message, 422)
