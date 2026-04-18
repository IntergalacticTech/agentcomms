# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
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
        name: str,
        value: str,
        type: str = "secret",
        metadata: Optional[dict[str, Any]] = None,
    ) -> VaultItem:
        body: dict[str, Any] = {"name": name, "value": value, "type": type}
        if metadata:
            body["metadata"] = metadata
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
        return self._client._request("POST", f"/vault/{vault_id}/totp")

    def delete(self, vault_id: str) -> None:
        self._client._request("DELETE", f"/vault/{vault_id}")
