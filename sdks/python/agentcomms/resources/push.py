# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""Push notifications resource."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agentcomms.client import Client


class PushResource:
    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self._agent_id = agent_id

    def register_device(
        self,
        *,
        platform: str,
        token: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Register a device push token (APNs or FCM)."""
        body: dict[str, Any] = {"platform": platform, "token": token}
        if metadata:
            body["metadata"] = metadata
        return self._client._request("POST", f"/agents/{self._agent_id}/push/devices", json=body)

    def send(
        self,
        *,
        title: str,
        body: str,
        device_ids: Optional[list[str]] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Send a push notification to registered devices."""
        payload: dict[str, Any] = {"title": title, "body": body}
        if device_ids:
            payload["device_ids"] = device_ids
        if data:
            payload["data"] = data
        return self._client._request("POST", f"/agents/{self._agent_id}/push/send", json=payload)
