# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

from __future__ import annotations

from typing import Any, Protocol


class EventPublisher(Protocol):
    def publish(self, *, event_type: str, partition_key: str, data: dict[str, Any]) -> None:
        """Publish a normalized domain event."""


class NoopEventPublisher:
    def publish(self, *, event_type: str, partition_key: str, data: dict[str, Any]) -> None:
        return None

