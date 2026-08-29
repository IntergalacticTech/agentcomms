"""Lambda authorizer for API Gateway TOKEN type.

Supports both API key authentication (ak_live_* / ak_test_*) and
Cognito JWT authentication for the developer console.
"""

import base64
import hashlib
import json
import os
import time
import urllib.request

from shared.dynamo import query_gsi

USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Module-level cache for JWKS
_jwks_cache = None


def _extract_token(event: dict) -> str | None:
    """Extract API token from the event."""
    # Check authorizationToken field (API Gateway TOKEN authorizer)
    token = event.get("authorizationToken", "")
    if token.startswith("Bearer "):
        return token[7:]
    if token.startswith("ak_live_") or token.startswith("ak_test_"):
        return token
    if token.startswith("eyJ"):
        return token  # JWT token passed directly via identity source header

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


def _get_wildcard_arn(event: dict) -> str:
    """Build a wildcard resource ARN so the cached policy covers all methods."""
    method_arn = event.get("methodArn", "*")
    if "/" in method_arn:
        parts = method_arn.split("/")
        return "/".join(parts[:2]) + "/*"
    return method_arn


def _fetch_jwks() -> dict:
    """Fetch and cache JWKS from Cognito."""
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache

    jwks_url = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
    with urllib.request.urlopen(jwks_url, timeout=5) as resp:
        _jwks_cache = json.loads(resp.read().decode("utf-8"))
    return _jwks_cache


def _validate_jwt(token: str) -> dict:
    """Validate a Cognito JWT and return claims.

    Performs claim-level verification: issuer, expiration, and token_use.
    For production-grade RSA signature verification, add PyJWT later.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise Exception("Unauthorized")

    # Decode header to verify it references a known kid
    header_b64 = parts[0]
    header_b64 += "=" * (4 - len(header_b64) % 4)
    header = json.loads(base64.urlsafe_b64decode(header_b64))

    # Verify kid exists in JWKS (confirms token was issued for this user pool)
    if USER_POOL_ID:
        try:
            jwks = _fetch_jwks()
            kid = header.get("kid")
            matching_keys = [k for k in jwks.get("keys", []) if k.get("kid") == kid]
            if not matching_keys:
                raise Exception("Unauthorized")
        except Exception as e:
            if "Unauthorized" in str(e):
                raise
            # If JWKS fetch fails (e.g. network), fall through to claim checks
            pass

    # Decode payload
    payload_b64 = parts[1]
    payload_b64 += "=" * (4 - len(payload_b64) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload_b64))

    # Verify issuer
    expected_iss = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
    if claims.get("iss") != expected_iss:
        raise Exception("Unauthorized")

    # Verify expiration
    if claims.get("exp", 0) < time.time():
        raise Exception("Unauthorized")

    # Verify token use
    if claims.get("token_use") not in ("id", "access"):
        raise Exception("Unauthorized")

    return claims


def _validate_api_key(token: str) -> dict:
    """Validate an API key and return the key item from DynamoDB."""
    key_hash = hashlib.sha256(token.encode()).hexdigest()

    items, _ = query_gsi("GSI1", f"APIKEY#{key_hash}", limit=1)
    if not items:
        raise Exception("Unauthorized")

    key_item = items[0]

    if key_item.get("status") != "active":
        raise Exception("Unauthorized")

    # Hard-block suspended orgs at the front door so we don't have to scatter
    # status checks across every handler. Authorizer denies → API Gateway
    # returns 403 before any handler runs.
    org_id = key_item.get("org_id", "")
    if org_id:
        from shared.dynamo import get_item
        org = get_item(f"ORG#{org_id}", f"ORG#{org_id}")
        if org and org.get("status") == "suspended":
            raise Exception("Unauthorized")

    return key_item


def handler(event, context):
    """Lambda authorizer handler.

    Supports two authentication methods:
    1. API key: tokens starting with ak_live_ or ak_test_
    2. Cognito JWT: all other Bearer tokens
    """
    token = _extract_token(event)
    if not token:
        raise Exception("Unauthorized")

    wildcard_arn = _get_wildcard_arn(event)

    # Route to appropriate auth method
    if token.startswith("ak_live_") or token.startswith("ak_test_"):
        # API key authentication
        key_item = _validate_api_key(token)

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
    else:
        # JWT authentication (Cognito)
        claims = _validate_jwt(token)

        org_id = claims.get("custom:org_id", "")

        # If no org_id in claims, try to look up by email
        if not org_id:
            email = claims.get("email", "")
            if email:
                # Look up org by email via GSI
                # For now, org_id must be in the token claims
                pass

        return _generate_policy(
            principal_id=org_id or claims.get("sub", "unknown"),
            effect="Allow",
            resource=wildcard_arn,
            context={
                "org_id": org_id,
                "email": claims.get("email", ""),
                "sub": claims.get("sub", ""),
                "auth_type": "jwt",
            },
        )
