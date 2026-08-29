# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

from __future__ import annotations

from typing import Protocol


class BlobStore(Protocol):
    def get_bytes(self, *, bucket: str, key: str) -> bytes:
        """Return object bytes for a provider-specific blob location."""

    def put_bytes(
        self, *, bucket: str, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Store bytes at a provider-specific blob location; return the key."""

