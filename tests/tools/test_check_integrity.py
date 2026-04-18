# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""
Moto-based tests for tools/check_migration_integrity.py.
"""
from __future__ import annotations

import sys
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tools.check_migration_integrity as checker
import tools.migrate_victorymail_to_agentcomms as migrator

_TS = "2026-04-17T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Shared seed helpers (duplicated here to keep tests self-contained)
# ---------------------------------------------------------------------------

def _seed_src(vm):
    """Seed a small but representative victorymail dataset."""
    # Org
    vm.put_item(Item={
        "PK": "ORG#org_01", "SK": "ORG#org_01",
        "entity": "organization", "org_id": "org_01",
        "name": "Acme", "plan": "free",
        "quotas": {}, "settings": {},
        "created_at": _TS, "updated_at": _TS,
    })
    # Inbox
    vm.put_item(Item={
        "PK": "ORG#org_01", "SK": "INBOX#inb_abc",
        "entity": "inbox", "inbox_id": "inb_abc",
        "org_id": "org_01", "address": "bot@example.com",
        "domain_id": "dom_01",
        "created_at": _TS, "updated_at": _TS,
    })
    # Message
    vm.put_item(Item={
        "PK": "INBOX#inb_abc", "SK": "MSG#msg_01",
        "entity": "message", "message_id": "msg_01",
        "org_id": "org_01", "inbox_id": "inb_abc",
        "from_address": "alice@example.com",
        "to_addresses": ["bot@example.com"],
        "subject": "Hello", "body_text": "Hi",
        "direction": "inbound", "status": "received",
        "thread_id": "thr_xyz",
        "message_id_header": "<msg1@example.com>",
        "created_at": _TS,
    })
    # Thread
    vm.put_item(Item={
        "PK": "INBOX#inb_abc", "SK": "THREAD#thr_xyz",
        "entity": "thread", "thread_id": "thr_xyz",
        "inbox_id": "inb_abc", "org_id": "org_01",
        "subject": "Hello", "message_count": 1,
        "participants": ["alice@example.com"],
        "created_at": _TS,
    })
    # Domain
    vm.put_item(Item={
        "PK": "ORG#org_01", "SK": "DOMAIN#dom_01",
        "entity": "domain", "domain_id": "dom_01",
        "org_id": "org_01", "domain_name": "example.com",
        "status": "verified",
        "created_at": _TS, "updated_at": _TS,
    })


def _run_migration(vm, ac):
    """Run the full migration from src to dst."""
    kw = dict(dry_run=False, limit=None)
    migrator.migrate_orgs(vm, ac, **kw)
    migrator.migrate_inboxes_to_agents_and_channels(vm, ac, **kw)
    migrator.migrate_messages(vm, ac, **kw)
    migrator.migrate_threads(vm, ac, **kw)
    migrator.migrate_domains(vm, ac, **kw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_matched_counts_pass(both_tables):
    """After a complete migration, all count checks pass."""
    vm, ac = both_tables
    _seed_src(vm)
    _run_migration(vm, ac)

    src_items = checker._full_scan(vm)
    dst_items = checker._full_scan(ac)
    src_buckets = checker._classify_src(src_items)
    dst_buckets = checker._classify_dst(dst_items)

    results = checker.check_counts(src_buckets, dst_buckets)
    failures = [r for r in results if not r.passed]
    assert failures == [], f"Count check failures: {[r.name + ': ' + r.detail for r in failures]}"


def test_mismatched_counts_fail(both_tables):
    """If messages are not migrated, the count check should fail."""
    vm, ac = both_tables
    _seed_src(vm)
    # Migrate everything EXCEPT messages
    kw = dict(dry_run=False, limit=None)
    migrator.migrate_orgs(vm, ac, **kw)
    migrator.migrate_inboxes_to_agents_and_channels(vm, ac, **kw)
    # Intentionally skip migrate_messages

    src_items = checker._full_scan(vm)
    dst_items = checker._full_scan(ac)
    src_buckets = checker._classify_src(src_items)
    dst_buckets = checker._classify_dst(dst_items)

    results = checker.check_counts(src_buckets, dst_buckets)
    # message 1:1 check should fail
    msg_check = next((r for r in results if "message 1:1" in r.name), None)
    assert msg_check is not None, "Expected a message count check"
    assert not msg_check.passed, "Expected message count check to FAIL when messages not migrated"


def test_spot_check_passes_after_full_migration(both_tables):
    """Spot-check returns no mismatches after a full migration."""
    vm, ac = both_tables
    _seed_src(vm)
    _run_migration(vm, ac)

    src_items = checker._full_scan(vm)
    dst_items = checker._full_scan(ac)
    src_buckets = checker._classify_src(src_items)
    dst_buckets = checker._classify_dst(dst_items)

    dst_msg_lookup = {
        item.get("message_id", ""): item
        for item in dst_buckets["message"]
        if item.get("message_id")
    }
    results = checker.check_spot_sample(src_buckets["message"], dst_msg_lookup, n=50)
    assert all(r.passed for r in results), (
        f"Spot-check failures: {[r.detail for r in results if not r.passed]}"
    )


def test_spot_check_detects_missing_message(both_tables):
    """Spot-check fails if a sampled message is absent from destination."""
    vm, ac = both_tables
    _seed_src(vm)
    # Do NOT migrate messages — they will be missing in dst
    migrator.migrate_orgs(vm, ac, dry_run=False, limit=None)

    src_items = checker._full_scan(vm)
    src_buckets = checker._classify_src(src_items)
    # Empty dst_msg_lookup simulates no messages migrated
    results = checker.check_spot_sample(src_buckets["message"], dst_msg_lookup={}, n=50)
    assert not all(r.passed for r in results), "Expected spot-check to FAIL for missing messages"


def test_gsi3_dm_count_matches(both_tables):
    """GSI3 returns the same count of DM messages as manually counted."""
    vm, ac = both_tables
    _seed_src(vm)
    _run_migration(vm, ac)

    dst_items = checker._full_scan(ac)
    dst_buckets = checker._classify_dst(dst_items)

    dst_msg_by_agent: dict = {}
    for m in dst_buckets["message"]:
        aid = m.get("agent_id", "")
        dst_msg_by_agent.setdefault(aid, []).append(m)

    results = checker.check_gsi3_dm_counts(ac, dst_buckets["agent"], dst_msg_by_agent)
    failures = [r for r in results if not r.passed]
    assert failures == [], f"GSI3 count mismatches: {failures}"
