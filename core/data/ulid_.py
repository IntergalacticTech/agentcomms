# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

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
