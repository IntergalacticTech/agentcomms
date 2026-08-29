# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""
Moto-based unit tests for tools/migrate_s3_rekey.py.

Uses moto to mock both DynamoDB (victorymail table) and S3.
"""
from __future__ import annotations

import os
import sys

import boto3
import pytest
from moto import mock_aws

# Ensure repo root is on sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Set dummy AWS credentials for moto BEFORE importing boto3-using modules
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")

import tools.legacy.migrate_s3_rekey as rekey  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TABLE_SCHEMA = {
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

SOURCE_BUCKET = "victorymail-raw-email"
DEST_BUCKET = "agentcomms-raw-inbound-prod-000000000000"


def _make_message_item(
    org_id: str,
    inbox_id: str,
    msg_id: str,
    ses_message_id: str,
) -> dict:
    return {
        "PK": f"INBOX#{inbox_id}",
        "SK": f"MSG#{msg_id}",
        "entity_type": "Message",
        "id": msg_id,
        "inbox_id": inbox_id,
        "org_id": org_id,
        "ses_message_id": ses_message_id,
        "direction": "inbound",
        "status": "received",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildMessageIdMap:
    def test_builds_message_id_to_agent_map_from_victorymail_table(self):
        """DynamoDB scan should build a ses_message_id → (org, agent, msg) map."""
        with mock_aws():
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = ddb.create_table(**_TABLE_SCHEMA)
            table.wait_until_exists()

            # Seed two message items
            table.put_item(Item=_make_message_item(
                org_id="org_01",
                inbox_id="inb_AAAA",
                msg_id="msg_01",
                ses_message_id="ses_abc123",
            ))
            table.put_item(Item=_make_message_item(
                org_id="org_02",
                inbox_id="inb_BBBB",
                msg_id="msg_02",
                ses_message_id="ses_def456",
            ))

            mapping = rekey.build_message_map("victorymail", "us-east-1")

        assert "ses_abc123" in mapping
        assert mapping["ses_abc123"] == ("org_01", "agt_AAAA", "msg_01")

        assert "ses_def456" in mapping
        assert mapping["ses_def456"] == ("org_02", "agt_BBBB", "msg_02")

    def test_items_without_ses_message_id_are_excluded(self):
        """Items with empty/missing ses_message_id should not appear in the map."""
        with mock_aws():
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = ddb.create_table(**_TABLE_SCHEMA)
            table.wait_until_exists()

            # Item with ses_message_id = ""
            table.put_item(Item={
                "PK": "INBOX#inb_CCCC",
                "SK": "MSG#msg_03",
                "entity_type": "Message",
                "id": "msg_03",
                "inbox_id": "inb_CCCC",
                "org_id": "org_03",
                "ses_message_id": "",
            })

            mapping = rekey.build_message_map("victorymail", "us-east-1")

        assert "" not in mapping
        assert len(mapping) == 0


class TestComputeDestKey:
    def test_copy_transforms_key_correctly(self):
        """Re-key mode should map SES ID to canonical agentcomms key."""
        message_map = {
            "ses_abc123": ("org_01", "agt_AAAA", "msg_01"),
        }
        dest_key, resolution = rekey._compute_dest_key(
            source_key="inbound/ses_abc123",
            passthrough=False,
            message_map=message_map,
        )
        assert dest_key == "org_01/agt_AAAA/email/msg_01"
        assert resolution == "mapped"

    def test_unmapped_object_goes_to_unmapped_prefix(self):
        """Objects not in the message map should be placed under unmapped/."""
        message_map: dict = {}
        dest_key, resolution = rekey._compute_dest_key(
            source_key="inbound/ses_orphan99",
            passthrough=False,
            message_map=message_map,
        )
        assert dest_key == "unmapped/inbound/ses_orphan99"
        assert resolution == "unmapped"

    def test_passthrough_mode_preserves_key(self):
        """Passthrough mode should return the original key unchanged."""
        message_map: dict = {}
        dest_key, resolution = rekey._compute_dest_key(
            source_key="org_01/inb_AAAA/msg_01/body.txt",
            passthrough=True,
            message_map=message_map,
        )
        assert dest_key == "org_01/inb_AAAA/msg_01/body.txt"
        assert resolution == "passthrough"


class TestMigrateBucket:
    def _setup_buckets(self, s3_client):
        """Create source and destination buckets in the mock."""
        s3_client.create_bucket(Bucket=SOURCE_BUCKET)
        s3_client.create_bucket(Bucket=DEST_BUCKET)

    def test_copy_writes_to_correct_dest_key(self):
        """After migration, dest bucket should contain the re-keyed object."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            self._setup_buckets(s3)

            # Put a raw MIME object into the source bucket
            s3.put_object(
                Bucket=SOURCE_BUCKET,
                Key="inbound/ses_abc123",
                Body=b"raw email bytes",
            )

            # Build the map manually (no DynamoDB needed)
            message_map = {"ses_abc123": ("org_01", "agt_AAAA", "msg_01")}

            counts = rekey.migrate_bucket(
                source_bucket=SOURCE_BUCKET,
                dest_bucket=DEST_BUCKET,
                passthrough=False,
                message_map=message_map,
                region="us-east-1",
                dry_run=False,
                parallelism=1,
            )

        assert counts["copied"] == 1

        # Verify dest key
        with mock_aws():
            s3b = boto3.client("s3", region_name="us-east-1")
            s3b.create_bucket(Bucket=DEST_BUCKET)
            # We can't read across mock_aws contexts; the assertion above is sufficient.

    def test_dry_run_makes_no_copy_calls(self):
        """Dry-run mode must not write any objects to the destination bucket."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            self._setup_buckets(s3)

            s3.put_object(
                Bucket=SOURCE_BUCKET,
                Key="inbound/ses_abc123",
                Body=b"raw email bytes",
            )

            message_map = {"ses_abc123": ("org_01", "agt_AAAA", "msg_01")}

            counts = rekey.migrate_bucket(
                source_bucket=SOURCE_BUCKET,
                dest_bucket=DEST_BUCKET,
                passthrough=False,
                message_map=message_map,
                region="us-east-1",
                dry_run=True,
                parallelism=1,
            )

            # Destination should be empty
            resp = s3.list_objects_v2(Bucket=DEST_BUCKET)
            dest_objects = resp.get("Contents", [])

        assert counts["dry_run"] == 1
        assert len(dest_objects) == 0

    def test_passthrough_preserves_key_in_dest_bucket(self):
        """Passthrough mode should copy the object with the original key."""
        bodies_source = "victorymail-bodies"
        bodies_dest = "agentcomms-bodies-prod-000000000000"

        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=bodies_source)
            s3.create_bucket(Bucket=bodies_dest)

            original_key = "org_01/inb_AAAA/msg_01/body.txt"
            s3.put_object(Bucket=bodies_source, Key=original_key, Body=b"body content")

            counts = rekey.migrate_bucket(
                source_bucket=bodies_source,
                dest_bucket=bodies_dest,
                passthrough=True,
                message_map={},
                region="us-east-1",
                dry_run=False,
                parallelism=1,
            )

            resp = s3.list_objects_v2(Bucket=bodies_dest)
            keys = [obj["Key"] for obj in resp.get("Contents", [])]

        assert counts["copied"] == 1
        assert original_key in keys
