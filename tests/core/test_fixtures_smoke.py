import pytest

def test_agentcomms_table_fixture_exists(agentcomms_table):
    """Fixture provides a moto-backed DynamoDB table named 'agentcomms' with all 7 GSIs."""
    assert agentcomms_table.table_name == "agentcomms"
    gsi_names = {gsi["IndexName"] for gsi in agentcomms_table.global_secondary_indexes}
    assert gsi_names == {"GSI1", "GSI2", "GSI3", "GSI4", "GSI5", "GSI6", "GSI7"}

def test_ses_client_fixture_exists(ses_client):
    """Fixture provides a moto-backed SES client."""
    response = ses_client.list_identities()
    assert "Identities" in response

def test_s3_buckets_fixture_exists(s3_buckets):
    """Fixture provides the three agentcomms S3 buckets."""
    assert set(s3_buckets.keys()) == {"raw_inbound", "bodies", "attachments"}
