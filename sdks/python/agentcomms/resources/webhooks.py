# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""Webhooks resource."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from agentcomms.models import Webhook

if TYPE_CHECKING:
    from agentcomms.client import Client


class WebhooksResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def _path(self, suffix: str = "") -> str:
        return f"/agents/{self._agent_id}/webhooks{suffix}"

    def list(self) -> list[Webhook]:
        data = self._client._request("GET", self._path())
        return [Webhook.model_validate(w) for w in data.get("webhooks", [])]

    def get(self, webhook_id: str) -> Webhook:
        data = self._client._request("GET", self._path(f"/{webhook_id}"))
        return Webhook.model_validate(data)

    def create(
        self,
        *,
        url: str,
        events: list[str],
        channels: Optional[list[str]] = None,
        secret: Optional[str] = None,
    ) -> Webhook:
        body: dict[str, Any] = {"url": url, "events": events}
        if channels:
            body["channels"] = channels
        if secret:
            body["secret"] = secret
        data = self._client._request("POST", self._path(), json=body)
        return Webhook.model_validate(data)

    def patch(self, webhook_id: str, **kwargs: Any) -> Webhook:
        data = self._client._request("PATCH", self._path(f"/{webhook_id}"), json=kwargs)
        return Webhook.model_validate(data)

    def delete(self, webhook_id: str) -> None:
        self._client._request("DELETE", self._path(f"/{webhook_id}"))
