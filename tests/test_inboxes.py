"""Tests for the inboxes Lambda handler."""

import json

import pytest


def _make_event(method, org_id, body=None, path_params=None, query_params=None):
    event = {
        "httpMethod": method,
        "path": "/inboxes",
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
                "key_id": "key_001",
                "scope": "org",
                "scope_resource_id": org_id,
            }
        },
        "queryStringParameters": query_params,
        "pathParameters": path_params,
    }
    if body:
        event["body"] = json.dumps(body)
    return event


def test_create_inbox_auto_email(aws_env):
    """Test creating an inbox with auto-generated email."""
    from inboxes.handler import handler

    result = handler(_make_event("POST", "org_001", body={"pod_id": "pod_001"}), None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["email"].endswith("@victorymail.dev")
    assert len(body["email"].split("@")[0]) == 12
    assert body["status"] == "active"
    assert "id" in body


def test_create_inbox_custom_email(aws_env):
    """Test creating an inbox with a custom email."""
    from inboxes.handler import handler

    result = handler(_make_event("POST", "org_002", body={
        "pod_id": "pod_001",
        "email": "hello@victorymail.dev",
        "display_name": "Hello Inbox",
    }), None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["email"] == "hello@victorymail.dev"
    assert body["display_name"] == "Hello Inbox"


def test_get_inbox(aws_env):
    """Test getting an inbox by id."""
    from inboxes.handler import handler

    org_id = "org_003"

    # Create
    create_result = handler(_make_event("POST", org_id, body={"pod_id": "pod_001"}), None)
    inbox_id = json.loads(create_result["body"])["id"]

    # Get
    result = handler(
        _make_event("GET", org_id, path_params={"id": inbox_id}), None
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["id"] == inbox_id
    assert body["status"] == "active"
    # Should not contain DynamoDB keys
    assert "PK" not in body
    assert "SK" not in body


def test_delete_inbox(aws_env):
    """Test soft deleting an inbox."""
    from inboxes.handler import handler

    org_id = "org_004"

    # Create
    create_result = handler(_make_event("POST", org_id, body={"pod_id": "pod_001"}), None)
    inbox_id = json.loads(create_result["body"])["id"]

    # Delete
    delete_result = handler(
        _make_event("DELETE", org_id, path_params={"id": inbox_id}), None
    )
    assert delete_result["statusCode"] == 204

    # Get should return 404 (soft deleted)
    get_result = handler(
        _make_event("GET", org_id, path_params={"id": inbox_id}), None
    )
    assert get_result["statusCode"] == 404
