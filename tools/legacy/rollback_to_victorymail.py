#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""
Rollback AgentComms → victorymail for a 24-hour window.

CAVEATS:
  - ONLY meaningful within 24 hours of cutover. After that, too much new activity
    has happened in agentcomms to reverse-map cleanly.
  - Does NOT reverse S3 object migrations (they're still available at the new
    bucket locations; the old bucket references still work).
  - Does NOT reverse Stripe subscription migrations (use Stripe dashboard if needed).
  - Does NOT automatically flip DNS. After this script exits, operator runs:
      aws route53 change-resource-record-sets --hosted-zone-id $ZONE \\
        --change-batch file://tools/rollback-dns-batch.json

Usage:
    python tools/rollback_to_victorymail.py \\
        --source-table agentcomms \\
        --dest-table victorymail \\
        --cutover-timestamp 2026-07-17T14:00:00Z \\
        [--dry-run] \\
        [--json] \\
        [--region us-east-1]

Exit codes:
    0 — success (or dry-run complete)
    1 — fatal error
    2 — partial success (some items failed; check log)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Generator

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("rollback")

_use_json = False  # toggled by --json


def _emit(kind: str, **fields: Any) -> None:
    record = {"event": kind, **fields}
    print(json.dumps(record, default=str), flush=True)


def _log(kind: str, **fields: Any) -> None:
    """Write to stdout (NDJSON or human) AND to the rollback log file."""
    if _use_json:
        _emit(kind, **fields)
    else:
        parts = " ".join(f"{k}={v}" for k, v in fields.items())
        print(f"[{kind}] {parts}", flush=True)

    # Also append to the log file (non-dry-run only; set by caller)
    if _log_fh is not None:
        record = {"event": kind, **fields}
        _log_fh.write(json.dumps(record, default=str) + "\n")
        _log_fh.flush()


_log_fh = None  # file handle opened after arg parse


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _paginate_scan(table: Any, filter_expr=None) -> Generator[dict, None, None]:
    """Yield every item from a DynamoDB table scan."""
    kwargs: dict = {}
    if filter_expr is not None:
        kwargs["FilterExpression"] = filter_expr
    while True:
        resp = table.scan(**kwargs)
        yield from resp.get("Items", [])
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last


def _safe_put(table: Any, item: dict, dry_run: bool) -> bool:
    """
    Write item to table with attribute_not_exists guard (idempotent).
    Returns True on success, False on skip (already exists), raises on error.
    """
    if dry_run:
        return True
    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False  # already exists — idempotent skip
        raise


# ---------------------------------------------------------------------------
# Reverse-transform functions
#
# Only four entity types are reverse-mapped because those are the only entities
# that could have been newly created during the dual-run window (T+0 → T+cutover):
#   1. UnifiedMessage (agentcomms) → Message (victorymail)
#   2. Agent (agentcomms)          → Inbox (victorymail)   [only if newly created]
#   3. Channel (agentcomms, email) → (ignored; inboxes have address inline)
#   4. Domain (agentcomms)         → Domain (victorymail)
#
# Items that already existed before cutover were migrated forward by
# migrate_victorymail_to_agentcomms.py and are left in place in victorymail.
# ---------------------------------------------------------------------------

def _reverse_unified_message(item: dict) -> dict | None:
    """
    UnifiedMessage → legacy Message shape.

    PK: ORG#{org_id}  SK: MSG#{msg_id}   entity: unified_message
    →
    PK: ORG#{org_id}  SK: MSG#{msg_id}   entity: message
    """
    if item.get("entity") != "unified_message":
        return None

    msg = {
        "PK":           item["PK"],
        "SK":           item["SK"],
        "entity":       "message",
        "message_id":   item.get("message_id", ""),
        "org_id":       item.get("org_id", ""),
        "created_at":   item.get("created_at", ""),
        "updated_at":   item.get("updated_at", item.get("created_at", "")),
        "direction":    item.get("direction", "inbound"),
        "status":       item.get("status", "received"),
        "subject":      item.get("subject", ""),
        "body_text":    item.get("body_text", ""),
        "body_html":    item.get("body_html", ""),
        "from_address": item.get("from_address", ""),
        "to_addresses": item.get("to_addresses", []),
        "thread_id":    item.get("thread_id"),
        "ses_message_id": item.get("ses_message_id"),
        "in_reply_to":  item.get("in_reply_to"),
        "references":   item.get("references", []),
    }

    # inbox_id: agentcomms stores agent_id (agt_…); reverse to inb_…
    agent_id = item.get("agent_id", "")
    if agent_id.startswith("agt_"):
        msg["inbox_id"] = "inb_" + agent_id[4:]
    else:
        msg["inbox_id"] = agent_id

    # GSI mirrors (victorymail uses UPPER-case GSI key names)
    org_id  = item.get("org_id", "")
    msg_id  = item.get("message_id", "")
    inbox_id = msg["inbox_id"]
    msg["GSI1PK"] = f"ORG#{org_id}"
    msg["GSI1SK"] = f"MSG#{msg_id}"
    msg["GSI2PK"] = f"INBOX#{inbox_id}"
    msg["GSI2SK"] = f"MSG#{msg_id}"

    return msg


