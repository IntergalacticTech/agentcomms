"""Pods Lambda handler."""

from shared.auth import get_org_id
from shared.dynamo import delete_item, get_item, put_item, query_gsi
from shared.models import now_iso, pod_gsi1, pod_keys
from shared.pagination import (
    decode_page_token,
    get_pagination_params,
    paginated_response,
)
from shared.response import bad_request, created, no_content, not_found, success
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

POD_FIELDS = [
    "id", "name", "description", "org_id", "inbox_count", "status",
    "settings", "created_at", "updated_at",
]


def _filter_pod(item: dict) -> dict:
    return {k: item[k] for k in POD_FIELDS if k in item}


def _list_pods(event):
    """GET /pods: list pods for org."""
    org_id = get_org_id(event)
    limit, page_token, ascending = get_pagination_params(event)
    start_key = decode_page_token(page_token)

    items, last_key = query_gsi(
        "GSI1",
        f"ORG#{org_id}#PODS",
        limit=limit,
        ascending=ascending,
        exclusive_start_key=start_key,
    )

    return success(paginated_response([_filter_pod(i) for i in items], last_key))


def _get_pod(event):
    """GET /pods/{id}: get a single pod."""
    org_id = get_org_id(event)
    pod_id = event["pathParameters"]["id"]
    keys = pod_keys(org_id, pod_id)
    item = get_item(keys["PK"], keys["SK"])

    if not item:
        return not_found("Pod")

    return success(_filter_pod(item))


def _create_pod(event):
    """POST /pods: create a new pod."""
    org_id = get_org_id(event)
    body = parse_body(event)
    err = require_fields(body, ["name"])
    if err:
        return bad_request(err)

    pod_id = generate_ulid()
    now = now_iso()

    pod_item = {
        **pod_keys(org_id, pod_id),
        **pod_gsi1(org_id, pod_id),
        "id": pod_id,
        "org_id": org_id,
        "name": body["name"],
        "inbox_count": 0,
        "status": "active",
        "settings": body.get("settings", {}),
        "created_at": now,
        "updated_at": now,
    }
    put_item(pod_item)

    return created(_filter_pod(pod_item))


def _delete_pod(event):
    """DELETE /pods/{id}: delete a pod (fails if inboxes exist)."""
    org_id = get_org_id(event)
    pod_id = event["pathParameters"]["id"]
    keys = pod_keys(org_id, pod_id)
    item = get_item(keys["PK"], keys["SK"])

    if not item:
        return not_found("Pod")

    if item.get("inbox_count", 0) > 0:
        return bad_request("Cannot delete pod with existing inboxes")

    delete_item(keys["PK"], keys["SK"])

    return no_content()


def handler(event, context):
    """Route pod requests."""
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if method == "GET" and path_params.get("id"):
        return _get_pod(event)
    elif method == "GET":
        return _list_pods(event)
    elif method == "POST":
        return _create_pod(event)
    elif method == "DELETE" and path_params.get("id"):
        return _delete_pod(event)
    else:
        return bad_request("Unknown route")
