# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""
Moto-backed unit tests for tools/rollback_to_victorymail.py.

Tests:
  1. basic_reverse_transform   — UnifiedMessage + Agent + Domain round-trip correctly
  2. dry_run                   — dry-run mode does NOT write to dest table
  3. cutover_timestamp_filter  — items created BEFORE the cutover are excluded
  4. idempotency               — running rollback twice does not duplicate rows
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest
import boto3
from moto import mock_aws

# Ensure repo root is on sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tools.legacy.rollback_to_victorymail as rollback

# ---------------------------------------------------------------------------
# DynamoDB table schemas
# ---------------------------------------------------------------------------

_AGENTCOMMS_SCHEMA = {
    "TableName": "agentcomms",
    "AttributeDefinitions": [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
    ],
    "KeySchema": [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    "BillingMode": "PAY_PER_REQUEST",
}

_VICTORYMAIL_SCHEMA = {
    "TableName": "victorymail",
    "AttributeDefinitions": [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
    ],
    "KeySchema": [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    "BillingMode": "PAY_PER_REQUEST",
}

_CUTOVER_TS = datetime(2026, 7, 17, 14, 0, 0, tzinfo=timezone.utc)
_AFTER_TS   = "2026-07-17T14:05:00+00:00"   # after cutover
_BEFORE_TS  = "2026-07-17T13:55:00+00:00"   # before cutover


@pytest.fixture
def tables():
    """Provide moto-backed agentcomms + victorymail tables."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(**_AGENTCOMMS_SCHEMA)
        ddb.create_table(**_VICTORYMAIL_SCHEMA)
        ac = ddb.Table("agentcomms")
        vm = ddb.Table("victorymail")
        ac.wait_until_exists()
        vm.wait_until_exists()
        yield ac, vm


# ---------------------------------------------------------------------------
# Test 1: Basic reverse transform
# ---------------------------------------------------------------------------

def test_basic_reverse_transform(tables):
    """
    Seed agentcomms with a UnifiedMessage, Agent, and Domain all created
    AFTER cutover. Run rollback; verify all three appear in victorymail with
    correct legacy shapes.
    """
    ac, vm = tables

    # Seed: UnifiedMessage
    ac.put_item(Item={
        "PK":         "ORG#org_01",
        "SK":         "MSG#msg_new",
        "entity":     "unified_message",
        "message_id": "msg_new",
        "org_id":     "org_01",
        "agent_id":   "agt_abc",
        "direction":  "inbound",
        "status":     "received",
        "subject":    "Hello",
        "body_text":  "world",
        "body_html":  "",
        "from_address": "alice@example.com",
        "to_addresses": ["bot@example.com"],
        "thread_id":  None,
        "created_at": _AFTER_TS,
        "updated_at": _AFTER_TS,
    })

    # Seed: Agent
    ac.put_item(Item={
        "PK":         "ORG#org_01",
        "SK":         "AGENT#agt_abc",
        "entity":     "agent",
        "agent_id":   "agt_abc",
        "org_id":     "org_01",
        "display_name": "My Bot",
        "created_at": _AFTER_TS,
        "updated_at": _AFTER_TS,
    })

    # Seed: Domain
    ac.put_item(Item={
        "PK":        "ORG#org_01",
        "SK":        "DOMAIN#dom_01",
        "entity":    "domain",
        "domain_id": "dom_01",
        "org_id":    "org_01",
        "domain":    "example.com",
        "status":    "active",
        "dkim_tokens": [],
        "created_at": _AFTER_TS,
        "updated_at": _AFTER_TS,
    })

    rc = rollback.run_rollback(ac, vm, _CUTOVER_TS, dry_run=False)
    assert rc == 0

    # Verify UnifiedMessage → legacy Message
    msg = vm.get_item(Key={"PK": "ORG#org_01", "SK": "MSG#msg_new"})["Item"]
    assert msg["entity"] == "message"
    assert msg["inbox_id"] == "inb_abc"       # agt_abc → inb_abc
    assert msg["subject"] == "Hello"

    # Verify Agent → legacy Inbox
    inbox = vm.get_item(Key={"PK": "ORG#org_01", "SK": "INBOX#inb_abc"})["Item"]
    assert inbox["entity"] == "inbox"
    assert inbox["inbox_id"] == "inb_abc"
    assert inbox["display_name"] == "My Bot"

    # Verify Domain round-trip
    dom = vm.get_item(Key={"PK": "ORG#org_01", "SK": "DOMAIN#dom_01"})["Item"]
    assert dom["entity"] == "domain"
    assert dom["domain"] == "example.com"


# ---------------------------------------------------------------------------
# Test 2: Dry-run does not write
# ---------------------------------------------------------------------------

def test_dry_run_does_not_write(tables):
    """Dry-run mode must not write anything to the destination table."""
    ac, vm = tables

    ac.put_item(Item={
        "PK":         "ORG#org_01",
        "SK":         "MSG#msg_dryrun",
        "entity":     "unified_message",
        "message_id": "msg_dryrun",
        "org_id":     "org_01",
        "agent_id":   "agt_xyz",
        "direction":  "inbound",
        "status":     "received",
        "subject":    "Dry test",
        "body_text":  "body",
        "body_html":  "",
        "from_address": "a@b.com",
        "to_addresses": [],
        "created_at": _AFTER_TS,
        "updated_at": _AFTER_TS,
    })

    rc = rollback.run_rollback(ac, vm, _CUTOVER_TS, dry_run=True)
    assert rc == 0

    # Nothing written to victorymail
    result = vm.scan()
    assert result["Count"] == 0


# ---------------------------------------------------------------------------
# Test 3: Cutover-timestamp filter excludes pre-cutover items
# ---------------------------------------------------------------------------

def test_cutover_timestamp_filter(tables):
    """
    Items with created_at BEFORE the cutover timestamp must be ignored;
    only post-cutover items get reverse-mapped.
    """
    ac, vm = tables

    # Pre-cutover item — should be excluded
    ac.put_item(Item={
        "PK":         "ORG#org_01",
        "SK":         "MSG#msg_old",
        "entity":     "unified_message",
        "message_id": "msg_old",
        "org_id":     "org_01",
        "agent_id":   "agt_old",
        "direction":  "inbound",
        "status":     "received",
        "subject":    "Before cutover",
        "body_text":  "",
        "body_html":  "",
        "from_address": "a@b.com",
        "to_addresses": [],
        "created_at": _BEFORE_TS,
        "updated_at": _BEFORE_TS,
    })

    # Post-cutover item — should be included
    ac.put_item(Item={
        "PK":         "ORG#org_01",
        "SK":         "MSG#msg_new",
        "entity":     "unified_message",
        "message_id": "msg_new",
        "org_id":     "org_01",
        "agent_id":   "agt_new",
        "direction":  "inbound",
        "status":     "received",
        "subject":    "After cutover",
        "body_text":  "",
        "body_html":  "",
        "from_address": "a@b.com",
        "to_addresses": [],
        "created_at": _AFTER_TS,
        "updated_at": _AFTER_TS,
    })

    rc = rollback.run_rollback(ac, vm, _CUTOVER_TS, dry_run=False)
    assert rc == 0

    # Only the post-cutover message should be in victorymail
    result = vm.scan()
    pks = [item["SK"] for item in result["Items"]]
    assert "MSG#msg_new" in pks
    assert "MSG#msg_old" not in pks


# ---------------------------------------------------------------------------
# Test 4: Idempotency — running twice does not error or duplicate
# ---------------------------------------------------------------------------

def test_idempotency(tables):
    """
    Running rollback twice against the same source data must not raise errors
    or create duplicate items (attribute_not_exists guard).
    """
    ac, vm = tables

    ac.put_item(Item={
        "PK":         "ORG#org_01",
        "SK":         "DOMAIN#dom_dup",
        "entity":     "domain",
        "domain_id":  "dom_dup",
        "org_id":     "org_01",
        "domain":     "dup-test.com",
        "status":     "active",
        "dkim_tokens": [],
        "created_at": _AFTER_TS,
        "updated_at": _AFTER_TS,
    })

    rc1 = rollback.run_rollback(ac, vm, _CUTOVER_TS, dry_run=False)
    rc2 = rollback.run_rollback(ac, vm, _CUTOVER_TS, dry_run=False)

    assert rc1 == 0
    assert rc2 == 0

    # Exactly one domain item in victorymail (not two)
    result = vm.scan()
    domains = [i for i in result["Items"] if i.get("entity") == "domain"]
    assert len(domains) == 1
    assert domains[0]["domain"] == "dup-test.com"
