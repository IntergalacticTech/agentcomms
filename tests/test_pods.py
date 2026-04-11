"""Tests for the pods Lambda handler."""

import json

import pytest

from shared.dynamo import update_item
from shared.models import pod_keys


def _make_event(method, org_id, body=None, path_params=None):
    event = {
        "httpMethod": method,
        "path": "/pods",
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


def test_create_pod(aws_env):
    """Test creating a new pod."""
    from pods.handler import handler

    result = handler(_make_event("POST", "org_001", body={"name": "My Pod"}), None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["name"] == "My Pod"
    assert body["inbox_count"] == 0
    assert "id" in body


def test_list_pods(aws_env):
    """Test listing pods."""
    from pods.handler import handler

    org_id = "org_002"

    # Create pods
    handler(_make_event("POST", org_id, body={"name": "Pod A"}), None)
    handler(_make_event("POST", org_id, body={"name": "Pod B"}), None)

    result = handler(_make_event("GET", org_id), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["data"]) == 2


def test_delete_pod_empty(aws_env):
    """Test deleting a pod with no inboxes."""
    from pods.handler import handler

    org_id = "org_003"

    create_result = handler(_make_event("POST", org_id, body={"name": "Empty Pod"}), None)
    pod_id = json.loads(create_result["body"])["id"]

    delete_result = handler(
        _make_event("DELETE", org_id, path_params={"id": pod_id}), None
    )
    assert delete_result["statusCode"] == 204


def test_delete_pod_with_inboxes(aws_env):
    """Test that deleting a pod with inboxes fails."""
    from pods.handler import handler

    org_id = "org_004"

    create_result = handler(_make_event("POST", org_id, body={"name": "Full Pod"}), None)
    pod_id = json.loads(create_result["body"])["id"]

    # Simulate inboxes by updating inbox_count
    keys = pod_keys(org_id, pod_id)
    update_item(keys["PK"], keys["SK"], {"inbox_count": 3})

    delete_result = handler(
        _make_event("DELETE", org_id, path_params={"id": pod_id}), None
    )
    assert delete_result["statusCode"] == 400
    body = json.loads(delete_result["body"])
    assert "inboxes" in body["error"]["message"].lower()
