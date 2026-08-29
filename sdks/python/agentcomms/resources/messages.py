# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""Messages resource — unified inbox and send operations."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from agentcomms.models import Message

if TYPE_CHECKING:
    from agentcomms.client import Client


class MessagesResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def _path(self, suffix: str = "") -> str:
        return f"/agents/{self._agent_id}/messages{suffix}"

    def list(
        self,
        *,
        since: Optional[str] = None,
        channels: Optional[list[str]] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> list[Message]:
        """List messages from the unified inbox (DMs and @mentions only)."""
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since
        if channels:
            params["channels"] = ",".join(channels)
        if cursor:
            params["cursor"] = cursor
        data = self._client._request("GET", self._path(), params=params)
        return [Message.model_validate(m) for m in data.get("messages", [])]

    def list_page(
        self,
        *,
        since: Optional[str] = None,
        channels: Optional[list[str]] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """List one page and keep the API's opaque ``next_cursor``."""
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since
        if channels:
            params["channels"] = ",".join(channels)
        if cursor:
            params["cursor"] = cursor
        data = self._client._request("GET", self._path(), params=params)
        return {
            "messages": [Message.model_validate(m) for m in data.get("messages", [])],
            "next_cursor": data.get("next_cursor"),
        }

    def get(self, message_id: str) -> Message:
        data = self._client._request("GET", self._path(f"/{message_id}"))
        return Message.model_validate(data)

    def send(
        self,
        *,
        to: str | dict[str, Any],
        body: Optional[str] = None,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        subject: Optional[str] = None,
        channel: Optional[str] = None,
        thread_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send a message. Channel is inferred from the ``to`` format unless overridden."""
        payload: dict[str, Any] = {"to": to}
        if body is not None:
            payload["body"] = body
        if body_text is not None:
            payload["body_text"] = body_text
        if body_html is not None:
            payload["body_html"] = body_html
        if subject is not None:
            payload["subject"] = subject
        if channel is not None:
            payload["channel"] = channel
        if thread_key is not None:
            payload["thread_key"] = thread_key
        return self._client._request("POST", self._path(), json=payload)

    def reply(self, message_id: str, *, body: str, body_html: Optional[str] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"body": body}
        if body_html:
            payload["body_html"] = body_html
        return self._client._request("POST", self._path(f"/{message_id}/reply"), json=payload)

    def mark_read(self, message_id: str) -> None:
        self._client._request("POST", self._path(f"/{message_id}/read"))

    def wait(
        self,
        *,
        timeout: int = 25,
        sender: Optional[str] = None,
        subject_contains: Optional[str] = None,
        channels: Optional[list[str]] = None,
    ) -> Message:
        """Long-poll for the next incoming message matching the given filters."""
        payload: dict[str, Any] = {"timeout_sec": timeout}
        if sender:
            payload["from"] = sender
        if subject_contains:
            payload["subject_contains"] = subject_contains
        if channels:
            if len(channels) == 1:
                payload["channel"] = channels[0]
            else:
                payload["channels"] = channels
        data = self._client._request("POST", f"/agents/{self._agent_id}/wait", json=payload)
        return Message.model_validate(data)

    def extract_otp(
        self,
        *,
        timeout: int = 25,
        sender: Optional[str] = None,
    ) -> dict[str, Any]:
        """Wait for a message containing a numeric OTP code and extract it."""
        payload: dict[str, Any] = {"max_age_sec": timeout}
        if sender:
            payload["from"] = sender
        return self._client._request("POST", f"/agents/{self._agent_id}/extract-otp", json=payload)
