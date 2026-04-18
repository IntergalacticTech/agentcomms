#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""
Migrate S3 objects from legacy victorymail buckets to agentcomms buckets.

Two modes:
  1. Re-key mode (default): streams objects from the source bucket, looks up
     each SES message ID in the victorymail DynamoDB table, and copies to
     dest using the AgentComms canonical key layout:
         {org_id}/{agent_id}/email/{msg_id}
     Objects that cannot be mapped go to: unmapped/{original_key}

  2. Passthrough mode (--passthrough): copies each object to the dest bucket
     preserving the original key. Equivalent to `aws s3 sync`.

Usage:
    # Re-key (raw-email bucket):
    python tools/migrate_s3_rekey.py \\
        --source-bucket victorymail-raw-email \\
        --dest-bucket agentcomms-raw-inbound-prod-732770059798

    # Passthrough (bodies/attachments):
    python tools/migrate_s3_rekey.py \\
        --source-bucket victorymail-bodies \\
        --dest-bucket agentcomms-bodies-prod-732770059798 \\
        --passthrough

IMPORTANT: Do NOT run against production without --dry-run first.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("migrate_s3_rekey")

_use_json = False


def _emit(kind: str, **fields: Any) -> None:
    record = {"event": kind, **fields}
    print(json.dumps(record, default=str), flush=True)


# ---------------------------------------------------------------------------
# DynamoDB cross-reference map builder
# ---------------------------------------------------------------------------

def build_message_map(table_name: str, region: str) -> dict[str, tuple[str, str, str]]:
    """
    Scan the victorymail DynamoDB table and build a mapping:
        ses_message_id → (org_id, agent_id, msg_id)

    agent_id is derived from inbox_id: "agt_" + inbox_id[4:]
    (inbox_id starts with "inb_"; agent_id starts with "agt_")
    """
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    mapping: dict[str, tuple[str, str, str]] = {}
    scan_kwargs: dict[str, Any] = {
        "FilterExpression": Attr("entity_type").eq("Message") & Attr("ses_message_id").exists(),
        "ProjectionExpression": "org_id, inbox_id, id, ses_message_id",
    }

    scanned = 0
    _emit("build_map_start", table=table_name)

    while True:
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])
        for item in items:
            ses_id = item.get("ses_message_id", "")
            if not ses_id:
                continue
            org_id = item.get("org_id", "")
            inbox_id = item.get("inbox_id", "")
            msg_id = item.get("id", "")
            if not (org_id and inbox_id and msg_id):
                continue
            # Derive agent_id from inbox_id: "inb_XXXX" → "agt_XXXX"
            agent_id = "agt_" + inbox_id[4:] if inbox_id.startswith("inb_") else inbox_id
            mapping[ses_id] = (org_id, agent_id, msg_id)

        scanned += len(items)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    _emit("build_map_done", scanned=scanned, mapped=len(mapping))
    return mapping


# ---------------------------------------------------------------------------
# S3 copy helpers
# ---------------------------------------------------------------------------

