# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core.adapters.base import (
    ChannelAdapter,
    HealthStatus,
    IngestPayload,
    OutboundMessage,
    ProvisionResult,
    SendResult,
)
from core.data.models import Agent, Channel, UnifiedMessage
from core.data.ulid_ import new_id

from .normalize import normalize_echo_event


class EchoAdapter(ChannelAdapter):
    """Small external adapter example with no provider dependency."""

    channel_name = "echo"
    supports_modes = ["provision"]

    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult:
        address = str(config.get("address") or f"echo:{agent.agent_id}")
        channel_id = str(config.get("channel_id") or new_id("chan", suffix="ec"))
        return ProvisionResult(
            status="active",
            channel_id=channel_id,
            details={
                "address": address,
                "provider": "echo",
            },
        )

    def teardown(self, *, channel: Channel) -> None:
        return None

    def health_check(self, *, channel: Channel) -> HealthStatus:
        return HealthStatus(
            ok=channel.channel.value == self.channel_name,
            last_success_at=datetime.now(timezone.utc).isoformat(),
            error=None if channel.channel.value == self.channel_name else "wrong channel type",
        )

    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None:
        body = payload.body
        if isinstance(body, bytes):
            body = json.loads(body.decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("echo payload body must be a JSON object")

        agent_id = payload.path_params.get("agent_id") or body.get("agent_id")
        org_id = payload.path_params.get("org_id") or body.get("org_id")
        channel_id = payload.path_params.get("channel_id") or body.get("channel_id")
        if not agent_id or not org_id or not channel_id:
            raise ValueError("agent_id, org_id, and channel_id are required")

        return normalize_echo_event(
            body=body,
            agent_id=str(agent_id),
            org_id=str(org_id),
            channel_id=str(channel_id),
        )

    def send(self, *, channel: Channel, message: OutboundMessage) -> SendResult:
        target = message.to if isinstance(message.to, str) else message.to.get("address", "")
        native_id = new_id("echo")
        return SendResult(
            channel_native_id=native_id,
            status="sent" if target and message.body_text else "failed",
            error=None if target and message.body_text else "target and body_text are required",
        )
