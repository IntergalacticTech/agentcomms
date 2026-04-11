"""Shared pytest fixtures for FreeMail tests."""

import os

import boto3
import pytest
from moto import mock_aws

# Set environment variables before any imports that might use them
os.environ["TABLE_NAME"] = "victorymail"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ["BODY_BUCKET"] = "victorymail-bodies"
os.environ["ATTACHMENT_BUCKET"] = "victorymail-attachments"
os.environ["EMAIL_BUCKET"] = "victorymail-raw-email"


def _create_table(dynamodb):
    """Create the DynamoDB table with all GSIs."""
    gsi_definitions = []
    attribute_definitions = [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
    ]

    for i in range(1, 4):
        pk_name = f"GSI{i}PK"
        sk_name = f"GSI{i}SK"
        attribute_definitions.extend([
            {"AttributeName": pk_name, "AttributeType": "S"},
            {"AttributeName": sk_name, "AttributeType": "S"},
        ])
        gsi_definitions.append({
            "IndexName": f"GSI{i}",
            "KeySchema": [
                {"AttributeName": pk_name, "KeyType": "HASH"},
                {"AttributeName": sk_name, "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        })

    table = dynamodb.create_table(
        TableName="victorymail",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=attribute_definitions,
        GlobalSecondaryIndexes=gsi_definitions,
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


@pytest.fixture
def aws_env():
    """Provide mocked AWS environment with DynamoDB table and S3 buckets."""
    import shared.dynamo as dynamo_mod
    import shared.s3 as s3_mod

    with mock_aws():
        # Reset singletons
        dynamo_mod._table = None
        s3_mod._s3 = None

        # Create DynamoDB table
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_table(dynamodb)

        # Create S3 buckets
        s3_client = boto3.client("s3", region_name="us-east-1")
        for bucket in ["victorymail-bodies", "victorymail-attachments", "victorymail-raw-email"]:
            s3_client.create_bucket(Bucket=bucket)

        yield {"table": table, "s3": s3_client}

        # Clean up singletons
        dynamo_mod._table = None
        s3_mod._s3 = None
