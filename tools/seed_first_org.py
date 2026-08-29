#!/usr/bin/env python3
"""Seed the first Organization + admin API key into the agentcomms table.

Run once after Phase 1 deploy. Outputs the plaintext API key exactly once.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys

import boto3

# Allow running from repo root without install.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.models import ApiKey, ApiKeyScope, Organization, OrgPlan
from core.data.repo import Repo
from core.data.ulid_ import new_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org-name", default="Victory")
    ap.add_argument("--plan", default="enterprise")
    ap.add_argument("--table", default=os.environ.get("AGENTCOMMS_TABLE", "agentcomms"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = ap.parse_args()

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)
    repo = Repo(table)

    org_id = new_id("org")
    org = Organization(
        org_id=org_id,
        name=args.org_name,
        plan=OrgPlan(args.plan),
    )
    repo.put_organization(org)

    plaintext = "ak_live_" + secrets.token_urlsafe(32).replace("_", "").replace("-", "")[:40]
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    api_key = ApiKey(
        key_id=new_id("key"),
        key_hash=key_hash,
        key_prefix=plaintext[:12],
        org_id=org_id,
        scope=ApiKeyScope.ORG,
        name="bootstrap-admin",
    )
    table.put_item(Item=api_key.to_dynamodb_item())

    print(f"org_id:    {org_id}")
    print(f"key_id:    {api_key.key_id}")
    print(f"api_key:   {plaintext}")
    print()
    print("Store the api_key — it is shown only once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
