# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""Drafts resource."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from agentcomms.models import Draft

if TYPE_CHECKING:
    from agentcomms.client import Client


class DraftsResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def _path(self, suffix: str = "") -> str:
        return f"/agents/{self._agent_id}/drafts{suffix}"

    def list(self) -> list[Draft]:
        data = self._client._request("GET", self._path())
        return [Draft.model_validate(d) for d in data.get("drafts", [])]

    def get(self, draft_id: str) -> Draft:
        data = self._client._request("GET", self._path(f"/{draft_id}"))
        return Draft.model_validate(data)

    def create(
        self,
        *,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> Draft:
        body: dict[str, Any] = {}
        if to:
            body["to"] = to
        if subject:
            body["subject"] = subject
        if body_text:
            body["body_text"] = body_text
        if body_html:
            body["body_html"] = body_html
        if channel:
            body["channel"] = channel
        data = self._client._request("POST", self._path(), json=body)
        return Draft.model_validate(data)

    def patch(self, draft_id: str, **kwargs: Any) -> Draft:
        data = self._client._request("PATCH", self._path(f"/{draft_id}"), json=kwargs)
        return Draft.model_validate(data)

    def delete(self, draft_id: str) -> None:
        self._client._request("DELETE", self._path(f"/{draft_id}"))
