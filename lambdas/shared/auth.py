"""Extract auth context from Lambda authorizer."""


def get_auth_context(event: dict) -> dict:
    """Extract auth context from the Lambda authorizer.

    Returns dict with org_id, key_id, scope, scope_resource_id.
    """
    ctx = event.get("requestContext", {}).get("authorizer", {})
    return {
        "org_id": ctx.get("org_id", ""),
        "key_id": ctx.get("key_id", ""),
        "scope": ctx.get("scope", ""),
        "scope_resource_id": ctx.get("scope_resource_id", ""),
    }


def get_org_id(event: dict) -> str:
    """Extract org_id from the Lambda authorizer context."""
    return get_auth_context(event)["org_id"]
