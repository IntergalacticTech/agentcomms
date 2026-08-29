# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""
Moto-based unit tests for tools/migrate_victorymail_to_agentcomms.py.

Each test seeds a small victorymail-shape table, runs the migrator against it,
then asserts the agentcomms-shape table has the expected items.
"""
from __future__ import annotations

import sys
import os
from datetime import datetime, timezone

import pytest

# Ensure the repo root is on sys.path so the tools/ module is importable.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tools.legacy.migrate_victorymail_to_agentcomms as migrator

# ---------------------------------------------------------------------------
# Shared seed helpers
# ---------------------------------------------------------------------------

_TS = "2026-04-17T10:00:00+00:00"


def _seed_org(table, org_id="org_01", name="Acme"):
    table.put_item(Item={
        "PK": f"ORG#{org_id}",
        "SK": f"ORG#{org_id}",
        "entity": "organization",
        "org_id": org_id,
        "name": name,
        "plan": "free",
        "quotas": {},
        "settings": {},
        "created_at": _TS,
        "updated_at": _TS,
    })


def _seed_api_key(table, org_id="org_01", key_hash="abc123", key_id="key_01"):
    table.put_item(Item={
        "PK": f"ORG#{org_id}",
        "SK": f"APIKEY#{key_hash}",
        "entity": "api_key",
        "key_id": key_id,
        "key_hash": key_hash,
        "org_id": org_id,
        "scope": "org",
        "name": "default",
        "GSI1PK": f"APIKEY#{key_hash}",
        "GSI1SK": f"APIKEY#{key_id}",
        "created_at": _TS,
        "last_used_at": None,
    })


def _seed_inbox(table, org_id="org_01", inbox_id="inb_abc", address="bot@example.com",
                pod_id=None, domain_id="dom_01"):
    item = {
        "PK": f"ORG#{org_id}",
        "SK": f"INBOX#{inbox_id}",
        "entity": "inbox",
        "inbox_id": inbox_id,
        "org_id": org_id,
        "address": address,
        "display_name": "My Bot",
        "domain_id": domain_id,
        "created_at": _TS,
        "updated_at": _TS,
    }
    if pod_id:
        item["pod_id"] = pod_id
    table.put_item(Item=item)


def _seed_pod(table, org_id="org_01", pod_id="pod_01"):
    table.put_item(Item={
        "PK": f"ORG#{org_id}",
        "SK": f"POD#{pod_id}",
        "entity": "pod",
        "pod_id": pod_id,
        "org_id": org_id,
        "name": "Default Pod",
        "created_at": _TS,
    })


def _seed_message(table, inbox_id="inb_abc", msg_id="msg_01", org_id="org_01",
                  thread_id="thr_xyz"):
    table.put_item(Item={
        "PK": f"INBOX#{inbox_id}",
        "SK": f"MSG#{msg_id}",
        "entity": "message",
        "message_id": msg_id,
        "org_id": org_id,
        "inbox_id": inbox_id,
        "from_address": "alice@example.com",
        "from_display_name": "Alice",
        "to_addresses": ["bot@example.com"],
        "subject": "Hello Agent",
        "body_text": "Hi there",
        "body_html": "<p>Hi there</p>",
        "direction": "inbound",
        "status": "received",
        "thread_id": thread_id,
        "message_id_header": "<alice-1@example.com>",
        "in_reply_to": None,
        "references": [],
        "spf_pass": True,
        "dkim_pass": True,
        "dmarc_pass": True,
        "created_at": _TS,
    })


def _seed_thread(table, inbox_id="inb_abc", thread_id="thr_xyz", org_id="org_01"):
    table.put_item(Item={
        "PK": f"INBOX#{inbox_id}",
        "SK": f"THREAD#{thread_id}",
        "entity": "thread",
        "thread_id": thread_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "subject": "Hello Agent",
        "message_count": 1,
        "participants": ["alice@example.com"],
        "last_message_at": _TS,
        "created_at": _TS,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_migrate_organization_copies_as_is(both_tables):
    """Organization items are copied to agentcomms with SK normalised to META."""
    vm, ac = both_tables
    _seed_org(vm, org_id="org_01", name="Acme")

    migrator.migrate_orgs(vm, ac, dry_run=False, limit=None)

    resp = ac.get_item(Key={"PK": "ORG#org_01", "SK": "META"})
    item = resp.get("Item")
    assert item is not None, "Organization not found in destination"
    assert item["org_id"] == "org_01"
    assert item["name"] == "Acme"
    assert item["SK"] == "META"


def test_migrate_api_key_preserves_gsi1(both_tables):
    """API keys are migrated with gsi1_pk / gsi1_sk populated (lowercase)."""
    vm, ac = both_tables
    _seed_api_key(vm, org_id="org_01", key_hash="abc123", key_id="key_01")

    migrator.migrate_api_keys(vm, ac, dry_run=False, limit=None)

    resp = ac.get_item(Key={"PK": "ORG#org_01", "SK": "APIKEY#abc123"})
    item = resp.get("Item")
    assert item is not None, "ApiKey not found in destination"
    assert item["gsi1_pk"] == "APIKEY#abc123"
    assert item["gsi1_sk"] is not None
    # Legacy uppercase keys should not be present (or should have been migrated)
    assert "GSI1PK" not in item, "Legacy uppercase GSI1PK should have been migrated"


def test_migrate_inbox_creates_agent_and_channel(both_tables):
    """Each Inbox creates exactly one Agent and one email Channel."""
    vm, ac = both_tables
    _seed_inbox(vm, org_id="org_01", inbox_id="inb_abc", address="bot@example.com")

    migrator.migrate_inboxes_to_agents_and_channels(vm, ac, dry_run=False, limit=None)

    # Agent at PK=ORG#org_01 SK=AGT#agt_abc
    resp_agent = ac.get_item(Key={"PK": "ORG#org_01", "SK": "AGT#agt_abc"})
    agent = resp_agent.get("Item")
    assert agent is not None, "Agent not created"
    assert agent["agent_id"] == "agt_abc"
    assert agent["metadata"]["migrated_from_inbox"] == "inb_abc"

    # Channel at PK=AGT#agt_abc SK=CHAN#email#chan_em_abc
    resp_chan = ac.get_item(Key={"PK": "AGT#agt_abc", "SK": "CHAN#email#chan_em_abc"})
    chan = resp_chan.get("Item")
    assert chan is not None, "Channel not created"
    assert chan["channel"] == "email"
    assert chan["mode"] == "provision"
    assert chan["config"]["address"] == "bot@example.com"
    assert chan["gsi2_pk"] == "ADDR#email#bot@example.com"


def test_migrate_message_transforms_to_unified_message(both_tables):
    """Messages are migrated under AGT# PK with all GSI projections."""
    vm, ac = both_tables
    _seed_message(vm, inbox_id="inb_abc", msg_id="msg_01", org_id="org_01", thread_id="thr_xyz")

    migrator.migrate_messages(vm, ac, dry_run=False, limit=None)

    # Scan the destination for the message
    resp = ac.scan(FilterExpression="message_id = :mid", ExpressionAttributeValues={":mid": "msg_01"})
    items = resp.get("Items", [])
    assert len(items) == 1, f"Expected 1 message, found {len(items)}"
    msg = items[0]
    assert msg["PK"] == "AGT#agt_abc"
    assert msg["agent_id"] == "agt_abc"
    assert msg["channel_id"] == "chan_em_abc"
    assert msg["channel"] == "email"
    assert msg["is_dm"] is True
    assert msg["gsi3_pk"] == "AGT_DM#agt_abc"
    assert msg["gsi4_pk"] == "CHAN#chan_em_abc"
    # Thread key should be preserved
    assert msg["thread_key"] == "thr_xyz"
    assert msg["gsi5_pk"] == "THR#thr_xyz"
    # External ID from message_id_header
    assert msg["external_id"] == "<alice-1@example.com>"
    assert msg["gsi6_pk"] == "EXTID#email#<alice-1@example.com>"


