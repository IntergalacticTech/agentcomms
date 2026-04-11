"""Tests for the Lists Lambda handler."""

import json

from shared.dynamo import put_item, get_item
from shared.models import list_keys, list_member_keys, list_gsi1, now_iso
from lists.handler import handler


ORG_ID = "org_test123"


def _make_event(method, path="/", path_params=None, body=None, query_params=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {"org_id": ORG_ID},
        },
    }


def test_create_list(aws_env):
    """Test creating a new mailing list with members."""
    event = _make_event(
        "POST",
        path="/lists",
        body={
            "name": "Newsletter Subscribers",
            "inbox_id": "inbox_001",
            "members": [
                {"address": "alice@example.com", "name": "Alice"},
                {"address": "bob@example.com", "name": "Bob"},
            ],
        },
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["name"] == "Newsletter Subscribers"
    assert body["inbox_id"] == "inbox_001"
    assert body["member_count"] == 2
    assert len(body["members"]) == 2
    addresses = {m["address"] for m in body["members"]}
    assert "alice@example.com" in addresses
    assert "bob@example.com" in addresses


def test_get_list_with_members(aws_env):
    """Test getting a list returns its members."""
    list_id = "list_test001"
    now = now_iso()

    # Seed the list
    list_item = {
        **list_keys(ORG_ID, list_id),
        **list_gsi1(ORG_ID, list_id),
        "id": list_id,
        "name": "Test List",
        "inbox_id": "inbox_001",
        "org_id": ORG_ID,
        "member_count": 2,
        "created_at": now,
        "updated_at": now,
    }
    put_item(list_item)

    # Seed members
    for addr, name in [("carol@example.com", "Carol"), ("dave@example.com", "Dave")]:
        member_item = {
            **list_member_keys(list_id, addr),
            "address": addr,
            "name": name,
            "subscribed_at": now,
        }
        put_item(member_item)

    event = _make_event(
        "GET",
        path=f"/lists/{list_id}",
        path_params={"id": list_id},
    )

    resp = handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["id"] == list_id
    assert body["name"] == "Test List"
    assert len(body["members"]) == 2
    addresses = {m["address"] for m in body["members"]}
    assert "carol@example.com" in addresses
    assert "dave@example.com" in addresses


def test_delete_list(aws_env):
    """Test deleting a list removes it and its members."""
    # Create a list first
    create_event = _make_event(
        "POST",
        path="/lists",
        body={
            "name": "To Delete",
            "inbox_id": "inbox_002",
            "members": [
                {"address": "ephemeral@example.com", "name": "Ephemeral"},
            ],
        },
    )
    create_resp = handler(create_event, None)
    assert create_resp["statusCode"] == 201
    created_body = json.loads(create_resp["body"])
    list_id = created_body["id"]

    # Delete it
    delete_event = _make_event(
        "DELETE",
        path=f"/lists/{list_id}",
        path_params={"id": list_id},
    )
    delete_resp = handler(delete_event, None)
    assert delete_resp["statusCode"] == 204

    # Verify it's gone
    keys = list_keys(ORG_ID, list_id)
    assert get_item(keys["PK"], keys["SK"]) is None
