"""Shared pytest fixtures for FreeMail tests."""

import os

import boto3
import pytest
from moto import mock_aws

# Set environment variables before any imports that might use them
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"


# ---------------------------------------------------------------------------
# AgentComms Phase 1 fixtures (moto-backed)
# ---------------------------------------------------------------------------

os.environ.setdefault("AGENTCOMMS_TABLE", "agentcomms")

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
def aws_mock():
    """Activate moto for all AWS clients in the test."""
    with mock_aws():
        yield


@pytest.fixture
def agentcomms_table(aws_mock):
    """Moto-backed DynamoDB table 'agentcomms' with all 7 GSIs."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(**_AGENTCOMMS_TABLE_SCHEMA)
    table = dynamodb.Table("agentcomms")
    table.wait_until_exists()
    return table


@pytest.fixture
def ses_client(aws_mock):
    return boto3.client("ses", region_name="us-east-1")


@pytest.fixture
def s3_buckets(aws_mock):
    s3 = boto3.client("s3", region_name="us-east-1")
    buckets = {
        "raw_inbound": "agentcomms-raw-inbound-test",
        "bodies": "agentcomms-bodies-test",
        "attachments": "agentcomms-attachments-test",
    }
    for name in buckets.values():
        s3.create_bucket(Bucket=name)
    os.environ["AGENTCOMMS_BUCKET_RAW_INBOUND"] = buckets["raw_inbound"]
    os.environ["AGENTCOMMS_BUCKET_BODIES"] = buckets["bodies"]
    os.environ["AGENTCOMMS_BUCKET_ATTACHMENTS"] = buckets["attachments"]
    return buckets


@pytest.fixture
def sns_topic(aws_mock):
    sns = boto3.client("sns", region_name="us-east-1")
    resp = sns.create_topic(Name="agentcomms-events-test")
    return resp["TopicArn"]


@pytest.fixture
def kinesis_stream(aws_mock):
    kinesis = boto3.client("kinesis", region_name="us-east-1")
    kinesis.create_stream(StreamName="agentcomms-events-test", ShardCount=1)
    os.environ["AGENTCOMMS_EVENT_STREAM"] = "agentcomms-events-test"
    return "agentcomms-events-test"


@pytest.fixture
def repo_fixture(agentcomms_table):
    from core.data.repo import Repo
    return Repo(table=agentcomms_table)


@pytest.fixture
def kms_key(aws_mock):
    """Create a moto-backed KMS CMK and expose its KeyId via env var."""
    kms = boto3.client("kms", region_name="us-east-1")
    resp = kms.create_key(
        Description="test vault key",
        KeyUsage="ENCRYPT_DECRYPT",
        KeySpec="SYMMETRIC_DEFAULT",
    )
    key_id = resp["KeyMetadata"]["KeyId"]
    os.environ["AGENTCOMMS_VAULT_KMS_KEY_ID"] = key_id
    yield key_id
    # Cleanup env var after test
    os.environ.pop("AGENTCOMMS_VAULT_KMS_KEY_ID", None)
