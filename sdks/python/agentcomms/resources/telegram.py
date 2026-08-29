# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""Telegram channel-native sub-surface resource."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentcomms.client import Client


class TelegramResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def chats(self) -> list[dict[str, Any]]:
        data = self._client._request("GET", f"/agents/{self._agent_id}/telegram/chats")
        return data.get("chats", [])

    def chat_messages(self, chat_id: str | int, *, limit: int = 50) -> list[dict[str, Any]]:
        data = self._client._request(
            "GET",
            f"/agents/{self._agent_id}/telegram/chats/{chat_id}/messages",
            params={"limit": limit},
        )
        return data.get("messages", [])

    def send(self, chat_id: str | int, *, body: str) -> dict[str, Any]:
        return self._client._request(
            "POST",
            f"/agents/{self._agent_id}/telegram/chats/{chat_id}/messages",
            json={"text": body},
        )
