"""Quota enforcement for free tier limits."""

from shared.dynamo import get_item
from shared.models import org_keys
from shared.response import error


QUOTA_MAP = {
    "inboxes": "max_inboxes",
    "pods": "max_pods",
    "api_keys": "max_api_keys",
    "domains": "max_domains",
    "webhooks": "max_webhooks",
}


def check_quota(org_id: str, resource: str) -> dict | None:
    """Check if org has quota remaining for a resource.

    Returns None if quota OK, or an error response dict if quota exceeded.
    """
    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return None  # No org record means no quota enforcement

    quotas = org.get("quotas", {})
    usage = org.get("usage", {})

    quota_field = QUOTA_MAP.get(resource)
    if not quota_field:
        return None  # No quota for this resource

    max_allowed = quotas.get(quota_field, 0)
    current = usage.get(resource, 0)

    # 0 means unlimited
    if max_allowed == 0:
        return None

    if current >= max_allowed:
        return error(
            "QUOTA_EXCEEDED",
            f"You have reached your {resource} limit ({max_allowed}). Upgrade to increase your quota.",
            403,
        )

    return None


def increment_usage(org_id: str, resource: str) -> None:
    """Increment the usage counter for a resource on the org."""
    from shared.dynamo import _get_table, get_item
    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return  # No org record, nothing to track

    # Ensure the usage map exists before updating a nested key
    if "usage" not in org:
        _get_table().update_item(
            Key={"PK": keys["PK"], "SK": keys["SK"]},
            UpdateExpression="SET #usage = :empty_map",
            ExpressionAttributeNames={"#usage": "usage"},
            ExpressionAttributeValues={":empty_map": {}},
        )

    _get_table().update_item(
        Key={"PK": keys["PK"], "SK": keys["SK"]},
        UpdateExpression="SET #usage.#resource = if_not_exists(#usage.#resource, :zero) + :one",
        ExpressionAttributeNames={"#usage": "usage", "#resource": resource},
        ExpressionAttributeValues={":one": 1, ":zero": 0},
    )


def decrement_usage(org_id: str, resource: str) -> None:
    """Decrement the usage counter for a resource on the org."""
    from shared.dynamo import _get_table, get_item
    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return  # No org record, nothing to track

    # Ensure the usage map exists before updating a nested key
    if "usage" not in org:
        _get_table().update_item(
            Key={"PK": keys["PK"], "SK": keys["SK"]},
            UpdateExpression="SET #usage = :empty_map",
            ExpressionAttributeNames={"#usage": "usage"},
            ExpressionAttributeValues={":empty_map": {}},
        )

    _get_table().update_item(
        Key={"PK": keys["PK"], "SK": keys["SK"]},
        UpdateExpression="SET #usage.#resource = if_not_exists(#usage.#resource, :one) - :one",
        ExpressionAttributeNames={"#usage": "usage", "#resource": resource},
        ExpressionAttributeValues={":one": 1},
    )
