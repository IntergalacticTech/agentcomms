# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

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
    # Resource wildcard: allow the caller (via this cached policy) to call any
    # method on any path under this API. method_arn format:
    #   arn:aws:execute-api:REGION:ACCOUNT:API-ID/STAGE/METHOD/PATH...
    # We keep `arn:...:API-ID/` and append `*` which matches any STAGE/METHOD/PATH.
    api_prefix = method_arn.split("/", 1)[0]  # arn:...:API-ID
    return {
        "principalId": ctx.api_key_id or "anon",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "execute-api:Invoke",
                "Effect": "Allow",
                "Resource": f"{api_prefix}/*",
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
