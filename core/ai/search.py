# core/ai/search.py
"""Keyword-based message search (Phase 2 — Phase 3 adds semantic/vector search)."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    )


def search(
    org_id: str,
    agent_id: str,
    query: str,
    *,
    channel: str | None = None,
    limit: int = 20,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keyword search across messages for *agent_id*.

    Phase 2: DynamoDB query on AGT#{agent_id} + MSG# prefix with post-query
    keyword filtering on ``body_text``.

    Returns a list of plain dicts (the DynamoDB items stripped of internal
    index keys).

    Phase 3 will replace the body_text scan with a vector/embedding search.
    """
    table = _get_table()
    query_lower = query.lower()

    # Build key condition — all messages for this agent
    key_cond = Key("PK").eq(f"AGT#{agent_id}") & Key("SK").begins_with("MSG#")

    # Paginate until we have enough hits (cap total scan at 1000 items)
    results: list[dict] = []
    last_key = None
    scanned = 0
    max_scan = 1000

    while scanned < max_scan:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": key_cond,
            "ScanIndexForward": False,
            "Limit": min(200, max_scan - scanned),
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        resp = table.query(**kwargs)
        items = resp.get("Items", [])
        scanned += len(items)

        for item in items:
            # Filter by keyword in body_text
            body = (item.get("body_text") or "").lower()
            subject = (item.get("subject") or "").lower()
            if query_lower not in body and query_lower not in subject:
                continue

            # Filter by channel if requested
            if channel and item.get("channel") != channel:
                continue

            # Filter by since
            if since:
                received_at_str = item.get("received_at", "")
                if received_at_str:
                    try:
                        received_at = datetime.fromisoformat(received_at_str.replace("Z", "+00:00"))
                        if received_at < since:
                            continue
                    except ValueError:
                        pass

            # Strip internal index keys
            clean = {
                k: v for k, v in item.items()
                if not k.startswith("gsi") and k not in ("PK", "SK", "entity")
            }
            results.append(clean)

            if len(results) >= limit:
                return results

        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    return results
