# conftest.py (root)
# Re-export AgentComms Phase 1 shared fixtures so they are discoverable by
# both tests/ and adapters/ test trees.
from tests.conftest import (  # noqa: F401
    aws_mock,
    agentcomms_table,
    ses_client,
    s3_buckets,
    sns_topic,
    kinesis_stream,
    repo_fixture,
)
