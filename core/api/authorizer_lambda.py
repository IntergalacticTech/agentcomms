# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

"""API Gateway TOKEN authorizer entrypoint."""
from urllib.parse import unquote

from core.api.authorizer import authorize, DeniedError
from core.api._common import get_repo


def _method_and_path(event: dict) -> tuple[str, str]:
    """Extract request method/path from TOKEN authorizer events.

    API Gateway TOKEN authorizers provide ``methodArn`` instead of the proxy
    event's ``path`` and ``httpMethod`` fields. Tests and some local harnesses
    may still pass those fields directly, so keep them as the first choice.
    """
    if event.get("path") and event.get("httpMethod"):
        return event["httpMethod"], event["path"]

    method_arn = event.get("methodArn", "")
    try:
        _, resource = method_arn.split("/", 1)
        parts = resource.split("/")
        method = parts[1] if len(parts) > 1 else ""
        path = "/" + "/".join(parts[2:]) if len(parts) > 2 else "/"
        return method, unquote(path)
    except ValueError:
        return "", ""


def _resource_policy_arns(method_arn: str, *, scope: str, agent_id: str | None, channel_id: str | None) -> list[str] | str:
    """Return least-broad execute-api resources for the caller scope."""
    if not method_arn:
        return []

    api_prefix, _, rest = method_arn.partition("/")
    stage = rest.split("/", 1)[0] if rest else "*"

    if scope == "org":
        return f"{api_prefix}/*"

    if scope == "agent" and agent_id:
        base = f"{api_prefix}/{stage}/*/v1/agents/{agent_id}"
        return [base, f"{base}/*"]

    if scope == "channel" and agent_id and channel_id:
        base = f"{api_prefix}/{stage}/*/v1/agents/{agent_id}/channels/{channel_id}"
        return [base, f"{base}/*"]

    return method_arn


def lambda_handler(event, context):
    token = event.get("authorizationToken", "")
    method_arn = event.get("methodArn", "")
    # API Gateway TOKEN format: Bearer <key>  or  raw <key>
    raw = token.replace("Bearer ", "").strip()
    method, path = _method_and_path(event)
    try:
        ctx = authorize(
            repo=get_repo(), raw_api_key=raw,
            requested_path=path, requested_method=method,
        )
    except DeniedError:
        raise Exception("Unauthorized")
    return {
        "principalId": ctx.api_key_id or "anon",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "execute-api:Invoke",
                "Effect": "Allow",
                "Resource": _resource_policy_arns(
                    method_arn,
                    scope=ctx.scope,
                    agent_id=ctx.agent_id,
                    channel_id=ctx.channel_id,
                ),
            }],
        },
        "context": {
            "org_id": ctx.org_id,
            "scope": ctx.scope,
            "agent_id": ctx.agent_id or "",
            "channel_id": ctx.channel_id or "",
            "api_key_id": ctx.api_key_id or "",
        },
    }
