# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

from __future__ import annotations

from typing import Any, Protocol


class EventPublisher(Protocol):
    def publish(self, *, event_type: str, partition_key: str, data: dict[str, Any]) -> None:
        """Publish a normalized domain event."""


class NoopEventPublisher:
    def publish(self, *, event_type: str, partition_key: str, data: dict[str, Any]) -> None:
        return None

