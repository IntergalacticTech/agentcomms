# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/adapters/base.py
"""
ChannelAdapter contract and support types.

Every channel plugin implements ChannelAdapter. The hub core interacts with
adapters only through this interface. Adapters never touch DynamoDB or Kinesis
directly — they return normalized data and the core does persistence.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from core.data.models import Agent, Channel, UnifiedMessage


class IngestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    source: str               # "sns" | "api_gateway" | "s3_event"
    headers: dict[str, str] = {}
    body: bytes | dict[str, Any]
    path_params: dict[str, str] = {}


class OutboundMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str | dict[str, Any]
    body_text: str
    body_html: str | None = None
    subject: str | None = None
    attachments: list[dict[str, Any]] = []
    thread_key: str | None = None
    channel_native_overrides: dict[str, Any] = {}


class SendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_native_id: str
    status: str                 # "sent" | "queued" | "failed"
    error: str | None = None


class NativeContainer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    type: str
    metadata: dict[str, Any] = {}


class ProvisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    channel_id: str
    details: dict[str, Any]


class BridgeStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    oauth_url: str
    state: str
    instructions: str = ""


class BridgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    channel_id: str
    details: dict[str, Any]


class HealthStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    last_success_at: str
    error: str | None = None


class ChannelAdapter(ABC):
    """Every channel adapter implements this."""

    channel_name: str
    supports_modes: list[Literal["provision", "bridge"]]

    # ── Lifecycle ─────────────────────────────────────────────────
    @abstractmethod
    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult: ...

    def bridge_start(self, *, agent: Agent, config: dict[str, Any]) -> BridgeStart:
        raise NotImplementedError(f"{self.channel_name} does not support bridge mode")

    def bridge_complete(
        self, *, channel: Channel, callback_params: dict[str, Any]
    ) -> BridgeResult:
        raise NotImplementedError(f"{self.channel_name} does not support bridge mode")

    @abstractmethod
    def teardown(self, *, channel: Channel) -> None: ...

    @abstractmethod
    def health_check(self, *, channel: Channel) -> HealthStatus: ...

    # ── Messaging ─────────────────────────────────────────────────
    @abstractmethod
    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None: ...

    @abstractmethod
    def send(
        self, *, channel: Channel, message: OutboundMessage
    ) -> SendResult: ...

    # ── Native sub-surfaces (optional) ────────────────────────────
    def list_native_containers(self, *, channel: Channel) -> list[NativeContainer]:
        return []

    def list_native_messages(
        self, *, channel: Channel, container_id: str, **filters: Any
    ) -> list[UnifiedMessage]:
        return []

    def send_to_native_target(
        self, *, channel: Channel, target: dict[str, Any], message: OutboundMessage,
    ) -> SendResult:
        return self.send(channel=channel, message=message)

    # ── CDK wiring (deploy time) ──────────────────────────────────
    def cdk_wiring(self, *, stack: Any, context: Any) -> None:
        """Override in subclasses that need CDK-level AWS resources."""
        return None
