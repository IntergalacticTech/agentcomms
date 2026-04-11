"""Search Lambda handler.

Basic text search across messages in an org using DynamoDB scan with filters.
"""

import json

from shared.auth import get_org_id
from shared.dynamo import query_gsi
from shared.response import success, bad_request
from shared.validation import parse_body


def handler(event, context):
    """Search messages across an org."""
    org_id = get_org_id(event)
    body = parse_body(event)

    query_text = body.get("query", "").lower()
    inbox_id = body.get("inbox_id")
    limit = min(body.get("limit", 25), 100)
    after = body.get("after")
    before = body.get("before")

    # Query all org messages via GSI3
    all_items = []
    last_key = None
    while True:
        items, last_key = query_gsi(
            "GSI3",
            f"ORG#{org_id}#MSGS",
            limit=500,
            exclusive_start_key=last_key,
        )
        all_items.extend(items)
        # Stop if we have enough raw items or no more pages
        if not last_key or len(all_items) >= 5000:
            break

    results = []
    for item in all_items:
        # Filter by query text (case-insensitive match against subject and snippet)
        if query_text:
            searchable = (
                item.get("subject", "") + " " + item.get("snippet", "")
            ).lower()
            if query_text not in searchable:
                continue

        # Filter by inbox_id
        if inbox_id and item.get("inbox_id") != inbox_id:
            continue

        # Filter by date range
        created_at = item.get("created_at", "")
        if after and created_at < after:
            continue
        if before and created_at > before:
            continue

        results.append(item)
        if len(results) >= limit:
            break

    return success({"data": results, "total": len(results)})
