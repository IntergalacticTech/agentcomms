# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""Personas resource — org-scoped identity personas."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from agentcomms.models import Persona

if TYPE_CHECKING:
    from agentcomms.client import Client


class PersonasResource:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def create(
        self,
        *,
        name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Persona:
        body: dict[str, Any] = {"name": name}
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if metadata:
            body["metadata"] = metadata
        data = self._client._request("POST", "/personas", json=body)
        return Persona.model_validate(data)

    def list(self) -> list[Persona]:
        data = self._client._request("GET", "/personas")
        return [Persona.model_validate(p) for p in data.get("personas", [])]

    def get(self, persona_id: str) -> Persona:
        data = self._client._request("GET", f"/personas/{persona_id}")
        return Persona.model_validate(data)

    def delete(self, persona_id: str) -> None:
        self._client._request("DELETE", f"/personas/{persona_id}")