def test_migrate_preserves_thread_key_across_messages(both_tables):
    """Thread items are migrated under AGT# PK and preserve the thread_key."""
    vm, ac = both_tables
    _seed_thread(vm, inbox_id="inb_abc", thread_id="thr_xyz", org_id="org_01")

    migrator.migrate_threads(vm, ac, dry_run=False, limit=None)

    resp = ac.get_item(Key={"PK": "AGT#agt_abc", "SK": "THR#email#thr_xyz"})
    item = resp.get("Item")
    assert item is not None, "Thread not found in destination"
    assert item["thread_key"] == "thr_xyz"
    assert item["agent_id"] == "agt_abc"
    assert item["native_thread_id"] == "thr_xyz"
    assert item["channel"] == "email"
    assert item["message_count"] == 1


def test_dry_run_writes_nothing_to_destination(both_tables):
    """--dry-run mode counts items but writes nothing to the destination table."""
    vm, ac = both_tables
    _seed_org(vm)
    _seed_api_key(vm)
    _seed_inbox(vm)
    _seed_message(vm)
    _seed_thread(vm)

    counts_org = migrator.migrate_orgs(vm, ac, dry_run=True, limit=None)
    counts_msg = migrator.migrate_messages(vm, ac, dry_run=True, limit=None)
    counts_ag, counts_ch = migrator.migrate_inboxes_to_agents_and_channels(vm, ac, dry_run=True, limit=None)

    # Nothing should be in the destination
    resp = ac.scan()
    assert resp.get("Items") == [], "Destination table should be empty in dry-run mode"

    # But counts should reflect what would have been written
    assert counts_org.processed == 1
    assert counts_msg.processed == 1
    assert counts_ag.processed == 1
    assert counts_ch.processed == 1


