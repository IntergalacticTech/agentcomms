# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
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
        device_id: str | None = None,
        body_text: str | None = None,
        title: Optional[str] = None,
        body: str | None = None,
        device_ids: Optional[list[str]] = None,
        badge: int | None = None,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Send a push notification to registered devices."""
        selected_device_id = device_id or (device_ids[0] if device_ids else None)
        if not selected_device_id:
            raise ValueError("device_id is required")
        payload: dict[str, Any] = {
            "device_id": selected_device_id,
            "body_text": body_text if body_text is not None else body,
        }
        if title:
            payload["title"] = title
        if badge is not None:
            payload["badge"] = badge
        if data:
            payload["data"] = data
        return self._client._request("POST", f"/agents/{self._agent_id}/push/send", json=payload)
