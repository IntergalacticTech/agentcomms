# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""Domains resource — org-scoped custom domain management."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from agentcomms.models import Domain

if TYPE_CHECKING:
    from agentcomms.client import Client


class DomainsResource:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def create(self, *, domain: str, metadata: Optional[dict[str, Any]] = None) -> Domain:
        body: dict[str, Any] = {"domain": domain}
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
