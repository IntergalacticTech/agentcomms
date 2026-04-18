# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/api/domains_handler.py
"""Domains API handler — org-scoped email domain SES identity lifecycle.

Routes (all org-scoped, NOT nested under agents):
  POST   /v1/domains                   — register domain with SES Easy DKIM
  GET    /v1/domains                   — list
  GET    /v1/domains/{id}              — get (with live SES verification status)
  POST   /v1/domains/{id}/verify       — force-poll SES now; return current status
  GET    /v1/domains/{id}/zone-file    — BIND-format zone file (text/plain)
  DELETE /v1/domains/{id}              — delete from SES + DB (409 if in-use)

TODO: scheduled poller Lambda (core/api/domains_poller.py) — deferred to a
follow-up task. The poller will periodically call `get_email_identity` for
all pending domains and advance their status.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3

from core.api._common import (
    Caller, err, get_repo, no_content, ok, parse_body, require_org_scope,
)
from core.data.models import Domain, DomainStatus
from core.data.ulid_ import new_id


# ---------------------------------------------------------------------------
# SES client (lazy singleton)
# ---------------------------------------------------------------------------

_sesv2 = None


def _get_sesv2():
    global _sesv2
    if _sesv2 is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _sesv2 = boto3.client("sesv2", region_name=region)
    return _sesv2


# ---------------------------------------------------------------------------
# DNS record builders
# ---------------------------------------------------------------------------

def _build_dns_records(domain_name: str, dkim_tokens: list[str]) -> dict:
    """Build the DNS record map a user must publish."""
    return {
        "mx": {
            "type": "MX",
            "name": domain_name,
            "value": "10 inbound-smtp.us-east-1.amazonaws.com",
            "ttl": 1800,
        },
        "spf": {
            "type": "TXT",
            "name": domain_name,
            "value": "v=spf1 include:amazonses.com ~all",
            "ttl": 3600,
        },
        "dkim": [
            {
                "type": "CNAME",
                "name": f"{tok}._domainkey.{domain_name}",
                "value": f"{tok}.dkim.amazonses.com",
                "ttl": 1800,
            }
            for tok in dkim_tokens
        ],
        "dmarc": {
            "type": "TXT",
            "name": f"_dmarc.{domain_name}",
            "value": f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain_name}",
            "ttl": 3600,
        },
    }


def _build_zone_file(domain_name: str, dns_records: dict) -> str:
    """Render dns_records as a BIND-format zone file."""
    lines = [
        f"$ORIGIN {domain_name}.",
        "$TTL 3600",
        "",
    ]
    mx = dns_records["mx"]
    lines.append(f"{mx['name']}.    {mx['ttl']}    IN    MX    {mx['value']}")
    lines.append("")

    spf = dns_records["spf"]
    lines.append(f'{spf["name"]}.    {spf["ttl"]}    IN    TXT    "{spf["value"]}"')
    lines.append("")

    for dkim in dns_records.get("dkim", []):
        lines.append(f'{dkim["name"]}.    {dkim["ttl"]}    IN    CNAME    {dkim["value"]}.')
    lines.append("")

    dmarc = dns_records["dmarc"]
    lines.append(f'{dmarc["name"]}.    {dmarc["ttl"]}    IN    TXT    "{dmarc["value"]}"')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------

def _domain_response(d: Domain) -> dict:
    return {
        "domain_id": d.domain_id,
        "org_id": d.org_id,
        "domain_name": d.domain_name,
        "status": d.status.value,
        "dkim_tokens": d.dkim_tokens,
        "spf_verified": d.spf_verified,
        "mx_verified": d.mx_verified,
        "dmarc_verified": d.dmarc_verified,
        "dns_records": d.dns_records,
        "verified_at": d.verified_at.isoformat() if d.verified_at else None,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Route implementations
# ---------------------------------------------------------------------------

def _create(caller: Caller, body: dict, repo) -> dict:
    domain_name = (body.get("domain_name") or "").strip().lower()
    if not domain_name or "." not in domain_name:
        return err("'domain_name' must be a fully-qualified domain name")

    # Cross-org uniqueness check via GSI7
    existing_ownership = repo.lookup_domain_ownership(domain_name)
    if existing_ownership and existing_ownership.org_id != caller.org_id:
        return err(
            f"Domain '{domain_name}' is already registered by another organisation.",
            status=409,
        )
    # Same org re-registers — idempotent; fall through to create/update

    # Register with SES Easy DKIM
    sesv2 = _get_sesv2()
    try:
        resp = sesv2.create_email_identity(
            EmailIdentity=domain_name,
            DkimSigningAttributes={"NextSigningKeyLength": "RSA_2048_BIT"},
        )
        dkim_tokens = resp.get("DkimAttributes", {}).get("Tokens") or []
    except sesv2.exceptions.AlreadyExistsException:
        # Re-fetch existing tokens
        resp = sesv2.get_email_identity(EmailIdentity=domain_name)
        dkim_tokens = resp.get("DkimAttributes", {}).get("Tokens") or []
    except Exception as exc:
        return err(f"SES error: {exc}", status=502)

    if not dkim_tokens:
        return err("SES did not return DKIM tokens; please retry.", status=502)

    dns_records = _build_dns_records(domain_name, dkim_tokens)
    domain_id = new_id("dom")
    now = datetime.now(timezone.utc)
    domain = Domain(
        domain_id=domain_id,
        org_id=caller.org_id,
        domain_name=domain_name,
        status=DomainStatus.PENDING_DNS,
        dkim_tokens=dkim_tokens,
        dns_records=dns_records,
        created_at=now,
        updated_at=now,
    )
    repo.put_domain(domain)
    return ok(_domain_response(domain), status=201)


def _list(caller: Caller, event: dict, repo) -> dict:
    qs = event.get("queryStringParameters") or {}
    limit = int(qs.get("limit", 100))
    domains = repo.list_domains(org_id=caller.org_id, limit=limit)
    return ok({"domains": [_domain_response(d) for d in domains]})


def _get(caller: Caller, domain_id: str, repo) -> dict:
    domain = repo.get_domain(org_id=caller.org_id, domain_id=domain_id)
    if not domain:
        return err("Domain not found", status=404)
    return ok(_domain_response(domain))


def _verify(caller: Caller, domain_id: str, repo) -> dict:
    """Force-poll SES for current verification state; persist + return status."""
    domain = repo.get_domain(org_id=caller.org_id, domain_id=domain_id)
    if not domain:
        return err("Domain not found", status=404)

    sesv2 = _get_sesv2()
    try:
        resp = sesv2.get_email_identity(EmailIdentity=domain.domain_name)
    except Exception as exc:
        return err(f"SES error: {exc}", status=502)

    verified_for_sending = bool(resp.get("VerifiedForSendingStatus", False))
    dkim_status = resp.get("DkimAttributes", {}).get("Status", "NOT_STARTED")

    now = datetime.now(timezone.utc)
    updates: dict = {"updated_at": now}

    if verified_for_sending and dkim_status == "SUCCESS":
        updates["status"] = DomainStatus.VERIFIED
        updates["spf_verified"] = True
        updates["mx_verified"] = True
        updates["dmarc_verified"] = True
        if not domain.verified_at:
            updates["verified_at"] = now
    elif dkim_status in ("PENDING", "NOT_STARTED"):
        updates["status"] = DomainStatus.PENDING_DKIM
    else:
        updates["status"] = DomainStatus.FAILED

    updated = domain.model_copy(update=updates)
    repo.put_domain(updated)
    return ok(_domain_response(updated))


def _zone_file(caller: Caller, domain_id: str, repo) -> dict:
    domain = repo.get_domain(org_id=caller.org_id, domain_id=domain_id)
    if not domain:
        return err("Domain not found", status=404)

    zone_text = _build_zone_file(domain.domain_name, domain.dns_records)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/plain"},
        "body": zone_text,
    }


def _delete(caller: Caller, domain_id: str, repo) -> dict:
    domain = repo.get_domain(org_id=caller.org_id, domain_id=domain_id)
    if not domain:
        return err("Domain not found", status=404)

    # Check for active channels that reference this domain via their config
    # A channel is "using" a domain when channel.config.domain_name == domain.domain_name
    # We check all agent channels in this org by scanning channels with email type
    channels = _find_channels_using_domain(caller.org_id, domain.domain_name, repo)
    if channels:
        return err(
            f"Domain is in use by {len(channels)} active channel(s). "
            "Remove those channels first.",
            status=409,
        )

    sesv2 = _get_sesv2()
    try:
        sesv2.delete_email_identity(EmailIdentity=domain.domain_name)
    except Exception:
        # Log but don't block — the DynamoDB record is authoritative
        pass

    repo.delete_domain(org_id=caller.org_id, domain_id=domain_id)
    return no_content()


def _find_channels_using_domain(org_id: str, domain_name: str, repo) -> list:
    """Return all agent channels whose email address ends with @domain_name."""
    from boto3.dynamodb.conditions import Key

    # Scan all agents in org, then check each agent's email channels
    agents = repo.list_agents(org_id=org_id)
    using = []
    for agent in agents:
        channels = repo.list_channels(agent_id=agent.agent_id)
        for ch in channels:
            # Email channels store address in config; check if it uses this domain
            addr = ch.config.get("address") or ch.config.get("domain_name") or ""
            if addr.endswith(f"@{domain_name}") or addr == domain_name:
                using.append(ch)
    return using


# ---------------------------------------------------------------------------
# Lambda entry-point
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    caller = Caller.from_event(event)

    if denied := require_org_scope(caller):
        return denied

    method = event.get("httpMethod", "")
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}
    domain_id = pp.get("domain_id") or pp.get("id", "")

    repo = get_repo()

    # Sub-routes on a specific domain
    if domain_id:
        if method == "POST" and path.endswith("/verify"):
            return _verify(caller, domain_id, repo)
        if method == "GET" and path.endswith("/zone-file"):
            return _zone_file(caller, domain_id, repo)
        if method == "GET":
            return _get(caller, domain_id, repo)
        if method == "DELETE":
            return _delete(caller, domain_id, repo)

    # Collection routes
    if method == "GET":
        return _list(caller, event, repo)
    if method == "POST":
        body = parse_body(event)
        return _create(caller, body, repo)

    return err("Not found", status=404)
