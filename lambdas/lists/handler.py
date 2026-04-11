"""Mailing Lists Lambda handler."""

import json

from shared.auth import get_org_id
from shared.dynamo import get_item, put_item, delete_item, query, query_gsi, update_item
from shared.models import list_keys, list_member_keys, list_gsi1, now_iso
from shared.pagination import get_pagination_params, decode_page_token, paginated_response
from shared.response import success, created, no_content, bad_request, not_found
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

LIST_FIELDS = ["id", "name", "inbox_id", "member_count", "created_at", "updated_at"]
MEMBER_FIELDS = ["address", "name", "subscribed_at"]


def _filter_list(item: dict) -> dict:
    return {k: item[k] for k in LIST_FIELDS if k in item}


def _filter_member(item: dict) -> dict:
    return {k: item[k] for k in MEMBER_FIELDS if k in item}


def _list_lists(org_id: str, event: dict) -> dict:
    """List all mailing lists for the org."""
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)

    items, last_key = query_gsi(
        index_name="GSI1",
        pk_value=f"ORG#{org_id}#LISTS",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )
    filtered = [_filter_list(i) for i in items]
    return success(paginated_response(filtered, last_key))


def _get_list(org_id: str, list_id: str, event: dict) -> dict:
    """Get a single list with paginated members."""
    keys = list_keys(org_id, list_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("List")

    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)

    members, last_key = query(
        pk=f"LIST#{list_id}",
        sk_prefix="MEMBER#",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )

    result = _filter_list(item)
    result["members"] = [_filter_member(m) for m in members]
    if last_key:
        from shared.pagination import encode_page_token
        result["next_page_token"] = encode_page_token(last_key)
        result["has_more"] = True
    else:
        result["has_more"] = False

    return success(result)


def _create_list(org_id: str, body: dict) -> dict:
    """Create a new mailing list."""
    err = require_fields(body, ["name", "inbox_id"])
    if err:
        return bad_request(err)

    list_id = generate_ulid()
    now = now_iso()
    members = body.get("members", [])

    list_item = {
        **list_keys(org_id, list_id),
        **list_gsi1(org_id, list_id),
        "id": list_id,
        "name": body["name"],
        "inbox_id": body["inbox_id"],
        "org_id": org_id,
        "member_count": len(members),
        "created_at": now,
        "updated_at": now,
    }
    put_item(list_item)

    for member in members:
        member_item = {
            **list_member_keys(list_id, member["address"]),
            "address": member["address"],
            "name": member.get("name", ""),
            "subscribed_at": now,
        }
        put_item(member_item)

    result = _filter_list(list_item)
    result["members"] = [
        {"address": m["address"], "name": m.get("name", ""), "subscribed_at": now}
        for m in members
    ]
    return created(result)


def _add_members(org_id: str, list_id: str, body: dict) -> dict:
    """Add members to an existing list."""
    keys = list_keys(org_id, list_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("List")

    members = body.get("members", [])
    if not members:
        return bad_request("members array is required")

    now = now_iso()
    for member in members:
        member_item = {
            **list_member_keys(list_id, member["address"]),
            "address": member["address"],
            "name": member.get("name", ""),
            "subscribed_at": now,
        }
        put_item(member_item)

    # Increment member_count
    current_count = item.get("member_count", 0)
    update_item(keys["PK"], keys["SK"], {
        "member_count": current_count + len(members),
        "updated_at": now,
    })

    return success({"added": len(members)})


def _delete_member(org_id: str, list_id: str, email: str) -> dict:
    """Remove a member from a list."""
    keys = list_keys(org_id, list_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("List")

    member_keys = list_member_keys(list_id, email)
    member = get_item(member_keys["PK"], member_keys["SK"])
    if not member:
        return not_found("Member")

    delete_item(member_keys["PK"], member_keys["SK"])

    current_count = item.get("member_count", 0)
    update_item(keys["PK"], keys["SK"], {
        "member_count": max(0, current_count - 1),
        "updated_at": now_iso(),
    })

    return no_content()


def _delete_list(org_id: str, list_id: str) -> dict:
    """Delete a list and all its members."""
    keys = list_keys(org_id, list_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("List")

    # Delete all members
    members, _ = query(
        pk=f"LIST#{list_id}",
        sk_prefix="MEMBER#",
        limit=1000,
    )
    for member in members:
        delete_item(member["PK"], member["SK"])

    # Delete the list itself
    delete_item(keys["PK"], keys["SK"])

    return no_content()


def handler(event, context):
    """Route mailing list requests."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    params = event.get("pathParameters") or {}
    list_id = params.get("id", "")
    org_id = get_org_id(event)
    body = parse_body(event)

    # DELETE /lists/{id}/members/{email}
    if method == "DELETE" and "/members/" in path:
        email = params.get("email", "")
        return _delete_member(org_id, list_id, email)

    # POST /lists/{id}/members
    if method == "POST" and list_id and path.endswith("/members"):
        return _add_members(org_id, list_id, body)

    # DELETE /lists/{id}
    if method == "DELETE" and list_id:
        return _delete_list(org_id, list_id)

    # GET /lists/{id}
    if method == "GET" and list_id:
        return _get_list(org_id, list_id, event)

    # GET /lists
    if method == "GET":
        return _list_lists(org_id, event)

    # POST /lists
    if method == "POST":
        return _create_list(org_id, body)

    return bad_request("Unsupported method")
