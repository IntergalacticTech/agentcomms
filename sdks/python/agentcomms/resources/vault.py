# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""Vault resource — org-scoped secret storage and TOTP."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from agentcomms.models import VaultItem

if TYPE_CHECKING:
    from agentcomms.client import Client


class VaultResource:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def create(
        self,
        *,
        label: str | None = None,
        value: str | None = None,
        name: str | None = None,
        seed: str | None = None,
        type: str = "secret",
        tags: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> VaultItem:
        item_label = label or name
        if not item_label:
            raise ValueError("label is required")
        body: dict[str, Any] = {"label": item_label, "type": type}
        if type == "totp":
            body["seed"] = seed if seed is not None else value
        elif value is not None:
            body["value"] = value
        if tags is not None:
            body["tags"] = tags
        elif metadata:
            body["tags"] = metadata
        data = self._client._request("POST", "/vault", json=body)
        return VaultItem.model_validate(data)

    def list(self) -> list[VaultItem]:
        data = self._client._request("GET", "/vault")
        return [VaultItem.model_validate(v) for v in data.get("items", [])]

    def get(self, vault_id: str) -> VaultItem:
        data = self._client._request("GET", f"/vault/{vault_id}")
        return VaultItem.model_validate(data)

    def get_totp(self, vault_id: str) -> dict[str, Any]:
        """Generate a TOTP code from a stored TOTP secret."""
        return self._client._request("GET", f"/vault/{vault_id}/totp")

    def delete(self, vault_id: str) -> None:
        self._client._request("DELETE", f"/vault/{vault_id}")
