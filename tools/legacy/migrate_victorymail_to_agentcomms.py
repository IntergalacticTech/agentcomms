#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""
Migrate data from the legacy `victorymail` DynamoDB table into the new
`agentcomms` table per spec §6.3. Idempotent, re-runnable, supports --dry-run.

Usage:
    python tools/migrate_victorymail_to_agentcomms.py [--dry-run] [--limit N]
    python tools/migrate_victorymail_to_agentcomms.py --source-table victorymail \\
        --dest-table agentcomms --region us-east-1

IMPORTANT: Do NOT run this script against production without a dry-run pass first.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Generator, Iterable

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

# Ensure the repo root is on sys.path so core.data.models is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.models import (
    Agent,
    ApiKey,
    ApiKeyScope,
    Channel,
    ChannelMode,
    ChannelStatus,
    ChannelType,
    Domain,
    Draft,
    MessageDirection,
    MessageStatus,
    Organization,
    OrgPlan,
    Party,
    Thread,
    UnifiedMessage,
    Webhook,
)

# ---------------------------------------------------------------------------
# Logging / NDJSON output
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("migrate")

_use_json = False  # set by --json flag


def _emit(kind: str, **fields: Any) -> None:
    """Write a single NDJSON line to stdout."""
    record = {"event": kind, **fields}
    print(json.dumps(record, default=str), flush=True)


# ---------------------------------------------------------------------------
# Retry / backoff helper
# ---------------------------------------------------------------------------

_MAX_RETRIES = 5
_BACKOFF_BASE = 0.1


def _with_retry(fn: Callable[[], Any]) -> Any:
    """Call fn; on ProvisionedThroughputExceededException, retry with jitter."""
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ProvisionedThroughputExceededException" and attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.1)
                time.sleep(wait)
                continue
            raise
    return None  # unreachable


# ---------------------------------------------------------------------------
# Idempotent write
# ---------------------------------------------------------------------------

def _put_if_not_exists(dest_table: Any, item: dict[str, Any], dry_run: bool) -> str:
    """Write item only if PK+SK pair does not already exist.

    Returns 'written', 'skipped', or 'error'.
    """
    if dry_run:
        return "dry"

    def _do_put() -> str:
        try:
            dest_table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            return "written"
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                return "skipped"
            raise

    try:
        return _with_retry(_do_put)
    except ClientError as exc:
        logger.error("put_item failed for PK=%s SK=%s: %s", item.get("PK"), item.get("SK"), exc)
        return "error"


# ---------------------------------------------------------------------------
# Table scanner
# ---------------------------------------------------------------------------

