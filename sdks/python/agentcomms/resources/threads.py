# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""Threads resource."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from agentcomms.models import Thread

if TYPE_CHECKING:
    from agentcomms.client import Client


class ThreadsResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def _path(self, suffix: str = "") -> str:
        return f"/agents/{self._agent_id}/threads{suffix}"

    def list(self, *, channel: Optional[str] = None, limit: int = 50) -> list[Thread]:
        params = {"limit": limit}
        if channel:
            params["channel"] = channel  # type: ignore[assignment]
        data = self._client._request("GET", self._path(), params=params)
        return [Thread.model_validate(t) for t in data.get("threads", [])]

    def get(self, thread_id: str) -> Thread:
        data = self._client._request("GET", self._path(f"/{thread_id}"))
        return Thread.model_validate(data)
