# SPDX-License-Identifier: FSL-1.1-Apache-2.0
"""Ingest Lambdas must publish message.received through the shared
core.providers KinesisEventPublisher (not hand-rolled boto3 kinesis)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.providers.aws.events import KinesisEventPublisher
import adapters.sms.ingest as sms_ingest
import adapters.slack.ingest as slack_ingest
import adapters.telegram.ingest as telegram_ingest


@pytest.mark.parametrize("mod", [sms_ingest, slack_ingest, telegram_ingest])
def test_event_publisher_is_kinesis_provider(mod):
    mod._event_publisher = None  # reset singleton
    pub = mod._get_event_publisher()
    assert isinstance(pub, KinesisEventPublisher)
    # cached singleton
    assert mod._get_event_publisher() is pub
    mod._event_publisher = None


class _FakeMsg:
    agent_id = "agt_9"

    def model_dump_json(self, by_alias=False):
        return json.dumps({"agent_id": "agt_9", "message_id": "m1"})


def test_sms_handler_publishes_via_provider():
    fake_pub = MagicMock()
    fake_adapter = MagicMock()
    fake_adapter.ingest.return_value = _FakeMsg()

    sms_ingest._event_publisher = fake_pub
    event = {"Records": [{"Sns": {"Message": "{}"}}]}
    try:
        with patch.object(sms_ingest, "_adapter", fake_adapter), \
             patch.object(sms_ingest, "Repo", return_value=MagicMock()), \
             patch.object(sms_ingest, "_get_table", return_value=None):
            result = sms_ingest.handler(event, None)
    finally:
        sms_ingest._event_publisher = None

    assert result == {"processed": 1}
    fake_pub.publish.assert_called_once()
    kwargs = fake_pub.publish.call_args.kwargs
    assert kwargs["event_type"] == "message.received"
    assert kwargs["partition_key"] == "agt_9"
    assert kwargs["data"]["agent_id"] == "agt_9"
