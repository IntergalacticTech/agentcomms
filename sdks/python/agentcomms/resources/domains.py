# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""Domains resource — org-scoped custom domain management."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from agentcomms.models import Domain

if TYPE_CHECKING:
    from agentcomms.client import Client


class DomainsResource:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def create(
        self,
        *,
        domain_name: str | None = None,
        domain: str | None = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Domain:
        body: dict[str, Any] = {"domain_name": domain_name or domain}
        if metadata:
            body["metadata"] = metadata
        data = self._client._request("POST", "/domains", json=body)
        return Domain.model_validate(data)

    def list(self) -> list[Domain]:
        data = self._client._request("GET", "/domains")
        return [Domain.model_validate(d) for d in data.get("domains", [])]

    def get(self, domain_id: str) -> Domain:
        data = self._client._request("GET", f"/domains/{domain_id}")
        return Domain.model_validate(data)

    def delete(self, domain_id: str) -> None:
        self._client._request("DELETE", f"/domains/{domain_id}")