def _dest_key_exists(s3_client: Any, dest_bucket: str, dest_key: str) -> bool:
    """Return True if the object already exists in the destination bucket."""
    try:
        s3_client.head_object(Bucket=dest_bucket, Key=dest_key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def _copy_object(
    s3_client: Any,
    source_bucket: str,
    source_key: str,
    dest_bucket: str,
    dest_key: str,
    dry_run: bool,
) -> dict[str, str]:
    """Copy a single S3 object server-side. Returns a result dict."""
    if dry_run:
        return {"source_key": source_key, "dest_key": dest_key, "status": "dry_run"}

    if _dest_key_exists(s3_client, dest_bucket, dest_key):
        return {"source_key": source_key, "dest_key": dest_key, "status": "skipped_exists"}

    copy_source = {"Bucket": source_bucket, "Key": source_key}
    s3_client.copy_object(CopySource=copy_source, Bucket=dest_bucket, Key=dest_key)
    return {"source_key": source_key, "dest_key": dest_key, "status": "copied"}


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------

def _compute_dest_key(
    source_key: str,
    passthrough: bool,
    message_map: dict[str, tuple[str, str, str]],
) -> tuple[str, str]:
    """
    Compute the destination key for a source key.

    Returns (dest_key, resolution) where resolution is one of:
        "mapped", "passthrough", "unmapped"
    """
    if passthrough:
        return source_key, "passthrough"

    # Source key format: "inbound/{ses_message_id}" (may or may not have prefix)
    ses_message_id = source_key.split("/")[-1]  # last component is the SES message ID

    if ses_message_id in message_map:
        org_id, agent_id, msg_id = message_map[ses_message_id]
        dest_key = f"{org_id}/{agent_id}/email/{msg_id}"
        return dest_key, "mapped"

    # Orphaned / unmapped
    return f"unmapped/{source_key}", "unmapped"


def migrate_bucket(
    source_bucket: str,
    dest_bucket: str,
    passthrough: bool,
    message_map: dict[str, tuple[str, str, str]],
    region: str,
    dry_run: bool,
    parallelism: int,
) -> dict[str, int]:
    """
    Paginate through all objects in source_bucket and copy to dest_bucket.
    Returns summary counts.
    """
    s3 = boto3.client("s3", region_name=region)

    counts = {"copied": 0, "skipped_exists": 0, "dry_run": 0, "unmapped": 0, "errors": 0}
    pending: list[dict[str, str]] = []
    total = 0

    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=source_bucket)

    def _flush_batch(batch: list[dict[str, str]]) -> None:
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = {
                pool.submit(
                    _copy_object,
                    s3,
                    source_bucket,
                    obj["source_key"],
                    dest_bucket,
                    obj["dest_key"],
                    dry_run,
                ): obj
                for obj in batch
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    status = result["status"]
                    counts[status] = counts.get(status, 0) + 1
                except Exception as exc:  # noqa: BLE001
                    orig = futures[future]
                    counts["errors"] += 1
                    _emit(
                        "copy_error",
                        source_key=orig["source_key"],
                        error=str(exc),
                    )

    for page in pages:
        objects = page.get("Contents", [])
        for obj in objects:
            source_key = obj["Key"]
            dest_key, resolution = _compute_dest_key(source_key, passthrough, message_map)
            if resolution == "unmapped":
                counts["unmapped"] += 1
                _emit("unmapped", source_key=source_key, dest_key=dest_key)
            pending.append({"source_key": source_key, "dest_key": dest_key})
            total += 1

            if len(pending) >= parallelism:
                _flush_batch(pending)
                pending.clear()

            if total % 100 == 0:
                _emit("progress", total=total, **counts)

    # flush remaining
    if pending:
        _flush_batch(pending)

    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate S3 objects between victorymail and agentcomms buckets."
    )
    parser.add_argument("--source-bucket", required=True)
    parser.add_argument("--dest-bucket", required=True)
    parser.add_argument(
        "--source-table",
        default="victorymail",
        help="DynamoDB table for cross-reference map (default: victorymail)",
    )
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--passthrough",
        action="store_true",
        help="Copy objects without key transformation (aws s3 sync semantics).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count what would be copied; no writes.")
    parser.add_argument("--parallelism", type=int, default=8, help="Concurrent S3 copies (default: 8).")
    parser.add_argument("--json", action="store_true", dest="use_json", help="NDJSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    global _use_json
    _use_json = args.use_json

    _emit(
        "migrate_start",
        source_bucket=args.source_bucket,
        dest_bucket=args.dest_bucket,
        passthrough=args.passthrough,
        dry_run=args.dry_run,
    )

    # Build cross-reference map (skip for passthrough — keys stay the same)
    message_map: dict[str, tuple[str, str, str]] = {}
    if not args.passthrough:
        message_map = build_message_map(args.source_table, args.region)

    counts = migrate_bucket(
        source_bucket=args.source_bucket,
        dest_bucket=args.dest_bucket,
        passthrough=args.passthrough,
        message_map=message_map,
        region=args.region,
        dry_run=args.dry_run,
        parallelism=args.parallelism,
    )

    _emit("migrate_done", **counts)

    if counts.get("errors", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
