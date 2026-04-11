"""Tests for the API keys Lambda handler."""

import json

import pytest


def _make_event(method, org_id, body=None, path_params=None):
    event = {
        "httpMethod": method,
        "path": "/api-keys",
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
                "key_id": "key_001",
                "scope": "org",
                "scope_resource_id": org_id,
            }
        },
        "queryStringParameters": None,
        "pathParameters": path_params,
    }
    if body:
        event["body"] = json.dumps(body)
    return event


def test_create_api_key(aws_env):
    """Test creating a new API key."""
    from api_keys.handler import handler

    event = _make_event("POST", "org_001", body={
        "name": "My Key",
        "scope": "org",
    })

    result = handler(event, None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["name"] == "My Key"
    assert body["key"].startswith("am_live_")
    assert body["scope"] == "org"
    assert "id" in body


def test_list_api_keys(aws_env):
    """Test listing API keys."""
    from api_keys.handler import handler

    org_id = "org_002"

    # Create two keys
    for name in ("Key A", "Key B"):
        handler(_make_event("POST", org_id, body={
            "name": name,
            "scope": "org",
        }), None)

    # List
    result = handler(_make_event("GET", org_id), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["data"]) == 2
    # Should not include the key itself
    for item in body["data"]:
        assert "key" not in item
        assert "key_hash" not in item


def test_delete_api_key(aws_env):
    """Test deleting (revoking) an API key."""
    from api_keys.handler import handler

    org_id = "org_003"

    # Create a key
    create_result = handler(_make_event("POST", org_id, body={
        "name": "To Delete",
        "scope": "org",
    }), None)
    key_id = json.loads(create_result["body"])["id"]

    # Delete it
    delete_result = handler(
        _make_event("DELETE", org_id, path_params={"id": key_id}), None
    )
    assert delete_result["statusCode"] == 204

    # List should be empty (no active keys)
    list_result = handler(_make_event("GET", org_id), None)
    body = json.loads(list_result["body"])
    assert len(body["data"]) == 0
