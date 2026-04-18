# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
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