def _reverse_agent(item: dict) -> dict | None:
    """
    Agent → legacy Inbox shape.

    PK: ORG#{org_id}  SK: AGENT#{agent_id}   entity: agent
    →
    PK: ORG#{org_id}  SK: INBOX#{inbox_id}   entity: inbox
    """
    if item.get("entity") != "agent":
        return None

    agent_id = item.get("agent_id", "")
    if agent_id.startswith("agt_"):
        inbox_id = "inb_" + agent_id[4:]
    else:
        inbox_id = agent_id

    org_id = item.get("org_id", "")
    inbox = {
        "PK":           f"ORG#{org_id}",
        "SK":           f"INBOX#{inbox_id}",
        "entity":       "inbox",
        "inbox_id":     inbox_id,
        "org_id":       org_id,
        "display_name": item.get("display_name", item.get("name", "")),
        "created_at":   item.get("created_at", ""),
        "updated_at":   item.get("updated_at", item.get("created_at", "")),
        # address and domain_id are stored on the email Channel; leave blank here
        # — they'll be populated from any reverse-mapped Channel records.
        "address":      "",
        "domain_id":    "",
    }
    inbox["GSI1PK"] = f"ORG#{org_id}"
    inbox["GSI1SK"] = f"INBOX#{inbox_id}"

    return inbox


def _reverse_domain(item: dict) -> dict | None:
    """
    Domain (agentcomms) → Domain (victorymail).

    Schema is mostly identical; only key name differences.
    """
    if item.get("entity") != "domain":
        return None

    org_id    = item.get("org_id", "")
    domain_id = item.get("domain_id", "")

    domain = {
        "PK":             f"ORG#{org_id}",
        "SK":             f"DOMAIN#{domain_id}",
        "entity":         "domain",
        "domain_id":      domain_id,
        "org_id":         org_id,
        "domain":         item.get("domain", ""),
        "status":         item.get("status", "pending"),
        "dkim_tokens":    item.get("dkim_tokens", []),
        "created_at":     item.get("created_at", ""),
        "updated_at":     item.get("updated_at", item.get("created_at", "")),
        "GSI1PK":         f"ORG#{org_id}",
        "GSI1SK":         f"DOMAIN#{domain_id}",
    }
    return domain


def _reverse_channel(item: dict) -> dict | None:
    """
    Channel (agentcomms, email type only) → patch Inbox address + domain_id.

    Returns a partial dict: {"_patch_inbox": inbox_id, "address": ..., "domain_id": ...}
    Caller handles the patch separately.
    """
    if item.get("entity") != "channel":
        return None
    if item.get("channel_type") not in ("email", "EMAIL"):
        return None  # SMS/Slack channels have no victorymail equivalent

    agent_id = item.get("agent_id", "")
    if agent_id.startswith("agt_"):
        inbox_id = "inb_" + agent_id[4:]
    else:
        inbox_id = agent_id

    return {
        "_patch_inbox": inbox_id,
        "org_id":       item.get("org_id", ""),
        "address":      item.get("address", ""),
        "domain_id":    item.get("domain_id", ""),
    }


# ---------------------------------------------------------------------------
# Main rollback logic
# ---------------------------------------------------------------------------

_REVERSE_FNS = [_reverse_unified_message, _reverse_agent, _reverse_domain]


