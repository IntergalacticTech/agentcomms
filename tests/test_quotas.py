"""Tests for quota enforcement."""

import json

import pytest

from shared.dynamo import get_item, put_item
from shared.models import org_keys
from shared.quotas import check_quota, decrement_usage, increment_usage


def _seed_org(org_id, quotas=None, usage=None):
    """Seed an org record with quotas and usage."""
    keys = org_keys(org_id)
    item = {
        **keys,
        "id": org_id,
        "name": f"Test Org {org_id}",
        "quotas": quotas or {},
        "usage": usage or {},
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    put_item(item)
    return item


def _make_event(method, org_id, body=None, path_params=None, path="/inboxes"):
    event = {
        "httpMethod": method,
        "path": path,
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


def test_quota_allows_under_limit(aws_env):
    """check_quota returns None when usage is under the limit."""
    org_id = "org_quota_01"
    _seed_org(org_id, quotas={"max_inboxes": 5}, usage={"inboxes": 3})

    result = check_quota(org_id, "inboxes")
    assert result is None


def test_quota_blocks_at_limit(aws_env):
    """check_quota returns a 403 error when usage equals the limit."""
    org_id = "org_quota_02"
    _seed_org(org_id, quotas={"max_inboxes": 5}, usage={"inboxes": 5})

    result = check_quota(org_id, "inboxes")
    assert result is not None
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"]["code"] == "QUOTA_EXCEEDED"


def test_quota_blocks_over_limit(aws_env):
    """check_quota returns a 403 error when usage exceeds the limit."""
    org_id = "org_quota_03"
    _seed_org(org_id, quotas={"max_inboxes": 5}, usage={"inboxes": 7})

    result = check_quota(org_id, "inboxes")
    assert result is not None
    assert result["statusCode"] == 403


def test_quota_unlimited_when_zero(aws_env):
    """check_quota returns None when max is 0 (unlimited)."""
    org_id = "org_quota_04"
    _seed_org(org_id, quotas={"max_inboxes": 0}, usage={"inboxes": 999})

    result = check_quota(org_id, "inboxes")
    assert result is None


def test_quota_allows_when_no_quota_field(aws_env):
    """check_quota returns None when the quota field is missing (defaults to 0 = unlimited)."""
    org_id = "org_quota_05"
    _seed_org(org_id, quotas={}, usage={"inboxes": 999})

    result = check_quota(org_id, "inboxes")
    assert result is None


def test_quota_no_org_allows(aws_env):
    """check_quota returns None (allows) when org record does not exist."""
    result = check_quota("nonexistent_org", "inboxes")
    assert result is None


def test_increment_usage(aws_env):
    """increment_usage increases the usage counter by 1."""
    org_id = "org_quota_06"
    _seed_org(org_id, quotas={"max_inboxes": 10}, usage={"inboxes": 3})

    increment_usage(org_id, "inboxes")

    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    assert org["usage"]["inboxes"] == 4


def test_decrement_usage(aws_env):
    """decrement_usage decreases the usage counter by 1."""
    org_id = "org_quota_07"
    _seed_org(org_id, quotas={"max_inboxes": 10}, usage={"inboxes": 3})

    decrement_usage(org_id, "inboxes")

    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    assert org["usage"]["inboxes"] == 2


def test_inbox_create_respects_quota(aws_env):
    """POST /inboxes returns 403 QUOTA_EXCEEDED when at limit."""
    from inboxes.handler import handler

    org_id = "org_quota_08"
    _seed_org(org_id, quotas={"max_inboxes": 2}, usage={"inboxes": 2})

    result = handler(
        _make_event("POST", org_id, body={"pod_id": "pod_001"}),
        None,
    )
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"]["code"] == "QUOTA_EXCEEDED"


def test_inbox_create_increments_usage(aws_env):
    """POST /inboxes increments usage on success."""
    from inboxes.handler import handler

    org_id = "org_quota_09"
    _seed_org(org_id, quotas={"max_inboxes": 5}, usage={"inboxes": 1})

    result = handler(
        _make_event("POST", org_id, body={"pod_id": "pod_001"}),
        None,
    )
    assert result["statusCode"] == 201

    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    assert org["usage"]["inboxes"] == 2


def test_inbox_delete_decrements_usage(aws_env):
    """DELETE /inboxes/{id} decrements usage."""
    from inboxes.handler import handler

    org_id = "org_quota_10"
    _seed_org(org_id, quotas={"max_inboxes": 5}, usage={"inboxes": 2})

    # Create an inbox first
    create_result = handler(
        _make_event("POST", org_id, body={"pod_id": "pod_001"}),
        None,
    )
    inbox_id = json.loads(create_result["body"])["id"]

    # Usage should be 3 after create
    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    assert org["usage"]["inboxes"] == 3

    # Delete
    handler(
        _make_event("DELETE", org_id, path_params={"id": inbox_id}),
        None,
    )

    org = get_item(keys["PK"], keys["SK"])
    assert org["usage"]["inboxes"] == 2


def test_pod_create_respects_quota(aws_env):
    """POST /pods returns 403 QUOTA_EXCEEDED when at limit."""
    from pods.handler import handler

    org_id = "org_quota_11"
    _seed_org(org_id, quotas={"max_pods": 3}, usage={"pods": 3})

    result = handler(
        _make_event("POST", org_id, body={"name": "Test Pod"}, path="/pods"),
        None,
    )
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"]["code"] == "QUOTA_EXCEEDED"


def test_domain_create_respects_quota(aws_env):
    """POST /domains returns 403 QUOTA_EXCEEDED when at limit."""
    from domains.handler import handler

    org_id = "org_quota_12"
    _seed_org(org_id, quotas={"max_domains": 1}, usage={"domains": 1})

    result = handler(
        _make_event("POST", org_id, body={"domain": "example.com"}, path="/domains"),
        None,
    )
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"]["code"] == "QUOTA_EXCEEDED"


def test_webhook_create_respects_quota(aws_env):
    """POST /webhooks returns 403 QUOTA_EXCEEDED when at limit."""
    from webhooks.handler import handler

    org_id = "org_quota_13"
    _seed_org(org_id, quotas={"max_webhooks": 5}, usage={"webhooks": 5})

    result = handler(
        _make_event(
            "POST", org_id,
            body={"url": "https://example.com/hook", "events": ["message.received"]},
            path="/webhooks",
        ),
        None,
    )
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"]["code"] == "QUOTA_EXCEEDED"


def test_api_key_create_respects_quota(aws_env):
    """POST /api-keys returns 403 QUOTA_EXCEEDED when at limit."""
    from api_keys.handler import handler

    org_id = "org_quota_14"
    _seed_org(org_id, quotas={"max_api_keys": 5}, usage={"api_keys": 5})

    result = handler(
        _make_event(
            "POST", org_id,
            body={"name": "test key", "scope": "org"},
            path="/api-keys",
        ),
        None,
    )
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["error"]["code"] == "QUOTA_EXCEEDED"
