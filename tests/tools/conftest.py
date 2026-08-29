# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""
Shared fixtures for tools/ tests.

Provides `agentcomms_table` (from root conftest via inheritance) and a new
`victorymail_table` seeded with legacy-schema entities.
"""
from __future__ import annotations

import os
import pytest
import boto3
from moto import mock_aws

# Env vars required by moto
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")


# ---------------------------------------------------------------------------
# Legacy victorymail table schema (mirrors real table GSI structure)
# ---------------------------------------------------------------------------

_VICTORYMAIL_SCHEMA = {
    "TableName": "victorymail",
    "AttributeDefinitions": [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
        {"AttributeName": "GSI1PK", "AttributeType": "S"},
        {"AttributeName": "GSI1SK", "AttributeType": "S"},
        {"AttributeName": "GSI2PK", "AttributeType": "S"},
        {"AttributeName": "GSI2SK", "AttributeType": "S"},
        {"AttributeName": "GSI3PK", "AttributeType": "S"},
        {"AttributeName": "GSI3SK", "AttributeType": "S"},
    ],
    "KeySchema": [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    "BillingMode": "PAY_PER_REQUEST",
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "GSI1",
            "KeySchema": [
                {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
        {
            "IndexName": "GSI2",
            "KeySchema": [
                {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
        {
            "IndexName": "GSI3",
            "KeySchema": [
                {"AttributeName": "GSI3PK", "KeyType": "HASH"},
                {"AttributeName": "GSI3SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
}

# ---------------------------------------------------------------------------
# agentcomms table schema (reused from root conftest)
# ---------------------------------------------------------------------------

_AGENTCOMMS_TABLE_SCHEMA = {
    "TableName": "agentcomms",
    "AttributeDefinitions": [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
        {"AttributeName": "gsi1_pk", "AttributeType": "S"},
        {"AttributeName": "gsi1_sk", "AttributeType": "S"},
        {"AttributeName": "gsi2_pk", "AttributeType": "S"},
        {"AttributeName": "gsi2_sk", "AttributeType": "S"},
        {"AttributeName": "gsi3_pk", "AttributeType": "S"},
        {"AttributeName": "gsi3_sk", "AttributeType": "S"},
        {"AttributeName": "gsi4_pk", "AttributeType": "S"},
        {"AttributeName": "gsi4_sk", "AttributeType": "S"},
        {"AttributeName": "gsi5_pk", "AttributeType": "S"},
        {"AttributeName": "gsi5_sk", "AttributeType": "S"},
        {"AttributeName": "gsi6_pk", "AttributeType": "S"},
        {"AttributeName": "gsi6_sk", "AttributeType": "S"},
        {"AttributeName": "gsi7_pk", "AttributeType": "S"},
        {"AttributeName": "gsi7_sk", "AttributeType": "S"},
    ],
    "KeySchema": [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    "BillingMode": "PAY_PER_REQUEST",
    "GlobalSecondaryIndexes": [
        {
            "IndexName": f"GSI{i}",
            "KeySchema": [
                {"AttributeName": f"gsi{i}_pk", "KeyType": "HASH"},
                {"AttributeName": f"gsi{i}_sk", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
        for i in range(1, 8)
    ],
}


@pytest.fixture
def both_tables():
    """Moto-backed victorymail + agentcomms tables in the same mock_aws context."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(**_VICTORYMAIL_SCHEMA)
        dynamodb.create_table(**_AGENTCOMMS_TABLE_SCHEMA)
        vm_table = dynamodb.Table("victorymail")
        ac_table = dynamodb.Table("agentcomms")
        vm_table.wait_until_exists()
        ac_table.wait_until_exists()
        yield vm_table, ac_table
