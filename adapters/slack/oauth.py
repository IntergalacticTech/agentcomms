# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/slack/oauth.py
"""
Slack OAuth v2 bridge flow.

Handles:
  - bridge_start: generate OAuth URL + store short-lived state nonce in DynamoDB
  - bridge_complete: exchange code, store bot token in SSM, update Channel record
  - oauth_callback_handler: Lambda handler for GET /webhooks/slack/oauth/callback
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ENV = os.environ.get("AGENTCOMMS_ENV", "dev")
SLACK_OAUTH_URL = "https://slack.com/oauth/v2/authorize"
SLACK_OAUTH_ACCESS_URL = "https://slack.com/api/oauth.v2.access"
SLACK_SCOPES = "chat:write,im:history,im:read,im:write,app_mentions:read,channels:history"


def get_oauth_callback_url() -> str:
    """Return the AgentComms-hosted Slack OAuth callback URL.

    This URL is used as the OAuth ``redirect_uri`` in BOTH the authorize URL
    (build_oauth_url) and the token exchange (exchange_oauth_code). Slack
    requires the two to byte-match, so both call this single function and the
    value MUST be derived only from configuration (never from the incoming
    request), otherwise the token exchange fails with ``bad_redirect_uri``.

    Resolution order:
      1. AGENTCOMMS_SLACK_OAUTH_CALLBACK_URL (explicit, preferred).
      2. https://{AGENTCOMMS_API_HOST}[/{AGENTCOMMS_API_STAGE}]/webhooks/slack/oauth/callback
    """
    url = os.environ.get("AGENTCOMMS_SLACK_OAUTH_CALLBACK_URL", "").strip()
    if url:
        return url
    host = os.environ.get("AGENTCOMMS_API_HOST", "").strip()
    if not host:
        return ""
    stage = os.environ.get("AGENTCOMMS_API_STAGE", "prod").strip().strip("/")
    base = f"https://{host}"
    if stage:
        base = f"{base}/{stage}"
    return f"{base}/webhooks/slack/oauth/callback"


def _allowed_redirect_hosts() -> set[str]:
    raw = os.environ.get("AGENTCOMMS_ALLOWED_REDIRECT_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def is_safe_return_url(return_url: str) -> bool:
    """Guard the final 302 against open-redirect abuse.

    Only https URLs with a host are permitted. When
    AGENTCOMMS_ALLOWED_REDIRECT_HOSTS is set, the host must be a member of that
    allowlist; otherwise any https host is accepted.
    """
    if not return_url:
        return False
    try:
        parsed = urlparse(return_url)
    except (ValueError, TypeError):
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    allowed = _allowed_redirect_hosts()
    if not allowed:
        return True
    return parsed.hostname.lower() in allowed


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _ssm_client():
    return boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _get_ssm_param(name: str, with_decryption: bool = False) -> str:
    ssm = _ssm_client()
    resp = ssm.get_parameter(Name=name, WithDecryption=with_decryption)
    return resp["Parameter"]["Value"]


def _put_ssm_param(name: str, value: str, param_type: str = "String") -> None:
    ssm = _ssm_client()
    ssm.put_parameter(
        Name=name,
        Value=value,
        Type=param_type,
        Overwrite=True,
    )


def _delete_ssm_param(name: str) -> None:
    ssm = _ssm_client()
    try:
        ssm.delete_parameter(Name=name)
    except ssm.exceptions.ParameterNotFound:
        logger.warning("SSM parameter %s not found during delete", name)


def get_client_id() -> str:
    """Retrieve the Slack app client_id from SSM."""
    param_name = f"/agentcomms/{ENV}/adapters/slack/client_id"
    return _get_ssm_param(param_name)


def get_client_secret() -> str:
    """Retrieve the Slack app client_secret from SSM."""
    param_name = f"/agentcomms/{ENV}/adapters/slack/client_secret"
    return _get_ssm_param(param_name, with_decryption=True)


def get_signing_secret() -> str:
    """Retrieve the Slack app signing_secret from SSM."""
    param_name = f"/agentcomms/{ENV}/adapters/slack/signing_secret"
    return _get_ssm_param(param_name, with_decryption=True)


def get_workspace_token(team_id: str) -> str:
    """Retrieve the bot token for a given Slack workspace from SSM."""
    param_name = f"/agentcomms/{ENV}/adapters/slack/workspaces/{team_id}"
    return _get_ssm_param(param_name, with_decryption=True)


def store_workspace_token(team_id: str, bot_token: str) -> None:
    """Store the bot token for a Slack workspace in SSM as a SecureString."""
    param_name = f"/agentcomms/{ENV}/adapters/slack/workspaces/{team_id}"
    _put_ssm_param(param_name, bot_token, "SecureString")


def delete_workspace_token(team_id: str) -> None:
    """Delete the bot token for a Slack workspace from SSM."""
    param_name = f"/agentcomms/{ENV}/adapters/slack/workspaces/{team_id}"
    _delete_ssm_param(param_name)


def store_oauth_state(state: str, return_url: str, agent_id: str, org_id: str) -> None:
    """Store OAuth state nonce in DynamoDB with 10-minute TTL.

    PK = OAUTH#{state}, SK = STATE
    """
    table = _get_table()
    ttl = int(time.time()) + 600  # 10 minutes
    table.put_item(Item={
        "PK": f"OAUTH#{state}",
        "SK": "STATE",
        "entity": "oauth_state",
        "state": state,
        "return_url": return_url,
        "agent_id": agent_id,
        "org_id": org_id,
        "ttl": ttl,
    })


def get_and_consume_oauth_state(state: str) -> dict[str, Any] | None:
    """Retrieve and delete OAuth state nonce (one-time use).

    Returns the state record dict or None if not found / expired.
    """
    table = _get_table()
    resp = table.get_item(Key={"PK": f"OAUTH#{state}", "SK": "STATE"})
    item = resp.get("Item")
    if item is None:
        return None

    # Delete the state (one-time use)
    table.delete_item(Key={"PK": f"OAUTH#{state}", "SK": "STATE"})

    # Check TTL manually (DynamoDB TTL deletion is eventually consistent)
    ttl = int(item.get("ttl", 0))
    if ttl < int(time.time()):
        return None  # Expired

    return item


def build_oauth_url(return_url: str, state: str) -> str:
    """Build the Slack OAuth v2 authorization URL.

    The ``redirect_uri`` is the AgentComms-hosted callback URL — NOT the
    caller's ``return_url``. Slack redirects the browser to this callback,
    which then completes the token exchange and finally 302s the browser to
    the stored ``return_url``. The callback URL here must byte-match the one
    used in the token exchange (see exchange_oauth_code / get_oauth_callback_url).

    ``return_url`` is accepted for signature stability but is persisted via
    store_oauth_state (used only for the final redirect), not embedded here.
    """
    client_id = get_client_id()
    params = {
        "client_id": client_id,
        "scope": SLACK_SCOPES,
        "user_scope": "",
        "redirect_uri": get_oauth_callback_url(),
        "state": state,
    }
    return f"{SLACK_OAUTH_URL}?{urlencode(params)}"


def exchange_oauth_code(code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange the OAuth code for a bot token via oauth.v2.access.

    Returns the full Slack API response dict.
    Raises RuntimeError if the exchange fails.
    """
    import urllib.request

    client_id = get_client_id()
    client_secret = get_client_secret()

    data = urlencode({
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")

    req = urllib.request.Request(SLACK_OAUTH_ACCESS_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(f"Slack oauth.v2.access failed: {result.get('error')}")

    return result


def oauth_callback_handler(event: dict, context) -> dict:
    """Lambda handler for GET /webhooks/slack/oauth/callback.

    Flow:
      1. Extract code + state from query params.
      2. Validate state against DynamoDB nonce.
      3. Exchange code for bot token.
      4. Store token in SSM.
      5. Update Channel record in DynamoDB.
      6. Redirect to return_url with success flag.
    """
    from core.data.repo import Repo
    from core.data.models import ChannelStatus

    params = event.get("queryStringParameters") or {}
    code = params.get("code")
    state = params.get("state")

    if not code or not state:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "missing code or state"}),
        }

    # Validate state
    state_record = get_and_consume_oauth_state(state)
    if state_record is None:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "invalid or expired state"}),
        }

    agent_id = state_record["agent_id"]
    org_id = state_record["org_id"]
    return_url = state_record["return_url"]

    # Build redirect URI — must byte-match the one used in build_oauth_url.
    # Derived only from configuration (never from the incoming request Host),
    # otherwise Slack rejects the exchange with bad_redirect_uri.
    redirect_uri = get_oauth_callback_url()

    try:
        token_resp = exchange_oauth_code(code, redirect_uri)
    except RuntimeError as e:
        logger.exception("OAuth code exchange failed")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }

    team_id = token_resp.get("team", {}).get("id", "")
    bot_token = token_resp.get("access_token", "")
    bot_user_id = token_resp.get("bot_user_id", "")
    app_id = token_resp.get("app_id", "")

    # Store bot token in SSM
    store_workspace_token(team_id, bot_token)

    # Update Channel record
    table = _get_table()
    repo = Repo(table)
    channels = repo.list_channels(agent_id=agent_id)
    slack_channel = next(
        (c for c in channels if c.channel.value == "slack" and c.status.value == "pending_oauth"),
        None,
    )

    if slack_channel:
        slack_channel.status = ChannelStatus.ACTIVE
        slack_channel.config = {
            "team_id": team_id,
            "bot_user_id": bot_user_id,
            "app_id": app_id,
        }
        # Update address_index_value for GSI2 inbound routing
        slack_channel.address_index_value = f"{team_id}:{bot_user_id}"
        repo.put_channel(slack_channel)
        logger.info(
            "Slack OAuth complete: team=%s agent=%s channel=%s",
            team_id, agent_id, slack_channel.channel_id,
        )
    else:
        logger.warning(
            "No pending_oauth slack channel found for agent %s", agent_id
        )

    # Redirect back to caller with success — but only to a vetted return_url.
    # return_url is attacker-influenceable (stored at bridge_start), so refuse
    # to emit a Location to an unexpected host/scheme (open-redirect guard).
    if not is_safe_return_url(return_url):
        logger.warning("Refusing unsafe OAuth return_url: %s", return_url)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "invalid return_url"}),
        }

    sep = "&" if urlparse(return_url).query else "?"
    redirect_target = f"{return_url}{sep}slack_connected=true&team_id={team_id}"
    return {
        "statusCode": 302,
        "headers": {"Location": redirect_target},
        "body": "",
    }
