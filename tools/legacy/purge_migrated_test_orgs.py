#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Purge the 58 migrated test orgs from the agentcomms table.

KEEPS:
  - org_01KPH36QSYPCPJAEY4GRN5EJ1G (JWC Personal)
  - org_01KPF3CA06MJ3D5Z3PERTZQHM3 (Victory Phase 1 Test)

DELETES everything else that was migrated from victorymail: org, api_key,
agent, channel, message, thread, draft items scoped to those orgs plus the
corresponding GSI entries.

Usage:
  python tools/purge_migrated_test_orgs.py --dry-run    # count only
  python tools/purge_migrated_test_orgs.py              # real purge
"""
from __future__ import annotations

import argparse
import json
import sys
import boto3
from boto3.dynamodb.conditions import Key

KEEP_ORG_IDS = {
    "org_01KPH36QSYPCPJAEY4GRN5EJ1G",  # JWC Personal
    "org_01KPF3CA06MJ3D5Z3PERTZQHM3",  # Victory Phase 1 Test
}


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="agentcomms")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ddb = boto3.resource("dynamodb", region_name=args.region)
    table = ddb.Table(args.table)

    # Phase 1: find all org IDs to delete.
    # Migrated orgs from victorymail kept legacy shape (no `org_id` top-level);
    # the org_id is embedded in the PK (format `ORG#<uuid>`). Native agentcomms
    # orgs have `org_id` top-level. Handle both.
    to_delete_orgs: set[str] = set()
    scan_kwargs = {
        "FilterExpression": "SK = :meta",
        "ExpressionAttributeValues": {":meta": "META"},
    }

    def _process(resp_items):
        for item in resp_items:
            oid = item.get("org_id")
            if not oid:
                pk = item.get("PK", "")
                if pk.startswith("ORG#"):
                    oid = pk[4:]  # strip ORG# prefix
            if oid and oid not in KEEP_ORG_IDS:
                to_delete_orgs.add(oid)

    resp = table.scan(**scan_kwargs)
    _process(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(**scan_kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        _process(resp.get("Items", []))

    emit("plan", keep=sorted(KEEP_ORG_IDS), delete_org_count=len(to_delete_orgs))

    # Phase 2: for each org, scan all items under PK=ORG#... and PK=AGT#<agents-of-this-org>
    items_to_delete: list[tuple[str, str]] = []
    agent_ids_for_orgs: dict[str, list[str]] = {}

    for oid in to_delete_orgs:
        # ORG-scoped items (META, APIKEY, AGT, DOM, POD, VLT, PER, INB/MSG/THR for legacy shape)
        org_items = table.query(
            KeyConditionExpression=Key("PK").eq(f"ORG#{oid}"),
        ).get("Items", [])
        for item in org_items:
            items_to_delete.append((item["PK"], item["SK"]))
            # Track agent IDs (native shape uses AGT#, legacy victorymail uses INB#)
            if item["SK"].startswith("AGT#") and "agent_id" in item:
                agent_ids_for_orgs.setdefault(oid, []).append(item["agent_id"])
            elif item["SK"].startswith("INB#") and "inbox_id" in item:
                # Legacy inbox items have PK=ORG#<orgid> SK=INB#<inbox_id>
                # Their associated messages/threads live under PK=INBOX#<inbox_id>
                agent_ids_for_orgs.setdefault(oid, []).append(f"INBOX#{item['inbox_id']}")

    # Phase 3: scan AGT# items for each agent (messages, channels, threads, drafts, webhooks)
    total_agent_children = 0
    for oid, agent_ids in agent_ids_for_orgs.items():
        for aid in agent_ids:
            # Determine PK format: legacy inboxes use INBOX#<id>, native agents use AGT#<id>
            pk = aid if aid.startswith("INBOX#") else f"AGT#{aid}"
            child_items = table.query(
                KeyConditionExpression=Key("PK").eq(pk),
            ).get("Items", [])
            for item in child_items:
                items_to_delete.append((item["PK"], item["SK"]))
                total_agent_children += 1

    emit("plan", total_items=len(items_to_delete), agent_children=total_agent_children)

    if args.dry_run:
        emit("dry_run", status="skipping writes")
        return 0

    # Phase 4: batch delete (DynamoDB max 25 per batch)
    deleted = 0
    failed = 0
    for i in range(0, len(items_to_delete), 25):
        batch = items_to_delete[i:i + 25]
        request_items = {
            args.table: [{"DeleteRequest": {"Key": {"PK": pk, "SK": sk}}} for pk, sk in batch]
        }
        try:
            resp = ddb.batch_write_item(RequestItems=request_items)
            unprocessed = resp.get("UnprocessedItems", {}).get(args.table, [])
            # Retry unprocessed
            retries = 0
            while unprocessed and retries < 3:
                resp = ddb.batch_write_item(RequestItems={args.table: unprocessed})
                unprocessed = resp.get("UnprocessedItems", {}).get(args.table, [])
                retries += 1
            deleted += len(batch) - len(unprocessed)
            failed += len(unprocessed)
        except Exception as e:
            emit("batch_error", error=str(e), batch_size=len(batch))
            failed += len(batch)

        if (i // 25) % 10 == 0:
            emit("progress", processed=i + len(batch), total=len(items_to_delete))

    emit("done", deleted=deleted, failed=failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