def test_idempotent_rerun_does_not_duplicate(both_tables):
    """Running the migration twice does not create duplicate items."""
    vm, ac = both_tables
    _seed_org(vm)
    _seed_inbox(vm)
    _seed_message(vm)

    # First run
    migrator.migrate_orgs(vm, ac, dry_run=False, limit=None)
    migrator.migrate_inboxes_to_agents_and_channels(vm, ac, dry_run=False, limit=None)
    migrator.migrate_messages(vm, ac, dry_run=False, limit=None)

    after_first = ac.scan()["Items"]

    # Second run
    counts_org = migrator.migrate_orgs(vm, ac, dry_run=False, limit=None)
    counts_ag, counts_ch = migrator.migrate_inboxes_to_agents_and_channels(vm, ac, dry_run=False, limit=None)
    counts_msg = migrator.migrate_messages(vm, ac, dry_run=False, limit=None)

    after_second = ac.scan()["Items"]

    assert len(after_first) == len(after_second), (
        f"Item count changed on second run: {len(after_first)} → {len(after_second)}"
    )
    # Second run should have skipped everything
    assert counts_org.skipped == 1
    assert counts_ag.skipped == 1
    assert counts_ch.skipped == 1
    assert counts_msg.skipped == 1


def test_pod_becomes_metadata_tag_on_agent(both_tables):
    """Pods are not copied to agentcomms; their pod_id is in Agent.metadata.pod."""
    vm, ac = both_tables
    _seed_pod(vm, org_id="org_01", pod_id="pod_01")
    _seed_inbox(vm, org_id="org_01", inbox_id="inb_abc", pod_id="pod_01")

    # Pods should not be written
    migrator.migrate_pods_warn(vm, limit=None)

    # Agent should carry pod metadata
    migrator.migrate_inboxes_to_agents_and_channels(vm, ac, dry_run=False, limit=None)

    resp = ac.get_item(Key={"PK": "ORG#org_01", "SK": "AGT#agt_abc"})
    agent = resp.get("Item")
    assert agent is not None, "Agent not created"
    assert agent["metadata"].get("pod") == "pod_01", (
        f"Expected pod='pod_01' in metadata, got {agent['metadata']}"
    )

    # Pods themselves should NOT be in the destination
    pod_scan = ac.scan(
        FilterExpression="begins_with(SK, :pfx)",
        ExpressionAttributeValues={":pfx": "POD#"},
    )
    assert pod_scan.get("Items") == [], "Pod items should not be in agentcomms"


def test_migrate_with_limit(both_tables):
    """--limit N stops after N items per entity type."""
    vm, ac = both_tables
    for i in range(5):
        _seed_org(vm, org_id=f"org_{i:02d}", name=f"Org {i}")

    counts = migrator.migrate_orgs(vm, ac, dry_run=False, limit=2)

    assert counts.processed == 2
    resp = ac.scan()
    # Only 2 orgs should have been written
    org_items = [it for it in resp["Items"] if it.get("SK") == "META"]
    assert len(org_items) == 2


def test_migrate_domain_adds_gsi7(both_tables):
    """Domains get gsi7_pk/gsi7_sk added for cross-org uniqueness."""
    vm, ac = both_tables
    vm.put_item(Item={
        "PK": "ORG#org_01",
        "SK": "DOMAIN#dom_01",
        "entity": "domain",
        "domain_id": "dom_01",
        "org_id": "org_01",
        "domain_name": "example.com",
        "status": "verified",
        "created_at": _TS,
        "updated_at": _TS,
    })

    migrator.migrate_domains(vm, ac, dry_run=False, limit=None)

    resp = ac.get_item(Key={"PK": "ORG#org_01", "SK": "DOM#dom_01"})
    item = resp.get("Item")
    assert item is not None, "Domain not found in destination"
    assert item.get("gsi7_pk") == "DOMAIN#example.com"
    assert item.get("gsi7_sk") == "ORG#org_01"
