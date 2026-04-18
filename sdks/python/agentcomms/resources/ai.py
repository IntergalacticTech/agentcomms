# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""AI resource — Bedrock-backed operations on messages."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agentcomms.client import Client


class AiResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def _path(self, op: str) -> str:
        return f"/agents/{self._agent_id}/ai/{op}"

    def categorize(self, *, message_id: str, categories: Optional[list[str]] = None) -> dict[str, Any]:
        body: dict[str, Any] = {"message_id": message_id}
        if categories:
            body["categories"] = categories
        return self._client._request("POST", self._path("categorize"), json=body)

    def extract(self, *, message_id: str, fields: list[str]) -> dict[str, Any]:
        return self._client._request("POST", self._path("extract"), json={"message_id": message_id, "fields": fields})

    def summarize(self, *, message_id: str, max_length: Optional[int] = None) -> dict[str, Any]:
        body: dict[str, Any] = {"message_id": message_id}
        if max_length:
            body["max_length"] = max_length
        return self._client._request("POST", self._path("summarize"), json=body)

    def search(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        return self._client._request("POST", self._path("search"), json={"query": query, "limit": limit})
