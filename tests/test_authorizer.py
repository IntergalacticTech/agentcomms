"""Tests for the authorizer Lambda handler."""

import hashlib
import json

import pytest

from shared.dynamo import put_item
from shared.models import api_key_gsi1, api_key_keys


@pytest.fixture
def valid_key_item(aws_env):
    """Create a valid API key in DynamoDB."""
    token = "am_live_testkey123456789"
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    key_id = "key_001"
    org_id = "org_001"

    item = {
        **api_key_keys(org_id, key_id),
        **api_key_gsi1(key_hash, key_id),
        "id": key_id,
        "key_id": key_id,
        "org_id": org_id,
        "name": "Test Key",
        "key_hash": key_hash,
        "scope": "org",
        "scope_resource_id": org_id,
        "status": "active",
    }
    put_item(item)
    return {"token": token, "org_id": org_id, "key_id": key_id}


@pytest.fixture
def revoked_key_item(aws_env):
    """Create a revoked API key in DynamoDB."""
    token = "am_live_revokedkey999"
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    key_id = "key_002"
    org_id = "org_001"

    item = {
        **api_key_keys(org_id, key_id),
        **api_key_gsi1(key_hash, key_id),
        "id": key_id,
        "key_id": key_id,
        "org_id": org_id,
        "name": "Revoked Key",
        "key_hash": key_hash,
        "scope": "org",
        "scope_resource_id": org_id,
        "status": "revoked",
    }
    put_item(item)
    return {"token": token}


def test_valid_key(valid_key_item):
    """Test that a valid API key returns an Allow policy."""
    from authorizer.handler import handler

    event = {
        "authorizationToken": valid_key_item["token"],
        "methodArn": "arn:aws:execute-api:us-east-1:123:api/*/GET/test",
    }

    result = handler(event, None)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert result["context"]["org_id"] == valid_key_item["org_id"]
    assert result["context"]["key_id"] == valid_key_item["key_id"]
    assert result["context"]["scope"] == "org"


def test_invalid_key(aws_env):
    """Test that an invalid token raises Unauthorized."""
    from authorizer.handler import handler

    event = {
        "authorizationToken": "am_live_nonexistent",
        "methodArn": "arn:aws:execute-api:us-east-1:123:api/*/GET/test",
    }

    with pytest.raises(Exception, match="Unauthorized"):
        handler(event, None)


def test_bearer_token(valid_key_item):
    """Test that Bearer token extraction works."""
    from authorizer.handler import handler

    event = {
        "authorizationToken": f"Bearer {valid_key_item['token']}",
        "methodArn": "arn:aws:execute-api:us-east-1:123:api/*/GET/test",
    }

    result = handler(event, None)

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert result["context"]["org_id"] == valid_key_item["org_id"]


def test_revoked_key(revoked_key_item):
    """Test that a revoked key raises Unauthorized."""
    from authorizer.handler import handler

    event = {
        "authorizationToken": revoked_key_item["token"],
        "methodArn": "arn:aws:execute-api:us-east-1:123:api/*/GET/test",
    }

    with pytest.raises(Exception, match="Unauthorized"):
        handler(event, None)
