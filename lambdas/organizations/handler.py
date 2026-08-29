"""Organizations Lambda handler."""

from shared.abuse import unsuspend_org
from shared.auth import get_org_id
from shared.dynamo import get_item
from shared.models import org_keys
from shared.response import bad_request, not_found, success

ORG_FIELDS = [
    "id", "name", "email", "tier", "status",
    "settings", "quotas", "usage",
    "sends_total", "bounces_total", "complaints_total",
    "suspended_reason", "suspended_at",
    "created_at", "updated_at",
]


def _filter_org(item: dict) -> dict:
    """Filter org item to only return expected API fields."""
    return {k: item[k] for k in ORG_FIELDS if k in item}


def _abuse_summary(org_id: str) -> dict:
    keys = org_keys(org_id)
    item = get_item(keys["PK"], keys["SK"])
    if not item:
        return not_found("Organization")
    sends = int(item.get("sends_total", 0) or 0)
    bounces = int(item.get("bounces_total", 0) or 0)
    complaints = int(item.get("complaints_total", 0) or 0)
    return success({
        "org_id": org_id,
        "tier": item.get("tier", "free"),
        "status": item.get("status", "active"),
        "sends_total": sends,
        "bounces_total": bounces,
        "complaints_total": complaints,
        "bounce_rate": (bounces / sends) if sends else 0.0,
        "complaint_rate": (complaints / sends) if sends else 0.0,
        "suspended_reason": item.get("suspended_reason", ""),
        "suspended_at": item.get("suspended_at", ""),
    })


def handler(event, context):
    """Handle GET /organizations/me, GET /organizations/me/abuse,
    POST /organizations/me/unsuspend."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    org_id = get_org_id(event)

    if path.endswith("/unsuspend") and method == "POST":
        # Operator action — clears suspension and resets abuse counters.
        # Currently anyone with a valid API key on the org can unsuspend
        # themselves; tighten this to admin-only when we ship a real role
        # model.
        ok = unsuspend_org(org_id)
        if not ok:
            return bad_request("Could not unsuspend organization")
        return _abuse_summary(org_id)

    if path.endswith("/abuse") and method == "GET":
        return _abuse_summary(org_id)

    keys = org_keys(org_id)
    item = get_item(keys["PK"], keys["SK"])

    if not item:
        return not_found("Organization")

    return success(_filter_org(item))
