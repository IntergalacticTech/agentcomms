# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""Channels resource — CRUD for per-agent channel configurations."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcomms.models import Channel

if TYPE_CHECKING:
    from agentcomms.client import Client


class ChannelsResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def _path(self, suffix: str = "") -> str:
        return f"/agents/{self._agent_id}/channels{suffix}"

    def list(self) -> list[Channel]:
        data = self._client._request("GET", self._path())
        return [Channel.model_validate(c) for c in data.get("channels", [])]

    def get(self, channel_id: str) -> Channel:
        data = self._client._request("GET", self._path(f"/{channel_id}"))
        return Channel.model_validate(data)

    def create(self, *, channel: str, mode: str = "provision", config: dict[str, Any] | None = None) -> Channel:
        body: dict[str, Any] = {"channel": channel, "mode": mode, "config": config or {}}
        data = self._client._request("POST", self._path(), json=body)
        return Channel.model_validate(data)

    def patch(self, channel_id: str, **kwargs: Any) -> Channel:
        data = self._client._request("PATCH", self._path(f"/{channel_id}"), json=kwargs)
        return Channel.model_validate(data)

    def delete(self, channel_id: str) -> None:
        self._client._request("DELETE", self._path(f"/{channel_id}"))
