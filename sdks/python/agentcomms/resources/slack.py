# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""Slack channel-native sub-surface resource."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentcomms.client import Client


class SlackWorkspaceChannels:
    def __init__(self, client: "Client", agent_id: str, team_id: str) -> None:
        self._client = client
        self._agent_id = agent_id
        self._team_id = team_id

    def _base(self) -> str:
        return f"/agents/{self._agent_id}/slack/workspaces/{self._team_id}/channels"

    def list(self) -> list[dict[str, Any]]:
        data = self._client._request("GET", self._base())
        return data.get("channels", [])

    def messages(self, channel_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        data = self._client._request("GET", f"{self._base()}/{channel_id}/messages", params={"limit": limit})
        return data.get("messages", [])

    def post(self, channel_id: str, *, body: str, blocks: Any = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"body": body}
        if blocks:
            payload["blocks"] = blocks
        return self._client._request("POST", f"{self._base()}/{channel_id}/messages", json=payload)


class SlackWorkspace:
    def __init__(self, client: "Client", agent_id: str, team_id: str) -> None:
        self._client = client
        self._agent_id = agent_id
        self._team_id = team_id
        self.channels = SlackWorkspaceChannels(client, agent_id, team_id)

    def dm(self, user_id: str, *, body: str) -> dict[str, Any]:
        return self._client._request(
            "POST",
            f"/agents/{self._agent_id}/slack/workspaces/{self._team_id}/users/{user_id}/messages",
            json={"body": body},
        )


class SlackResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def workspaces(self) -> list[dict[str, Any]]:
        data = self._client._request("GET", f"/agents/{self._agent_id}/slack/workspaces")
        return data.get("workspaces", [])

    def workspace(self, team_id: str) -> SlackWorkspace:
        return SlackWorkspace(self._client, self._agent_id, team_id)
