"""API Gateway TOKEN authorizer entrypoint."""
import os
from core.api.authorizer import authorize, DeniedError, CallerContext
from core.api._common import get_repo


def lambda_handler(event, context):
    token = event.get("authorizationToken", "")
    method_arn = event.get("methodArn", "")
    # API Gateway TOKEN format: Bearer <key>  or  raw <key>
    raw = token.replace("Bearer ", "").strip()
    path = event.get("path") or ""  # if not provided by API GW, parse from methodArn
    method = event.get("httpMethod") or ""
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
                "Resource": method_arn.rsplit("/", 2)[0] + "/*/*",
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
