#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""
Post-migration integrity verifier.

Scans both `victorymail` and `agentcomms` tables, counts entity types,
spot-checks 50 random messages, checks GSI3 and GSI7 projections, and emits
an NDJSON report.  Exit code 0 = all checks pass; non-zero = failures found.

Usage:
    python tools/check_migration_integrity.py
    python tools/check_migration_integrity.py --source-table victorymail \\
        --dest-table agentcomms --spot-check-n 50
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import os
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# NDJSON output
# ---------------------------------------------------------------------------

def _emit(kind: str, **fields: Any) -> None:
    print(json.dumps({"event": kind, **fields}, default=str), flush=True)


# ---------------------------------------------------------------------------
# Scanner helpers
# ---------------------------------------------------------------------------

def _full_scan(table: Any) -> list[dict[str, Any]]:
    """Return all items from a DynamoDB table (handles pagination)."""
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs = {"ExclusiveStartKey": last}
    return items


def _query_gsi(table: Any, index_name: str, pk_value: str, pk_attr: str = "gsi3_pk") -> list[dict[str, Any]]:
    """Query a GSI by its PK value, returning all matching items."""
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "IndexName": index_name,
        "KeyConditionExpression": boto3.dynamodb.conditions.Key(pk_attr).eq(pk_value),
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


# ---------------------------------------------------------------------------
# Source item classifiers
# ---------------------------------------------------------------------------

def _classify_src(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bucket victorymail items by entity type."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "org": [],
        "api_key": [],
        "inbox": [],
        "message": [],
        "thread": [],
        "domain": [],
        "webhook": [],
        "draft": [],
        "attachment": [],
        "pod": [],
        "list": [],
        "other": [],
    }
    for item in items:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        if pk.startswith("ORG#") and (sk == "META" or sk == pk):
            buckets["org"].append(item)
        elif pk.startswith("ORG#") and sk.startswith("APIKEY#"):
            buckets["api_key"].append(item)
        elif pk.startswith("ORG#") and (sk.startswith("INBOX#") or sk.startswith("INB#")):
            buckets["inbox"].append(item)
        elif pk.startswith("INBOX#") and sk.startswith("MSG#"):
            buckets["message"].append(item)
        elif pk.startswith("INBOX#") and sk.startswith("THREAD#"):
            buckets["thread"].append(item)
        elif pk.startswith("ORG#") and (sk.startswith("DOM#") or sk.startswith("DOMAIN#")):
            buckets["domain"].append(item)
        elif (pk.startswith("ORG#") or pk.startswith("INBOX#")) and sk.startswith("WEBHOOK#"):
            buckets["webhook"].append(item)
        elif pk.startswith("INBOX#") and (sk.startswith("DRAFT#") or sk.startswith("DRF#")):
            buckets["draft"].append(item)
        elif pk.startswith("MSG#") and (sk.startswith("ATTACH#") or sk.startswith("ATT#")):
            buckets["attachment"].append(item)
        elif pk.startswith("ORG#") and sk.startswith("POD#"):
            buckets["pod"].append(item)
        elif pk.startswith("LIST#") or (pk.startswith("ORG#") and sk.startswith("LIST#")):
            buckets["list"].append(item)
        else:
            buckets["other"].append(item)
    return buckets


def _classify_dst(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bucket agentcomms items by entity type."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "org": [],
        "api_key": [],
        "agent": [],
        "channel": [],
        "message": [],
        "thread": [],
        "domain": [],
        "webhook": [],
        "draft": [],
        "attachment": [],
        "other": [],
    }
    for item in items:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        entity = item.get("entity", "")
        if entity == "organization" or (pk.startswith("ORG#") and sk == "META"):
            buckets["org"].append(item)
        elif entity == "api_key" or (pk.startswith("ORG#") and sk.startswith("APIKEY#")):
            buckets["api_key"].append(item)
        elif entity == "agent" or (pk.startswith("ORG#") and sk.startswith("AGT#")):
            buckets["agent"].append(item)
        elif entity == "channel" or (pk.startswith("AGT#") and sk.startswith("CHAN#")):
            buckets["channel"].append(item)
        elif entity == "message" or (pk.startswith("AGT#") and sk.startswith("MSG#")):
            buckets["message"].append(item)
        elif entity == "thread" or (pk.startswith("AGT#") and sk.startswith("THR#")):
            buckets["thread"].append(item)
        elif entity == "domain" or (pk.startswith("ORG#") and sk.startswith("DOM#")):
            buckets["domain"].append(item)
        elif entity == "webhook" or (pk.startswith("AGT#") and sk.startswith("WHK#")):
            buckets["webhook"].append(item)
        elif entity == "draft" or (pk.startswith("AGT#") and sk.startswith("DRF#")):
            buckets["draft"].append(item)
        elif entity == "attachment" or (pk.startswith("MSG#") and sk.startswith("ATT#")):
            buckets["attachment"].append(item)
        else:
            buckets["other"].append(item)
    return buckets


