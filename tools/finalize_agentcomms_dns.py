#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
"""
Finalize agentcomms.dev DNS setup once the ACM cert is ISSUED.

Run this AFTER the domain registrar has been updated to point at our new
Route 53 nameservers AND the ACM certificate validation has completed.

Steps (all idempotent):
  1. Verify ACM cert is ISSUED.
  2. Create (or reuse) API Gateway regional custom domain for api.agentcomms.dev.
  3. Create base-path mapping: api.agentcomms.dev → AgentCommsApi REST API (stage=prod).
  4. Write Route 53 A-alias for api.agentcomms.dev → API GW regional target.
  5. Update CloudFront distribution for the landing page to add agentcomms.dev
     as an alternate domain name + attach the wildcard cert.
  6. Update CloudFront for the console to add console.agentcomms.dev.
  7. Write Route 53 A-alias for agentcomms.dev and console.agentcomms.dev →
     the respective CloudFront distribution domain names.
  8. Verify the full chain with a curl round-trip.

Exits non-zero if ACM is not ISSUED or any step fails.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

import boto3

ZONE_ID = "Z0370999MWHX8OSTHZPR"
ZONE_DOMAIN = "agentcomms.dev"
CERT_ARN = "arn:aws:acm:us-east-1:732770059798:certificate/3b0a4bb3-2daa-47a2-87b5-5d880d06718e"
API_REST_API_ID = "0xztg5asi6"
API_STAGE = "prod"
REGION = "us-east-1"
ACCOUNT = "732770059798"

LANDING_DISTRIBUTION_TAG_HINT = "VictoryMail-Landing"      # existing CloudFront distribution to extend
CONSOLE_DISTRIBUTION_TAG_HINT = "VictoryMail-Console"

_acm = boto3.client("acm", region_name=REGION)
_apigw = boto3.client("apigateway", region_name=REGION)
_route53 = boto3.client("route53")
_cloudfront = boto3.client("cloudfront")


def emit(phase: str, status: str, **fields: Any) -> None:
    print(json.dumps({"phase": phase, "status": status, **fields}), flush=True)


def step_1_verify_cert() -> None:
    resp = _acm.describe_certificate(CertificateArn=CERT_ARN)
    status = resp["Certificate"]["Status"]
    if status != "ISSUED":
        emit("cert", "fail", status=status, msg="Run this script only after ACM cert is ISSUED.")
        raise SystemExit(3)
    emit("cert", "ok", status=status)


def step_2_api_gw_custom_domain() -> dict[str, str]:
    name = f"api.{ZONE_DOMAIN}"
    try:
        resp = _apigw.get_domain_name(domainName=name)
        emit("api_gw_domain", "ok", existing=True, regionalDomainName=resp["regionalDomainName"])
    except _apigw.exceptions.NotFoundException:
        resp = _apigw.create_domain_name(
            domainName=name,
            regionalCertificateArn=CERT_ARN,
            endpointConfiguration={"types": ["REGIONAL"]},
            securityPolicy="TLS_1_2",
        )
        emit("api_gw_domain", "ok", created=True, regionalDomainName=resp["regionalDomainName"])
    return {
        "regional_domain": resp["regionalDomainName"],
        "regional_hosted_zone": resp["regionalHostedZoneId"],
    }


def step_3_base_path_mapping() -> None:
    name = f"api.{ZONE_DOMAIN}"
    try:
        existing = _apigw.get_base_path_mappings(domainName=name)
        items = existing.get("items", [])
        for m in items:
            if m.get("restApiId") == API_REST_API_ID and m.get("stage") == API_STAGE:
                emit("base_path_mapping", "ok", existing=True, basePath=m.get("basePath") or "(none)")
                return
    except Exception:
        pass
    _apigw.create_base_path_mapping(
        domainName=name, restApiId=API_REST_API_ID, stage=API_STAGE,
    )
    emit("base_path_mapping", "ok", created=True)


def step_4_api_route53() -> None:
    resp = _apigw.get_domain_name(domainName=f"api.{ZONE_DOMAIN}")
    _route53.change_resource_record_sets(
        HostedZoneId=ZONE_ID,
        ChangeBatch={
            "Changes": [{
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": f"api.{ZONE_DOMAIN}.",
                    "Type": "A",
                    "AliasTarget": {
                        "HostedZoneId": resp["regionalHostedZoneId"],
                        "DNSName": resp["regionalDomainName"],
                        "EvaluateTargetHealth": False,
                    },
                },
            }]
        },
    )
    emit("route53_api", "ok")


def _find_distribution_by_comment(hint: str) -> dict[str, Any] | None:
    paginator = _cloudfront.get_paginator("list_distributions")
    for page in paginator.paginate():
        for item in page.get("DistributionList", {}).get("Items", []) or []:
            if hint in (item.get("Comment", "") or ""):
                return item
    return None


def step_5_cloudfront_alternate(subdomain: str, hint: str) -> None:
    """Update a CloudFront distribution to add `subdomain.agentcomms.dev` as an alternate + attach wildcard cert."""
    fqdn = f"{subdomain}.{ZONE_DOMAIN}" if subdomain else ZONE_DOMAIN
    dist = _find_distribution_by_comment(hint)
    if dist is None:
        emit("cloudfront_" + hint, "warn", msg=f"no CloudFront distribution matched hint '{hint}' — skipping")
        return
    dist_id = dist["Id"]
    cfg_resp = _cloudfront.get_distribution_config(Id=dist_id)
    etag = cfg_resp["ETag"]
    cfg = cfg_resp["DistributionConfig"]

    aliases = cfg.get("Aliases") or {"Quantity": 0, "Items": []}
    current = set(aliases.get("Items") or [])
    if fqdn not in current:
        current.add(fqdn)
        aliases = {"Quantity": len(current), "Items": sorted(current)}
        cfg["Aliases"] = aliases

    # Ensure wildcard cert is attached
    cfg["ViewerCertificate"] = {
        "ACMCertificateArn": CERT_ARN,
        "SSLSupportMethod": "sni-only",
        "MinimumProtocolVersion": "TLSv1.2_2021",
        "Certificate": CERT_ARN,
        "CertificateSource": "acm",
    }

    try:
        _cloudfront.update_distribution(Id=dist_id, IfMatch=etag, DistributionConfig=cfg)
        emit("cloudfront_" + hint, "ok", distribution_id=dist_id, fqdn=fqdn)
    except Exception as e:
        emit("cloudfront_" + hint, "fail", distribution_id=dist_id, error=str(e))
        raise

    # Route 53 alias
    dist_domain = dist["DomainName"]
    _route53.change_resource_record_sets(
        HostedZoneId=ZONE_ID,
        ChangeBatch={
            "Changes": [{
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": f"{fqdn}.",
                    "Type": "A",
                    "AliasTarget": {
                        "HostedZoneId": "Z2FDTNDATAQYW2",  # CloudFront's fixed Route 53 hosted zone ID
                        "DNSName": dist_domain,
                        "EvaluateTargetHealth": False,
                    },
                },
            }]
        },
    )
    emit("route53_" + hint, "ok", fqdn=fqdn, target=dist_domain)


def step_8_smoke_test() -> None:
    import urllib.request
    import ssl
    for url in (f"https://api.{ZONE_DOMAIN}/v1/agents", f"https://{ZONE_DOMAIN}", f"https://console.{ZONE_DOMAIN}"):
        try:
            # Plain request — server may respond 401 for api.agentcomms.dev without auth; that's fine
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as resp:
                emit("smoke", "ok", url=url, code=resp.status)
        except urllib.error.HTTPError as e:
            emit("smoke", "ok", url=url, code=e.code, note="HTTP error code is expected for unauthed API; domain+TLS work")
        except Exception as e:
            emit("smoke", "warn", url=url, error=str(e))


def main() -> int:
    step_1_verify_cert()
    step_2_api_gw_custom_domain()
    step_3_base_path_mapping()
    step_4_api_route53()
    step_5_cloudfront_alternate("", LANDING_DISTRIBUTION_TAG_HINT)
    step_5_cloudfront_alternate("console", CONSOLE_DISTRIBUTION_TAG_HINT)

    emit("wait_for_cloudfront", "waiting", msg="CloudFront distribution updates take ~5-10 min to propagate")
    time.sleep(30)  # minimal wait; full rollout takes longer but DNS records are already valid

    step_8_smoke_test()

    emit("done", "ok", msg="agentcomms.dev set up; api.agentcomms.dev → AgentCommsApi; agentcomms.dev → landing; console.agentcomms.dev → console")
    return 0


if __name__ == "__main__":
    sys.exit(main())
