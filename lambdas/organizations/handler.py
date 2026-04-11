"""Organizations Lambda handler."""

from shared.auth import get_org_id
from shared.dynamo import get_item
from shared.models import org_keys
from shared.response import not_found, success

ORG_FIELDS = [
    "id", "name", "email", "tier", "status",
    "settings", "quotas", "usage", "created_at", "updated_at",
]


def _filter_org(item: dict) -> dict:
    """Filter org item to only return expected API fields."""
    return {k: item[k] for k in ORG_FIELDS if k in item}


def handler(event, context):
    """Handle GET /organizations/me."""
    org_id = get_org_id(event)
    keys = org_keys(org_id)
    item = get_item(keys["PK"], keys["SK"])

    if not item:
        return not_found("Organization")

    return success(_filter_org(item))
