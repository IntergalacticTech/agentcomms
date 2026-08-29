# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
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

    def categorize(
        self,
        *,
        message_id: str,
        labels: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"message_id": message_id}
        selected_labels = labels or categories
        if selected_labels:
            body["labels"] = selected_labels
        return self._client._request("POST", self._path("categorize"), json=body)

    def extract(
        self,
        *,
        message_id: str,
        schema: dict[str, Any] | None = None,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        if schema is None:
            if not fields:
                raise ValueError("schema is required")
            schema = {
                "type": "object",
                "properties": {field: {"type": "string"} for field in fields},
            }
        return self._client._request("POST", self._path("extract"), json={"message_id": message_id, "schema": schema})

    def summarize(
        self,
        *,
        text: str | None = None,
        message_id: str | None = None,
        thread_key: str | None = None,
        length: str | None = None,
        max_length: Optional[int] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if text:
            body["text"] = text
        if message_id:
            body["message_id"] = message_id
        if thread_key:
            body["thread_key"] = thread_key
        if length:
            body["length"] = length
        elif max_length:
            body["length"] = "long" if max_length > 500 else "short"
        return self._client._request("POST", self._path("summarize"), json=body)

    def search(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        return self._client._request("POST", self._path("search"), json={"query": query, "limit": limit})
