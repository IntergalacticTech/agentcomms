"""Metrics Lambda handler."""

from collections import defaultdict
from datetime import datetime

from shared.auth import get_org_id
from shared.dynamo import get_item, query, query_gsi
from shared.models import org_keys
from shared.response import success, bad_request
from shared.validation import parse_body

VALID_METRICS = {"messages_sent", "messages_received", "inboxes_created", "api_calls"}
VALID_PERIODS = {"hour", "day", "week", "month"}


def _aggregate_by_period(items, period, date_field="created_at"):
    """Aggregate items into time-series buckets by period."""
    buckets = defaultdict(int)
    for item in items:
        ts = item.get(date_field, "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        if period == "hour":
            key = dt.strftime("%Y-%m-%dT%H:00:00.000Z")
        elif period == "day":
            key = dt.strftime("%Y-%m-%dT00:00:00.000Z")
        elif period == "week":
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        elif period == "month":
            key = dt.strftime("%Y-%m-01T00:00:00.000Z")
        else:
            key = dt.strftime("%Y-%m-%dT00:00:00.000Z")

        buckets[key] += 1

    return [{"timestamp": k, "value": v} for k, v in sorted(buckets.items())]


def _aggregate_by_group(items, group_by, period, date_field="created_at"):
    """Aggregate items grouped by a field, then by period."""
    groups = defaultdict(list)
    for item in items:
        group_value = item.get(group_by, "unknown")
        groups[group_value].append(item)

    result = {}
    for group_value, group_items in sorted(groups.items()):
        result[group_value] = _aggregate_by_period(group_items, period, date_field)
    return result


def _fetch_all_pages(pk_value, index_name, sk_prefix=None, limit_per_page=100):
    """Fetch all items from a GSI query, paginating through results."""
    all_items = []
    last_key = None
    while True:
        items, last_key = query_gsi(
            index_name=index_name,
            pk_value=pk_value,
            sk_prefix=sk_prefix,
            limit=limit_per_page,
            exclusive_start_key=last_key,
        )
        all_items.extend(items)
        if not last_key:
            break
    return all_items


def _filter_by_date_range(items, start, end, date_field="created_at"):
    """Filter items to those within the given ISO date range."""
    filtered = []
    for item in items:
        ts = item.get(date_field, "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if start and dt < start:
            continue
        if end and dt > end:
            continue
        filtered.append(item)
    return filtered


def _parse_iso(value):
    """Parse an ISO datetime string, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _query_messages(org_id, direction, start, end):
    """Query messages for the org filtered by direction and date range."""
    items = _fetch_all_pages(f"ORG#{org_id}#MSGS", "GSI3", sk_prefix="MSG#")
    # Filter by direction
    items = [i for i in items if i.get("direction") == direction]
    # Filter by date range
    return _filter_by_date_range(items, start, end)


def _query_inboxes(org_id, start, end):
    """Query inboxes for the org filtered by date range."""
    all_items = []
    last_key = None
    while True:
        items, last_key = query(
            pk=f"ORG#{org_id}",
            sk_prefix="INBOX#",
            limit=100,
            exclusive_start_key=last_key,
        )
        all_items.extend(items)
        if not last_key:
            break
    return _filter_by_date_range(all_items, start, end)


def _query_api_calls(org_id, start, end):
    """Query rate limit counters for the org as a proxy for API calls."""
    all_items = []
    last_key = None
    while True:
        items, last_key = query(
            pk=f"ORG#{org_id}",
            sk_prefix="RATE#",
            limit=100,
            exclusive_start_key=last_key,
        )
        all_items.extend(items)
        if not last_key:
            break
    return _filter_by_date_range(all_items, start, end, date_field="created_at")


def _handle_metrics_query(event):
    """Handle POST /metrics/query."""
    org_id = get_org_id(event)
    body = parse_body(event)

    metric = body.get("metric", "")
    if metric not in VALID_METRICS:
        return bad_request(f"Invalid metric. Must be one of: {', '.join(sorted(VALID_METRICS))}")

    period = body.get("period", "day")
    if period not in VALID_PERIODS:
        return bad_request(f"Invalid period. Must be one of: {', '.join(sorted(VALID_PERIODS))}")

    start = _parse_iso(body.get("start"))
    end = _parse_iso(body.get("end"))
    group_by = body.get("group_by")

    # Fetch and aggregate data based on metric type
    if metric == "messages_sent":
        items = _query_messages(org_id, "outbound", start, end)
    elif metric == "messages_received":
        items = _query_messages(org_id, "inbound", start, end)
    elif metric == "inboxes_created":
        items = _query_inboxes(org_id, start, end)
    elif metric == "api_calls":
        items = _query_api_calls(org_id, start, end)
    else:
        items = []

    # Build response
    if group_by:
        data_points = _aggregate_by_group(items, group_by, period)
    else:
        data_points = _aggregate_by_period(items, period)

    return success({
        "metric": metric,
        "period": period,
        "start": body.get("start"),
        "end": body.get("end"),
        "group_by": group_by,
        "data": data_points,
    })


def _handle_usage_summary(event):
    """Handle GET /metrics/usage."""
    org_id = get_org_id(event)

    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return success({
            "inboxes": 0,
            "messages_today": 0,
            "api_keys": 0,
            "pods": 0,
            "domains": 0,
            "webhooks": 0,
            "tier": "free",
            "quotas": {},
        })

    usage = org.get("usage", {})
    quotas = org.get("quotas", {})
    tier = org.get("tier", "free")

    return success({
        "inboxes": usage.get("inboxes", 0),
        "messages_today": usage.get("messages_today", 0),
        "api_keys": usage.get("api_keys", 0),
        "pods": usage.get("pods", 0),
        "domains": usage.get("domains", 0),
        "webhooks": usage.get("webhooks", 0),
        "tier": tier,
        "quotas": quotas,
    })


def handler(event, context):
    """Route metrics requests."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")

    if method == "POST" and path.endswith("/metrics/query"):
        return _handle_metrics_query(event)
    elif method == "GET" and path.endswith("/metrics/usage"):
        return _handle_usage_summary(event)
    else:
        return bad_request("Unknown metrics endpoint")
