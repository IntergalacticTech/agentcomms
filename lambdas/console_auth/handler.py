"""Console authentication handler - Cognito user management + FreeMail org creation."""

import hashlib
import os
import secrets

import boto3

from shared.dynamo import get_item, put_item
from shared.models import api_key_gsi1, api_key_keys, now_iso, org_keys
from shared.response import bad_request, created, error, success
from shared.ulid import generate_ulid
from shared.validation import parse_body, require_fields

COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")

cognito = boto3.client("cognito-idp")

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _gen_api_key(env: str = "live") -> str:
    """Generate a new API key with the am_{env}_ prefix."""
    rb = secrets.token_bytes(32)
    n = int.from_bytes(rb, "big")
    e = []
    while n > 0:
        n, r = divmod(n, 62)
        e.append(BASE62[r])
    return f"am_{env}_{''.join(reversed(e)).rjust(43, '0')}"


def handler(event, context):
    """Route console auth requests."""
    path = event.get("path", "")
    method = event.get("httpMethod", "")

    if path.endswith("/signup") and method == "POST":
        return handle_signup(event)
    elif path.endswith("/login") and method == "POST":
        return handle_login(event)
    elif path.endswith("/refresh") and method == "POST":
        return handle_refresh(event)
    elif path.endswith("/me") and method == "GET":
        return handle_me(event)
    return bad_request("Not found")


def handle_signup(event):
    """Create a Cognito user and FreeMail organization."""
    body = parse_body(event)
    err = require_fields(body, ["email", "password"])
    if err:
        return bad_request(err)

    email = body["email"]
    password = body["password"]
    name = body.get("name", email.split("@")[0])

    # Create Cognito user
    try:
        cognito.sign_up(
            ClientId=COGNITO_CLIENT_ID,
            Username=email,
            Password=password,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "name", "Value": name},
            ],
        )
    except cognito.exceptions.UsernameExistsException:
        return error("CONFLICT", "An account with this email already exists.", 409)
    except Exception as e:
        return error("INVALID_REQUEST", str(e), 400)

    # Create FreeMail org
    org_id = generate_ulid()
    now = now_iso()
    org_item = {
        **org_keys(org_id),
        "entity_type": "Organization",
        "id": org_id,
        "name": name,
        "email": email,
        "tier": "free",
        "status": "active",
        "settings": {"default_domain": "victorymail.dev"},
        "quotas": {
            "max_inboxes": 5,
            "max_messages_per_day": 1000,
            "max_api_keys": 5,
            "max_pods": 3,
            "max_domains": 1,
            "max_webhooks": 5,
        },
        "usage": {"inboxes": 0, "api_keys": 0, "pods": 0, "domains": 0},
        "created_at": now,
        "updated_at": now,
        "GSI1PK": "TIER#free",
        "GSI1SK": f"ORG#{org_id}",
    }
    put_item(org_item)

    # Set org_id on Cognito user (after auto-confirm or admin confirm)
    try:
        cognito.admin_update_user_attributes(
            UserPoolId=USER_POOL_ID,
            Username=email,
            UserAttributes=[{"Name": "custom:org_id", "Value": org_id}],
        )
    except Exception:
        pass  # Will be set on first login if this fails

    # Generate initial API key
    key_id = generate_ulid()
    plaintext = _gen_api_key()
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    put_item(
        {
            **api_key_keys(org_id, key_id),
            **api_key_gsi1(key_hash, key_id),
            "entity_type": "ApiKey",
            "id": key_id,
            "org_id": org_id,
            "name": "Default Key",
            "prefix": plaintext[:12],
            "key_hash": key_hash,
            "environment": "live",
            "scope": "org",
            "scope_resource_id": None,
            "status": "active",
            "created_at": now,
        }
    )

    return created(
        {
            "message": "Account created. Check your email to verify.",
            "org_id": org_id,
            "api_key": plaintext,
        }
    )


def handle_login(event):
    """Authenticate a user via Cognito USER_PASSWORD_AUTH."""
    body = parse_body(event)
    err = require_fields(body, ["email", "password"])
    if err:
        return bad_request(err)

    try:
        resp = cognito.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": body["email"],
                "PASSWORD": body["password"],
            },
        )
        result = resp.get("AuthenticationResult", {})
        return success(
            {
                "id_token": result.get("IdToken"),
                "access_token": result.get("AccessToken"),
                "refresh_token": result.get("RefreshToken"),
                "expires_in": result.get("ExpiresIn"),
            }
        )
    except cognito.exceptions.NotAuthorizedException:
        return error("UNAUTHORIZED", "Invalid email or password.", 401)
    except cognito.exceptions.UserNotConfirmedException:
        return error("UNAUTHORIZED", "Please verify your email first.", 401)
    except Exception as e:
        return error("UNAUTHORIZED", str(e), 401)


def handle_refresh(event):
    """Refresh tokens using a Cognito refresh token."""
    body = parse_body(event)
    err = require_fields(body, ["refresh_token"])
    if err:
        return bad_request(err)

    try:
        resp = cognito.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": body["refresh_token"]},
        )
        result = resp.get("AuthenticationResult", {})
        return success(
            {
                "id_token": result.get("IdToken"),
                "access_token": result.get("AccessToken"),
                "expires_in": result.get("ExpiresIn"),
            }
        )
    except Exception as e:
        return error("UNAUTHORIZED", str(e), 401)


def handle_me(event):
    """Get the current user's organization profile."""
    org_id = (
        event.get("requestContext", {}).get("authorizer", {}).get("org_id")
    )
    if not org_id:
        return error("UNAUTHORIZED", "Not authenticated.", 401)
    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return error("RESOURCE_NOT_FOUND", "Organization not found.", 404)
    return success(
        {
            "org_id": org["id"],
            "name": org.get("name"),
            "email": org.get("email"),
            "tier": org.get("tier"),
        }
    )
