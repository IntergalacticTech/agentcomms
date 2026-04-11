"""Tests for the organizations Lambda handler."""

import json

import pytest

from shared.dynamo import put_item
from shared.models import now_iso, org_keys


def _make_event(org_id):
    return {
        "httpMethod": "GET",
        "path": "/organizations/me",
        "requestContext": {
            "authorizer": {
                "org_id": org_id,
                "key_id": "key_001",
                "scope": "org",
                "scope_resource_id": org_id,
            }
        },
    }


def test_get_org(aws_env):
    """Test getting an organization."""
    from organizations.handler import handler

    org_id = "org_test_001"
    now = now_iso()
    item = {
        **org_keys(org_id),
        "id": org_id,
        "name": "Test Org",
        "email": "test@example.com",
        "tier": "free",
        "status": "active",
        "settings": {},
        "quotas": {"max_inboxes": 5},
        "usage": {},
        "created_at": now,
        "updated_at": now,
    }
    put_item(item)

    result = handler(_make_event(org_id), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["id"] == org_id
    assert body["name"] == "Test Org"
    assert body["tier"] == "free"
    # Should not contain DynamoDB keys
    assert "PK" not in body
    assert "SK" not in body


def test_org_not_found(aws_env):
    """Test getting a non-existent organization."""
    from organizations.handler import handler

    result = handler(_make_event("org_nonexistent"), None)

    assert result["statusCode"] == 404