def run_rollback(
    source_table: Any,
    dest_table: Any,
    cutover_ts: datetime,
    dry_run: bool,
) -> int:
    """
    Scan source_table for items created after cutover_ts, reverse-transform
    them, write to dest_table.  Returns exit code (0=ok, 2=partial).
    """
    _log("rollback_start",
         dry_run=dry_run,
         cutover_timestamp=cutover_ts.isoformat(),
         source=source_table.name,
         dest=dest_table.name)

    cutover_str = cutover_ts.isoformat()

    # Scan for new items
    filter_expr = Attr("created_at").gt(cutover_str)
    items = list(_paginate_scan(source_table, filter_expr=filter_expr))

    _log("scan_complete", count=len(items))

    # Separate channels for patching
    inbox_patches: dict[str, dict] = {}   # inbox_id → {address, domain_id, org_id}
    reverse_items: list[dict] = []

    for item in items:
        ch = _reverse_channel(item)
        if ch is not None:
            inbox_id = ch["_patch_inbox"]
            inbox_patches[inbox_id] = {
                "org_id":    ch["org_id"],
                "address":   ch["address"],
                "domain_id": ch["domain_id"],
            }
            continue

        for fn in _REVERSE_FNS:
            out = fn(item)
            if out is not None:
                reverse_items.append(out)
                break

    _log("reverse_mapped", total=len(reverse_items), inbox_patches=len(inbox_patches))

    ok = 0
    skip = 0
    fail = 0

    # Write reverse-mapped items
    for item in reverse_items:
        try:
            written = _safe_put(dest_table, item, dry_run)
            if written:
                ok += 1
                _log("write_ok", entity=item.get("entity"), pk=item.get("PK"), sk=item.get("SK"))
            else:
                skip += 1
                _log("write_skipped", entity=item.get("entity"), pk=item.get("PK"), sk=item.get("SK"))
        except ClientError as exc:
            fail += 1
            _log("write_error", entity=item.get("entity"), pk=item.get("PK"),
                 sk=item.get("SK"), error=str(exc))

    # Apply inbox address patches (update address + domain_id on reversed Inboxes)
    for inbox_id, patch in inbox_patches.items():
        org_id = patch["org_id"]
        pk = f"ORG#{org_id}"
        sk = f"INBOX#{inbox_id}"
        if dry_run:
            _log("patch_inbox_dryrun", pk=pk, sk=sk, address=patch["address"])
            ok += 1
            continue
        try:
            dest_table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET address = :a, domain_id = :d",
                ExpressionAttributeValues={":a": patch["address"], ":d": patch["domain_id"]},
                ConditionExpression="attribute_exists(PK)",
            )
            ok += 1
            _log("patch_inbox_ok", pk=pk, sk=sk, address=patch["address"])
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                _log("patch_inbox_not_found", pk=pk, sk=sk)
            else:
                fail += 1
                _log("patch_inbox_error", pk=pk, sk=sk, error=str(exc))

    _log("rollback_complete", written=ok, skipped=skip, failed=fail)

    # Operator instructions
    _log("operator_action_required",
         message=(
             "Rollback data phase complete. To finish the rollback:\n"
             "  1. Verify the victorymail table has the expected items.\n"
             "  2. Flip api.victorymail.dev DNS back to the old API Gateway:\n"
             "       aws route53 change-resource-record-sets "
             "--hosted-zone-id $HOSTED_ZONE_ID \\\n"
             "         --change-batch file://tools/rollback-dns-batch.json\n"
             "  3. Wait for CloudFront cache purge (~5 min) and DNS TTL (~60 s).\n"
             "  4. Smoke-test api.victorymail.dev.\n"
             "  5. If smoke tests pass, update status page."
         ))

    return 2 if fail > 0 else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Rollback AgentComms → victorymail (24-hour window only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--source-table",       default="agentcomms",
                   help="AgentComms DynamoDB table name (default: agentcomms)")
    p.add_argument("--dest-table",         default="victorymail",
                   help="victorymail DynamoDB table name (default: victorymail)")
    p.add_argument("--cutover-timestamp",  required=True,
                   help="ISO 8601 cutover moment; only items created AFTER this are reversed")
    p.add_argument("--dry-run",            action="store_true",
                   help="Print what would be written; do not modify the destination table")
    p.add_argument("--json",               action="store_true",
                   help="Emit NDJSON lines to stdout instead of human-readable output")
    p.add_argument("--region",             default="us-east-1")
    p.add_argument("--log-file",           default=None,
                   help="Override log file path (default: /tmp/rollback-<ts>.log)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    global _use_json, _log_fh

    args = _parse_args(argv)
    _use_json = args.json

    # Parse cutover timestamp
    try:
        cutover_ts = datetime.fromisoformat(args.cutover_timestamp.replace("Z", "+00:00"))
        if cutover_ts.tzinfo is None:
            cutover_ts = cutover_ts.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        print(f"ERROR: invalid --cutover-timestamp: {exc}", file=sys.stderr)
        return 1

    # Open rollback log
    now_str = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = args.log_file or f"/tmp/rollback-{now_str}.log"
    if not args.dry_run:
        try:
            _log_fh = open(log_path, "w")  # noqa: WPS515
            _log("log_opened", path=log_path)
        except OSError as exc:
            print(f"WARNING: could not open log file {log_path}: {exc}", file=sys.stderr)

    # DynamoDB clients
    boto_kwargs: dict = {"region_name": args.region}
    dynamodb = boto3.resource("dynamodb", **boto_kwargs)
    source_table = dynamodb.Table(args.source_table)
    dest_table   = dynamodb.Table(args.dest_table)

    rc = run_rollback(source_table, dest_table, cutover_ts, dry_run=args.dry_run)

    if _log_fh is not None:
        _log_fh.close()
        if not args.dry_run:
            print(f"\nRollback log written to: {log_path}", file=sys.stderr)

    return rc


if __name__ == "__main__":
    sys.exit(main())
