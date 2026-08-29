# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/data/ulid_.py
"""Thin wrapper around python-ulid with project ID-prefix conventions."""
from __future__ import annotations

from ulid import ULID


def new_id(prefix: str, suffix: str | None = None) -> str:
    """Return a new prefixed ULID: '{prefix}_{suffix}_{ULID26}' or '{prefix}_{ULID26}'."""
    ulid_str = str(ULID())
    if suffix:
        return f"{prefix}_{suffix}_{ulid_str}"
    return f"{prefix}_{ulid_str}"
