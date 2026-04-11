"""Tests for the Drafts Lambda handler."""

import json

from shared.dynamo import put_item
from shared.models import inbox_keys, inbox_gsi2, now_iso
from drafts.handler import handler


ORG_ID = "org_test123"
INBOX_ID = "inbox_test456"


def _seed_inbox(aws_env):
    """Seed a test inbox."""
    now = now_iso()
    put_item({
        **inbox_keys(ORG_ID, INBOX_ID),
        **inbox_gsi2("test@example.com", INBOX_ID),
        "id": INBOX_ID,
        "org_id": ORG_ID,
        "email": "test@example.com",
        "created_at": now,
    })


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


def test_create_draft(aws_env):
    """Test creating a new draft."""
    _seed_inbox(aws_env)

    event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/drafts",
        path_params={"id": INBOX_ID},
        body={
            "to": ["recipient@example.com"],
            "subject": "Draft Subject",
            "body_text": "Draft body content",
        },
    )
    resp = handler(event, None)
    assert resp["statusCode"] == 201

    data = json.loads(resp["body"])
    assert data["subject"] == "Draft Subject"
    assert data["to"] == ["recipient@example.com"]
    assert data["body_text"] == "Draft body content"
    assert data["inbox_id"] == INBOX_ID


def test_get_draft(aws_env):
    """Test getting a single draft."""
    _seed_inbox(aws_env)

    # Create a draft first
    create_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/drafts",
        path_params={"id": INBOX_ID},
        body={"subject": "Get This Draft", "body_text": "content"},
    )
    create_resp = handler(create_event, None)
    draft = json.loads(create_resp["body"])
    draft_id = draft["id"]

    # Get it
    get_event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/drafts/{draft_id}",
        path_params={"id": INBOX_ID, "did": draft_id},
    )
    resp = handler(get_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["subject"] == "Get This Draft"


def test_update_draft(aws_env):
    """Test updating a draft."""
    _seed_inbox(aws_env)

    create_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/drafts",
        path_params={"id": INBOX_ID},
        body={"subject": "Original", "body_text": "original body"},
    )
    create_resp = handler(create_event, None)
    draft = json.loads(create_resp["body"])
    draft_id = draft["id"]

    patch_event = _make_event(
        "PATCH",
        path=f"/inboxes/{INBOX_ID}/drafts/{draft_id}",
        path_params={"id": INBOX_ID, "did": draft_id},
        body={"subject": "Updated Subject", "body_text": "updated body"},
    )
    resp = handler(patch_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert data["subject"] == "Updated Subject"
    assert data["body_text"] == "updated body"


def test_delete_draft(aws_env):
    """Test hard deleting a draft."""
    _seed_inbox(aws_env)

    create_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/drafts",
        path_params={"id": INBOX_ID},
        body={"subject": "Delete Me", "body_text": "bye"},
    )
    create_resp = handler(create_event, None)
    draft = json.loads(create_resp["body"])
    draft_id = draft["id"]

    delete_event = _make_event(
        "DELETE",
        path=f"/inboxes/{INBOX_ID}/drafts/{draft_id}",
        path_params={"id": INBOX_ID, "did": draft_id},
    )
    resp = handler(delete_event, None)
    assert resp["statusCode"] == 204

    # Verify it's gone
    get_event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/drafts/{draft_id}",
        path_params={"id": INBOX_ID, "did": draft_id},
    )
    resp = handler(get_event, None)
    assert resp["statusCode"] == 404


def test_list_drafts(aws_env):
    """Test listing drafts."""
    _seed_inbox(aws_env)

    # Create two drafts
    for subj in ["Draft 1", "Draft 2"]:
        event = _make_event(
            "POST",
            path=f"/inboxes/{INBOX_ID}/drafts",
            path_params={"id": INBOX_ID},
            body={"subject": subj, "body_text": "content"},
        )
        handler(event, None)

    list_event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/drafts",
        path_params={"id": INBOX_ID},
    )
    resp = handler(list_event, None)
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    assert len(data["data"]) == 2


def test_send_draft(aws_env):
    """Test converting a draft to a sent message."""
    _seed_inbox(aws_env)

    create_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/drafts",
        path_params={"id": INBOX_ID},
        body={
            "to": ["recipient@example.com"],
            "subject": "Send This Draft",
            "body_text": "draft body to send",
        },
    )
    create_resp = handler(create_event, None)
    draft = json.loads(create_resp["body"])
    draft_id = draft["id"]

    send_event = _make_event(
        "POST",
        path=f"/inboxes/{INBOX_ID}/drafts/{draft_id}/send",
        path_params={"id": INBOX_ID, "did": draft_id},
    )
    resp = handler(send_event, None)
    assert resp["statusCode"] == 201

    data = json.loads(resp["body"])
    assert data["subject"] == "Send This Draft"
    assert data["direction"] == "outbound"

    # Draft should be deleted
    get_event = _make_event(
        "GET",
        path=f"/inboxes/{INBOX_ID}/drafts/{draft_id}",
        path_params={"id": INBOX_ID, "did": draft_id},
    )
    resp = handler(get_event, None)
    assert resp["statusCode"] == 404
