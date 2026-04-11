"""Lambda authorizer for API Gateway TOKEN type."""

import hashlib

from shared.dynamo import query_gsi


def _extract_token(event: dict) -> str | None:
    """Extract API token from the event."""
    # Check authorizationToken field (API Gateway TOKEN authorizer)
    token = event.get("authorizationToken", "")
    if token.startswith("Bearer "):
        return token[7:]
    if token.startswith("am_live_") or token.startswith("am_test_"):
        return token

    # Check headers
    headers = event.get("headers") or {}
    # Normalize header keys to lowercase
    lower_headers = {k.lower(): v for k, v in headers.items()}

    api_key = lower_headers.get("x-api-key", "")
    if api_key:
        return api_key

    auth = lower_headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]

    return None


def _generate_policy(principal_id: str, effect: str, resource: str, context: dict | None = None) -> dict:
    """Generate an IAM policy document."""
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if context:
        policy["context"] = context
    return policy


def handler(event, context):
    """Lambda authorizer handler."""
    token = _extract_token(event)
    if not token:
        raise Exception("Unauthorized")

    # Validate token prefix
    if not (token.startswith("am_live_") or token.startswith("am_test_")):
        raise Exception("Unauthorized")

    # Hash the token
    key_hash = hashlib.sha256(token.encode()).hexdigest()

    # Look up the key in DynamoDB
    items, _ = query_gsi("GSI1", f"APIKEY#{key_hash}", limit=1)
    if not items:
        raise Exception("Unauthorized")

    key_item = items[0]

    # Check status
    if key_item.get("status") != "active":
        raise Exception("Unauthorized")

    # Build a wildcard resource ARN so the cached policy covers all methods.
    # methodArn format: arn:aws:execute-api:region:account:api-id/stage/METHOD/resource
    method_arn = event.get("methodArn", "*")
    if "/" in method_arn:
        # Replace everything after stage with wildcard
        parts = method_arn.split("/")
        wildcard_arn = "/".join(parts[:2]) + "/*"
    else:
        wildcard_arn = method_arn

    return _generate_policy(
        principal_id=key_item.get("org_id", "unknown"),
        effect="Allow",
        resource=wildcard_arn,
        context={
            "org_id": key_item.get("org_id", ""),
            "key_id": key_item.get("key_id", ""),
            "scope": key_item.get("scope", ""),
            "scope_resource_id": key_item.get("scope_resource_id", ""),
        },
    )
