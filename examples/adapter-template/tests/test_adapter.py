# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentcomms_adapter_echo import EchoAdapter
from core.adapters.base import IngestPayload, OutboundMessage
from core.data.models import (
    Agent,
    Channel,
    ChannelMode,
    ChannelStatus,
    ChannelType,
    MessageDirection,
)


def _agent() -> Agent:
    return Agent(agent_id="agt_123", org_id="org_123", name="Echo Bot")


def _channel(adapter: EchoAdapter) -> Channel:
    result = adapter.provision(agent=_agent(), config={"address": "echo:ops"})
    return Channel(
        channel_id=result.channel_id,
        agent_id="agt_123",
        org_id="org_123",
        channel=ChannelType(adapter.channel_name),
        mode=ChannelMode.PROVISION,
        config=result.details,
        status=ChannelStatus.ACTIVE,
        address_index_value=result.details["address"],
    )


def test_provision_returns_external_channel_details():
    adapter = EchoAdapter()
    channel = _channel(adapter)

    item = channel.to_dynamodb_item()
    assert item["channel"] == "echo"
    assert item["SK"].startswith("CHAN#echo#chan_ec_")
    assert item["gsi2_pk"] == "ADDR#echo#echo:ops"


def test_ingest_normalizes_inbound_payload():
    adapter = EchoAdapter()
    body = {
        "id": "evt_1",
        "from": "person:alice",
        "from_name": "Alice",
        "to": "echo:ops",
        "text": "ping",
        "room": "ops",
    }
    payload = IngestPayload(
        source="api_gateway",
        headers={},
        body=json.dumps(body).encode("utf-8"),
        path_params={
            "agent_id": "agt_123",
            "org_id": "org_123",
            "channel_id": "chan_ec_123",
        },
    )

    message = adapter.ingest(payload=payload)

    assert message is not None
    assert message.channel.value == "echo"
    assert message.direction == MessageDirection.INBOUND
    assert message.from_.address == "person:alice"
    assert message.to[0].address == "echo:ops"
    assert message.thread_key == "ops"
    assert message.external_id == "evt_1"


def test_ingest_drops_non_message_events():
    adapter = EchoAdapter()
    payload = IngestPayload(
        source="api_gateway",
        headers={},
        body={"type": "presence"},
        path_params={
            "agent_id": "agt_123",
            "org_id": "org_123",
            "channel_id": "chan_ec_123",
        },
    )

    assert adapter.ingest(payload=payload) is None


def test_send_returns_provider_native_id():
    adapter = EchoAdapter()
    channel = _channel(adapter)
    result = adapter.send(
        channel=channel,
        message=OutboundMessage(to="person:alice", body_text="pong"),
    )

    assert result.status == "sent"
    assert result.channel_native_id.startswith("echo_")