# ---------------------------------------------------------------------------
# Normalisation for spot-checks
# ---------------------------------------------------------------------------

def _normalise_src_msg(item: dict[str, Any]) -> dict[str, Any]:
    """Extract the comparable fields from a victorymail message item."""
    from_raw = item.get("from_address") or item.get("from") or {}
    if isinstance(from_raw, str):
        from_addr = from_raw
    elif isinstance(from_raw, dict):
        from_addr = from_raw.get("address", "")
    else:
        from_addr = ""
    return {
        "msg_id": item.get("message_id") or item.get("msg_id") or "",
        "from": from_addr,
        "subject": item.get("subject") or "",
        "body_text": (item.get("body_text") or "").strip(),
        "direction": item.get("direction", "inbound"),
    }


def _normalise_dst_msg(item: dict[str, Any]) -> dict[str, Any]:
    """Extract the comparable fields from an agentcomms message item."""
    from_raw = item.get("from") or {}
    if isinstance(from_raw, dict):
        from_addr = from_raw.get("address", "")
    else:
        from_addr = str(from_raw)
    return {
        "msg_id": item.get("message_id") or "",
        "from": from_addr,
        "subject": item.get("subject") or "",
        "body_text": (item.get("body_text") or "").strip(),
        "direction": item.get("direction", "inbound"),
    }


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def check_counts(
    src_buckets: dict[str, list],
    dst_buckets: dict[str, list],
) -> list[CheckResult]:
    """Verify that expected count ratios hold."""
    results: list[CheckResult] = []

    # 1:1 relationships
    for src_key, dst_key, label in [
        ("org", "org", "organization 1:1"),
        ("api_key", "api_key", "api_key 1:1"),
        ("domain", "domain", "domain 1:1"),
        ("message", "message", "message 1:1"),
        ("thread", "thread", "thread 1:1"),
        ("draft", "draft", "draft 1:1"),
        ("attachment", "attachment", "attachment 1:1"),
    ]:
        s = len(src_buckets[src_key])
        d = len(dst_buckets[dst_key])
        passed = s == d
        results.append(CheckResult(
            name=label,
            passed=passed,
            detail=f"src={s} dst={d}",
        ))
        _emit("count_check", entity=label, src=s, dst=d, passed=passed)

    # Inbox → 1 agent + 1 channel
    inboxes = len(src_buckets["inbox"])
    agents = len(dst_buckets["agent"])
    channels = len(dst_buckets["channel"])
    passed_a = inboxes == agents
    passed_c = inboxes == channels
    results.append(CheckResult(
        "inbox→agent 1:1", passed_a, f"inboxes={inboxes} agents={agents}"
    ))
    results.append(CheckResult(
        "inbox→channel 1:1", passed_c, f"inboxes={inboxes} channels={channels}"
    ))
    _emit("count_check", entity="inbox→agent", src=inboxes, dst=agents, passed=passed_a)
    _emit("count_check", entity="inbox→channel", src=inboxes, dst=channels, passed=passed_c)

    return results


def check_spot_sample(
    src_msgs: list[dict[str, Any]],
    dst_msg_lookup: dict[str, dict[str, Any]],
    n: int,
) -> list[CheckResult]:
    """Randomly sample n messages and compare normalised forms."""
    results: list[CheckResult] = []
    sample = random.sample(src_msgs, min(n, len(src_msgs)))
    mismatches = 0
    checked = 0

    for src_item in sample:
        msg_id = src_item.get("message_id") or src_item.get("msg_id") or ""
        if not msg_id:
            continue
        checked += 1
        dst_item = dst_msg_lookup.get(msg_id)
        if dst_item is None:
            _emit(
                "spot_check_miss",
                msg_id=msg_id,
                detail="message not found in destination",
            )
            mismatches += 1
            continue
        src_norm = _normalise_src_msg(src_item)
        dst_norm = _normalise_dst_msg(dst_item)
        if src_norm != dst_norm:
            _emit(
                "spot_check_mismatch",
                msg_id=msg_id,
                src=src_norm,
                dst=dst_norm,
            )
            mismatches += 1

    passed = mismatches == 0
    results.append(CheckResult(
        name=f"spot_check_messages (n={checked})",
        passed=passed,
        detail=f"mismatches={mismatches}",
    ))
    _emit(
        "spot_check_done",
        checked=checked,
        mismatches=mismatches,
        passed=passed,
    )
    return results