def _scan_entity(
    source_table: Any,
    filter_fn: Callable[[dict[str, Any]], bool],
    limit: int | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Full-table scan yielding items that pass filter_fn.

    Handles DynamoDB pagination automatically.
    If limit is set, stops after yielding that many items.
    """
    yielded = 0
    kwargs: dict[str, Any] = {}

    while True:
        response = _with_retry(lambda kw=kwargs: source_table.scan(**kw))
        for item in response.get("Items", []):
            if filter_fn(item):
                yield item
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
        last = response.get("LastEvaluatedKey")
        if not last:
            break
        kwargs = {"ExclusiveStartKey": last}


# ---------------------------------------------------------------------------
# Counter dataclass
# ---------------------------------------------------------------------------

@dataclass
class Counts:
    processed: int = 0
    written: int = 0
    skipped: int = 0
    errors: int = 0

    def record(self, result: str) -> None:
        self.processed += 1
        if result == "written":
            self.written += 1
        elif result == "skipped":
            self.skipped += 1
        elif result == "dry":
            self.written += 1  # dry-run: count as "would write"
        else:
            self.errors += 1

    def to_dict(self) -> dict[str, int]:
        return {
            "processed": self.processed,
            "written": self.written,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def _progress(entity: str, counts: Counts) -> None:
    _emit("progress", entity=entity, **counts.to_dict())


# ---------------------------------------------------------------------------
# Agent ID / Channel ID derivation
# ---------------------------------------------------------------------------

def _agent_id_from_inbox(inbox_id: str) -> str:
    """'inb_abc' → 'agt_abc'"""
    if inbox_id.startswith("inb_"):
        return "agt_" + inbox_id[4:]
    # Fallback for non-standard prefixes (log but don't crash)
    logger.warning("Unexpected inbox_id prefix: %s — using as-is for agent suffix", inbox_id)
    return "agt_" + inbox_id


def _channel_id_from_inbox(inbox_id: str) -> str:
    """'inb_abc' → 'chan_em_abc'"""
    if inbox_id.startswith("inb_"):
        return "chan_em_" + inbox_id[4:]
    return "chan_em_" + inbox_id


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------

def migrate_orgs(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> Counts:
    """Copy Organization items (PK=ORG#*, SK=META or SK=ORG#*) as-is."""
    counts = Counts()

    def _is_org(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        # Legacy victorymail stores org meta at PK=ORG#{id} SK=ORG#{id}
        return pk.startswith("ORG#") and (sk == "META" or sk == pk)

    for item in _scan_entity(src, _is_org, limit):
        # Normalize SK to "META" (agentcomms schema)
        normalised = dict(item)
        normalised["SK"] = "META"
        normalised.setdefault("entity", "organization")
        result = _put_if_not_exists(dst, normalised, dry_run)
        counts.record(result)
        if counts.processed % 100 == 0:
            _progress("org", counts)

    _emit("entity_done", entity="org", **counts.to_dict())
    return counts


def migrate_api_keys(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> Counts:
    """Copy ApiKey items; ensure gsi1_pk / gsi1_sk are present."""
    counts = Counts()

    def _is_apikey(item: dict[str, Any]) -> bool:
        return item.get("PK", "").startswith("ORG#") and item.get("SK", "").startswith("APIKEY#")

    for item in _scan_entity(src, _is_apikey, limit):
        normalised = dict(item)
        # Migrate legacy uppercase GSI1PK/GSI1SK to lowercase keys (always remove uppercase)
        for old, new in [("GSI1PK", "gsi1_pk"), ("GSI1SK", "gsi1_sk")]:
            if old in normalised:
                normalised.setdefault(new, normalised[old])
                del normalised[old]
        # Ensure GSI1 fields exist (agentcomms uses lowercase gsi1_pk/gsi1_sk)
        if "gsi1_pk" not in normalised:
            key_hash = normalised.get("key_hash") or normalised["SK"].removeprefix("APIKEY#")
            org_id = normalised.get("org_id") or normalised["PK"].removeprefix("ORG#")
            normalised["gsi1_pk"] = f"APIKEY#{key_hash}"
            normalised["gsi1_sk"] = f"ORG#{org_id}"
        normalised.setdefault("entity", "api_key")
        result = _put_if_not_exists(dst, normalised, dry_run)
        counts.record(result)
        if counts.processed % 100 == 0:
            _progress("api_key", counts)

    _emit("entity_done", entity="api_key", **counts.to_dict())
    return counts


def migrate_inboxes_to_agents_and_channels(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> tuple[Counts, Counts]:
    """For each Inbox, create one Agent + one email Channel in agentcomms."""
    agent_counts = Counts()
    channel_counts = Counts()

    def _is_inbox(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        return pk.startswith("ORG#") and (
            sk.startswith("INBOX#") or sk.startswith("INB#")
        )

    for inbox in _scan_entity(src, _is_inbox, limit):
        inbox_id = inbox.get("inbox_id") or _extract_id(inbox["SK"], ("INBOX#", "INB#"))
        org_id = inbox.get("org_id") or inbox["PK"].removeprefix("ORG#")
        agent_id = _agent_id_from_inbox(inbox_id)
        channel_id = _channel_id_from_inbox(inbox_id)
        pod_id = inbox.get("pod_id")

        # --- Agent ---
        metadata: dict[str, Any] = {"migrated_from_inbox": inbox_id}
        if pod_id:
            metadata["pod"] = pod_id
        name = inbox.get("display_name") or inbox.get("address") or inbox_id
        created_at_raw = inbox.get("created_at") or datetime.now(timezone.utc).isoformat()
        agent_item = {
            "PK": f"ORG#{org_id}",
            "SK": f"AGT#{agent_id}",
            "entity": "agent",
            "agent_id": agent_id,
            "org_id": org_id,
            "name": name,
            "metadata": metadata,
            "status": "active",
            "created_at": created_at_raw,
            "updated_at": created_at_raw,
        }
        result = _put_if_not_exists(dst, agent_item, dry_run)
        agent_counts.record(result)
        if agent_counts.processed % 100 == 0:
            _progress("agent", agent_counts)

        # --- Channel ---
        address = inbox.get("address") or ""
        domain_id = inbox.get("domain_id")
        channel_item = {
            "PK": f"AGT#{agent_id}",
            "SK": f"CHAN#email#{channel_id}",
            "entity": "channel",
            "channel_id": channel_id,
            "agent_id": agent_id,
            "org_id": org_id,
            "channel": "email",
            "mode": "provision",
            "config": {"address": address, "domain_id": domain_id},
            "status": "active",
            "address_index_value": address,
            "created_at": created_at_raw,
            "updated_at": created_at_raw,
        }
        if address:
            channel_item["gsi2_pk"] = f"ADDR#email#{address}"
            channel_item["gsi2_sk"] = f"CHAN#{channel_id}"
        result = _put_if_not_exists(dst, channel_item, dry_run)
        channel_counts.record(result)
        if channel_counts.processed % 100 == 0:
            _progress("channel", channel_counts)

    _emit("entity_done", entity="agent", **agent_counts.to_dict())
    _emit("entity_done", entity="channel", **channel_counts.to_dict())
    return agent_counts, channel_counts


def migrate_messages(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> Counts:
    """Transform Message items from inbox-scoped to agent-scoped UnifiedMessage items."""
    counts = Counts()

    def _is_message(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        return pk.startswith("INBOX#") and sk.startswith("MSG#")

    for msg in _scan_entity(src, _is_message, limit):
        inbox_id = msg["PK"].removeprefix("INBOX#")
        agent_id = _agent_id_from_inbox(inbox_id)
        channel_id = _channel_id_from_inbox(inbox_id)
        org_id = msg.get("org_id", "")

        msg_id = msg.get("message_id") or msg.get("msg_id") or _extract_id(msg["SK"], ("MSG#",))
        thread_id = msg.get("thread_id")
        thread_key = ("thr_" + thread_id[4:]) if thread_id and thread_id.startswith("thr_") else thread_id

        received_at_raw = msg.get("created_at") or datetime.now(timezone.utc).isoformat()
        received_at = _parse_dt(received_at_raw)
        ts_ms = int(received_at.timestamp() * 1000)
        sk = f"MSG#{ts_ms}#{msg_id}"

        direction = msg.get("direction", "inbound")
        status = msg.get("status", "received")

        from_raw = msg.get("from_address") or msg.get("from") or {}
        if isinstance(from_raw, str):
            from_party = {"address": from_raw, "display_name": msg.get("from_display_name")}
        elif isinstance(from_raw, dict):
            from_party = from_raw
        else:
            from_party = {"address": "unknown@unknown"}

        to_raw = msg.get("to_addresses") or msg.get("to") or []
        if isinstance(to_raw, list) and to_raw and isinstance(to_raw[0], str):
            to_list = [{"address": a} for a in to_raw]
        elif isinstance(to_raw, list):
            to_list = to_raw
        else:
            to_list = []

        channel_native = {
            "message_id_header": msg.get("message_id_header"),
            "in_reply_to": msg.get("in_reply_to"),
            "references": msg.get("references") or [],
            "spf_pass": msg.get("spf_pass"),
            "dkim_pass": msg.get("dkim_pass"),
            "dmarc_pass": msg.get("dmarc_pass"),
        }
        # Remove None values to keep the blob clean
        channel_native = {k: v for k, v in channel_native.items() if v is not None}

        new_item: dict[str, Any] = {
            "PK": f"AGT#{agent_id}",
            "SK": sk,
            "entity": "message",
            "message_id": msg_id,
            "agent_id": agent_id,
            "org_id": org_id,
            "channel_id": channel_id,
            "channel": "email",
            "direction": direction,
            "status": status,
            "from": from_party,
            "to": to_list,
            "subject": msg.get("subject"),
            "body_text": msg.get("body_text") or "",
            "body_html": msg.get("body_html"),
            "body_s3_key": msg.get("body_s3_key"),
            "attachments": msg.get("attachments") or [],
            "thread_key": thread_key,
            "is_dm": True,
            "received_at": received_at_raw,
            "channel_native": channel_native,
            "external_id": msg.get("message_id_header"),
            "created_at": received_at_raw,
            "updated_at": received_at_raw,
            # GSI3: unified inbox (is_dm=True)
            "gsi3_pk": f"AGT_DM#{agent_id}",
            "gsi3_sk": sk,
            # GSI4: channel-native listing
            "gsi4_pk": f"CHAN#{channel_id}",
            "gsi4_sk": sk,
        }
        if thread_key:
            new_item["gsi5_pk"] = f"THR#{thread_key}"
            new_item["gsi5_sk"] = sk
        external_id = msg.get("message_id_header")
        if external_id:
            new_item["gsi6_pk"] = f"EXTID#email#{external_id}"
            new_item["gsi6_sk"] = f"MSG#{msg_id}"

        result = _put_if_not_exists(dst, new_item, dry_run)
        counts.record(result)
        if counts.processed % 100 == 0:
            _progress("message", counts)

    _emit("entity_done", entity="message", **counts.to_dict())
    return counts


def migrate_threads(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> Counts:
    """Transform Thread items from inbox-scoped to agent-scoped."""
    counts = Counts()

    def _is_thread(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        return pk.startswith("INBOX#") and sk.startswith("THREAD#")

    for thr in _scan_entity(src, _is_thread, limit):
        inbox_id = thr["PK"].removeprefix("INBOX#")
        agent_id = _agent_id_from_inbox(inbox_id)
        org_id = thr.get("org_id", "")
        thread_id = thr.get("thread_id") or _extract_id(thr["SK"], ("THREAD#",))
        # thread_key: strip "thr_" prefix and re-add (or map thread_id → thr_...)
        if thread_id.startswith("thr_"):
            thread_key = "thr_" + thread_id[4:]
        else:
            thread_key = thread_id

        last_msg_at_raw = thr.get("last_message_at")
        last_msg_at = _parse_dt(last_msg_at_raw) if last_msg_at_raw else None
        created_at_raw = thr.get("created_at") or datetime.now(timezone.utc).isoformat()

        new_item: dict[str, Any] = {
            "PK": f"AGT#{agent_id}",
            "SK": f"THR#email#{thread_id}",
            "entity": "thread",
            "thread_key": thread_key,
            "agent_id": agent_id,
            "org_id": org_id,
            "channel": "email",
            "native_thread_id": thread_id,
            "subject": thr.get("subject"),
            "last_message_at": last_msg_at.isoformat() if last_msg_at else None,
            "message_count": int(thr.get("message_count") or 0),
            "participants": thr.get("participants") or [],
            "created_at": created_at_raw,
        }
        result = _put_if_not_exists(dst, new_item, dry_run)
        counts.record(result)
        if counts.processed % 100 == 0:
            _progress("thread", counts)

    _emit("entity_done", entity="thread", **counts.to_dict())
    return counts


def migrate_domains(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> Counts:
    """Copy Domain items; add GSI7 projection if missing."""
    counts = Counts()

    def _is_domain(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        return pk.startswith("ORG#") and (
            sk.startswith("DOM#") or sk.startswith("DOMAIN#")
        )

    for dom in _scan_entity(src, _is_domain, limit):
        normalised = dict(dom)
        # Normalize SK to DOM# prefix
        if dom["SK"].startswith("DOMAIN#"):
            domain_id = dom["SK"].removeprefix("DOMAIN#")
            normalised["SK"] = f"DOM#{domain_id}"
        else:
            domain_id = dom["SK"].removeprefix("DOM#")

        org_id = dom.get("org_id") or dom["PK"].removeprefix("ORG#")
        domain_name = dom.get("domain_name") or dom.get("name") or ""
        normalised.setdefault("entity", "domain")
        normalised.setdefault("domain_id", domain_id)
        normalised.setdefault("org_id", org_id)

        # Add GSI7 if missing
        if "gsi7_pk" not in normalised and domain_name:
            normalised["gsi7_pk"] = f"DOMAIN#{domain_name}"
            normalised["gsi7_sk"] = f"ORG#{org_id}"
        # Migrate legacy uppercase GSI1 domain uniqueness keys
        for old in ("GSI1PK", "GSI1SK"):
            normalised.pop(old, None)

        result = _put_if_not_exists(dst, normalised, dry_run)
        counts.record(result)
        if counts.processed % 100 == 0:
            _progress("domain", counts)

    _emit("entity_done", entity="domain", **counts.to_dict())
    return counts


def migrate_webhooks(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> Counts:
    """Migrate Webhook items from org-scoped to agent-scoped via inbox mapping."""
    counts = Counts()

    # We need inbox→agent mapping; build a lookup from org webhooks
    def _is_webhook(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        return (pk.startswith("INBOX#") or pk.startswith("ORG#")) and sk.startswith("WEBHOOK#")

    for whk in _scan_entity(src, _is_webhook, limit):
        pk = whk["PK"]
        webhook_id = whk.get("webhook_id") or _extract_id(whk["SK"], ("WEBHOOK#", "WHK#"))
        org_id = whk.get("org_id", "")

        # Determine agent_id from inbox or org
        if pk.startswith("INBOX#"):
            inbox_id = pk.removeprefix("INBOX#")
            agent_id = _agent_id_from_inbox(inbox_id)
        else:
            # Org-level webhook: use a sentinel agent_id, or skip
            inbox_id = whk.get("inbox_id", "")
            if inbox_id:
                agent_id = _agent_id_from_inbox(inbox_id)
            else:
                # Org-level webhooks without an inbox mapping: use org_id as suffix
                agent_id = "agt_org_" + (org_id or "unknown")
                logger.warning("Org-level webhook %s has no inbox_id; routing to %s", webhook_id, agent_id)

        created_at_raw = whk.get("created_at") or datetime.now(timezone.utc).isoformat()
        new_item: dict[str, Any] = {
            "PK": f"AGT#{agent_id}",
            "SK": f"WHK#{webhook_id}",
            "entity": "webhook",
            "webhook_id": webhook_id,
            "agent_id": agent_id,
            "org_id": org_id,
            "url": whk.get("url", ""),
            "events": whk.get("events") or [],
            "channels": whk.get("channels") or ["*"],
            "secret": whk.get("secret", ""),
            "status": whk.get("status", "active"),
            "created_at": created_at_raw,
        }
        result = _put_if_not_exists(dst, new_item, dry_run)
        counts.record(result)
        if counts.processed % 100 == 0:
            _progress("webhook", counts)

    _emit("entity_done", entity="webhook", **counts.to_dict())
    return counts


def migrate_drafts(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> Counts:
    """Migrate Draft items from inbox-scoped to agent-scoped."""
    counts = Counts()

    def _is_draft(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        return pk.startswith("INBOX#") and (sk.startswith("DRAFT#") or sk.startswith("DRF#"))

    for draft in _scan_entity(src, _is_draft, limit):
        inbox_id = draft["PK"].removeprefix("INBOX#")
        agent_id = _agent_id_from_inbox(inbox_id)
        org_id = draft.get("org_id", "")
        draft_id = draft.get("draft_id") or _extract_id(draft["SK"], ("DRAFT#", "DRF#"))
        created_at_raw = draft.get("created_at") or datetime.now(timezone.utc).isoformat()

        to_raw = draft.get("to") or []
        if isinstance(to_raw, list) and to_raw and isinstance(to_raw[0], str):
            to_list = [{"address": a} for a in to_raw]
        else:
            to_list = to_raw

        new_item: dict[str, Any] = {
            "PK": f"AGT#{agent_id}",
            "SK": f"DRF#email#{draft_id}",
            "entity": "draft",
            "draft_id": draft_id,
            "agent_id": agent_id,
            "org_id": org_id,
            "channel": "email",
            "to": to_list,
            "subject": draft.get("subject"),
            "body_text": draft.get("body_text") or "",
            "body_html": draft.get("body_html"),
            "attachments": draft.get("attachments") or [],
            "created_at": created_at_raw,
            "updated_at": draft.get("updated_at") or created_at_raw,
        }
        result = _put_if_not_exists(dst, new_item, dry_run)
        counts.record(result)
        if counts.processed % 100 == 0:
            _progress("draft", counts)

    _emit("entity_done", entity="draft", **counts.to_dict())
    return counts


def migrate_attachments(
    src: Any,
    dst: Any,
    dry_run: bool,
    limit: int | None,
) -> Counts:
    """Copy Attachment items as-is (already message-scoped)."""
    counts = Counts()

    def _is_attachment(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        return pk.startswith("MSG#") and (sk.startswith("ATTACH#") or sk.startswith("ATT#"))

    for att in _scan_entity(src, _is_attachment, limit):
        normalised = dict(att)
        normalised.setdefault("entity", "attachment")
        result = _put_if_not_exists(dst, normalised, dry_run)
        counts.record(result)
        if counts.processed % 100 == 0:
            _progress("attachment", counts)

    _emit("entity_done", entity="attachment", **counts.to_dict())
    return counts


def migrate_pods_warn(src: Any, limit: int | None) -> None:
    """Pods are dropped from the agentcomms model. Emit a warning for each one found."""

    def _is_pod(item: dict[str, Any]) -> bool:
        return item.get("PK", "").startswith("ORG#") and item.get("SK", "").startswith("POD#")

    count = 0
    for pod in _scan_entity(src, _is_pod, limit):
        count += 1
        pod_id = pod.get("pod_id") or pod["SK"].removeprefix("POD#")
        logger.warning(
            "Pod %s (org %s) is not in the agentcomms model; "
            "its pod_id will be preserved in Agent.metadata.pod for inboxes that referenced it.",
            pod_id,
            pod.get("org_id", "?"),
        )
    if count:
        _emit("warning", message=f"Dropped {count} Pod items (not in agentcomms model)")


def migrate_lists_warn(src: Any, limit: int | None) -> None:
    """List entries (allow/block) are dropped. Emit a warning for each one found."""

    def _is_list(item: dict[str, Any]) -> bool:
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        return (pk.startswith("LIST#") or sk.startswith("MEMBER#")
                or (pk.startswith("ORG#") and sk.startswith("LIST#")))

    count = 0
    for _ in _scan_entity(src, _is_list, limit):
        count += 1
    if count:
        _emit("warning", message=f"Dropped {count} List/member items (not in agentcomms model)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_id(sk: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if sk.startswith(prefix):
            return sk[len(prefix):]
    return sk


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_table(session: boto3.Session, table_name: str, region: str) -> Any:
    dynamodb = session.resource("dynamodb", region_name=region)
    return dynamodb.Table(table_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate data from victorymail DynamoDB table to agentcomms."
    )
    parser.add_argument("--source-table", default="victorymail")
    parser.add_argument("--dest-table", default="agentcomms")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--dry-run", action="store_true", help="Count writes without executing them")
    parser.add_argument("--limit", type=int, default=None, help="Max items per entity type (for testing)")
    parser.add_argument("--parallelism", type=int, default=4, help="Thread count for parallel entity scans")
    parser.add_argument("--json", action="store_true", dest="json_output", help="NDJSON progress output")
    args = parser.parse_args(argv)

    global _use_json
    _use_json = args.json_output

    _emit(
        "start",
        source_table=args.source_table,
        dest_table=args.dest_table,
        region=args.region,
        dry_run=args.dry_run,
        limit=args.limit,
    )

    session = boto3.Session()
    src = _build_table(session, args.source_table, args.region)
    dst = _build_table(session, args.dest_table, args.region)

    kwargs = dict(dry_run=args.dry_run, limit=args.limit)

    # Warn about dropped entities (no writes)
    migrate_pods_warn(src, args.limit)
    migrate_lists_warn(src, args.limit)

    # Migrate in dependency order
    org_counts = migrate_orgs(src, dst, **kwargs)
    key_counts = migrate_api_keys(src, dst, **kwargs)
    agent_counts, channel_counts = migrate_inboxes_to_agents_and_channels(src, dst, **kwargs)
    msg_counts = migrate_messages(src, dst, **kwargs)
    thr_counts = migrate_threads(src, dst, **kwargs)
    dom_counts = migrate_domains(src, dst, **kwargs)
    whk_counts = migrate_webhooks(src, dst, **kwargs)
    drf_counts = migrate_drafts(src, dst, **kwargs)
    att_counts = migrate_attachments(src, dst, **kwargs)

    total_errors = sum(
        c.errors for c in [
            org_counts, key_counts, agent_counts, channel_counts,
            msg_counts, thr_counts, dom_counts, whk_counts, drf_counts, att_counts,
        ]
    )

    _emit(
        "done",
        status="done",
        dry_run=args.dry_run,
        counts={
            "org": org_counts.to_dict(),
            "api_key": key_counts.to_dict(),
            "agent": agent_counts.to_dict(),
            "channel": channel_counts.to_dict(),
            "message": msg_counts.to_dict(),
            "thread": thr_counts.to_dict(),
            "domain": dom_counts.to_dict(),
            "webhook": whk_counts.to_dict(),
            "draft": drf_counts.to_dict(),
            "attachment": att_counts.to_dict(),
        },
    )

    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