def check_gsi3_dm_counts(
    dst_table: Any,
    dst_agents: list[dict[str, Any]],
    dst_msg_by_agent: dict[str, list[dict[str, Any]]],
) -> list[CheckResult]:
    """Check GSI3 (unified inbox) returns expected count of DM messages per agent."""
    results: list[CheckResult] = []
    for agent in dst_agents[:20]:  # cap at 20 agents for speed
        agent_id = agent.get("agent_id", "")
        if not agent_id:
            continue
        expected_dm_count = sum(
            1 for m in dst_msg_by_agent.get(agent_id, []) if m.get("is_dm")
        )
        gsi3_items = _query_gsi(
            dst_table, "GSI3", f"AGT_DM#{agent_id}", pk_attr="gsi3_pk"
        )
        actual = len(gsi3_items)
        passed = actual == expected_dm_count
        if not passed:
            _emit(
                "gsi3_mismatch",
                agent_id=agent_id,
                expected=expected_dm_count,
                actual=actual,
            )
        results.append(CheckResult(
            name=f"gsi3_dm_count::{agent_id}",
            passed=passed,
            detail=f"expected={expected_dm_count} gsi3={actual}",
        ))
    return results


def check_gsi7_domain_uniqueness(
    dst_table: Any,
    dst_domains: list[dict[str, Any]],
) -> list[CheckResult]:
    """Check GSI7 returns each domain exactly once."""
    results: list[CheckResult] = []
    seen_domain_names: set[str] = set()
    for dom in dst_domains:
        domain_name = dom.get("domain_name") or dom.get("name") or ""
        if not domain_name or domain_name in seen_domain_names:
            continue
        seen_domain_names.add(domain_name)
        gsi7_items = _query_gsi(
            dst_table, "GSI7", f"DOMAIN#{domain_name}", pk_attr="gsi7_pk"
        )
        passed = len(gsi7_items) == 1
        if not passed:
            _emit(
                "gsi7_duplicate",
                domain_name=domain_name,
                count=len(gsi7_items),
            )
        results.append(CheckResult(
            name=f"gsi7_unique::{domain_name}",
            passed=passed,
            detail=f"gsi7_count={len(gsi7_items)}",
        ))
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Post-migration integrity checker for victorymail → agentcomms migration."
    )
    parser.add_argument("--source-table", default="victorymail")
    parser.add_argument("--dest-table", default="agentcomms")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--spot-check-n", type=int, default=50)
    args = parser.parse_args(argv)

    _emit("start", source_table=args.source_table, dest_table=args.dest_table)

    session = boto3.Session()
    dynamodb = session.resource("dynamodb", region_name=args.region)
    src_table = dynamodb.Table(args.source_table)
    dst_table = dynamodb.Table(args.dest_table)

    _emit("scanning", table=args.source_table)
    src_items = _full_scan(src_table)
    _emit("scanned", table=args.source_table, count=len(src_items))

    _emit("scanning", table=args.dest_table)
    dst_items = _full_scan(dst_table)
    _emit("scanned", table=args.dest_table, count=len(dst_items))

    src_buckets = _classify_src(src_items)
    dst_buckets = _classify_dst(dst_items)

    all_results: list[CheckResult] = []

    # 1. Count checks
    all_results.extend(check_counts(src_buckets, dst_buckets))

    # 2. Spot-check messages
    dst_msg_lookup = {
        item.get("message_id", ""): item
        for item in dst_buckets["message"]
        if item.get("message_id")
    }
    all_results.extend(
        check_spot_sample(src_buckets["message"], dst_msg_lookup, args.spot_check_n)
    )

    # 3. GSI3 DM count per agent
    dst_msg_by_agent: dict[str, list[dict[str, Any]]] = {}
    for m in dst_buckets["message"]:
        aid = m.get("agent_id", "")
        dst_msg_by_agent.setdefault(aid, []).append(m)

    all_results.extend(
        check_gsi3_dm_counts(dst_table, dst_buckets["agent"], dst_msg_by_agent)
    )

    # 4. GSI7 domain uniqueness
    all_results.extend(check_gsi7_domain_uniqueness(dst_table, dst_buckets["domain"]))

    # Emit summary
    failures = [r for r in all_results if not r.passed]
    _emit(
        "summary",
        total_checks=len(all_results),
        passed=len(all_results) - len(failures),
        failed=len(failures),
        failures=[{"name": r.name, "detail": r.detail} for r in failures],
    )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
