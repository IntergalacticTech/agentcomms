# core/api/push_native_handler.py
"""
Push-channel native API routes.

These routes provide device management for push-enabled agents. Push is
asymmetric — the agent sends notifications to registered device endpoints.
There is no inbound message from users; delivery receipts arrive via SNS
and are handled by adapters/push/ingest.py.

Routes:
  POST   /v1/agents/{agent_id}/push/devices
      Body: { platform: "apns"|"fcm", token: "..." }
      → register_device → 201 { device_id, endpoint_arn, platform, created_at }

  GET    /v1/agents/{agent_id}/push/devices
      → list_devices → 200 { devices: [...] }

  DELETE /v1/agents/{agent_id}/push/devices/{device_id}
      → delete_device → 204

  POST   /v1/agents/{agent_id}/push/send
      Body: { device_id: "...", body_text: "...", title?: "...", badge?: N }
      → resolves the device, constructs target ARN, calls PushAdapter.send
      → 200 { channel_native_id, status }
"""
from __future__ import annotations

import json
import logging

from core.api._common import Caller, err, get_repo, no_content, ok, parse_body
from core.adapters.base import OutboundMessage
from core.data.models import ChannelType

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_push_channel(repo, agent_id: str, org_id: str):
    """Return the first active push Channel for this agent, or None."""
    channels = repo.list_channels(agent_id=agent_id)
    for ch in channels:
        if ch.channel == ChannelType.PUSH:
            return ch
    return None


def handler(event: dict, context) -> dict:
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}

    agent_id = path_params.get("agent_id", "")
    device_id = path_params.get("device_id", "")

    caller = Caller.from_event(event)
    repo = get_repo()

    # Verify agent exists and belongs to the caller's org
    agent = repo.get_agent(org_id=caller.org_id, agent_id=agent_id)
    if agent is None:
        return err("Agent not found", status=404)

    # ── POST /push/devices ──
    if method == "POST" and path.endswith("/devices"):
        body = parse_body(event)
        platform = (body.get("platform") or "").lower()
        token = body.get("token", "").strip()

        if platform not in ("apns", "fcm"):
            return err("platform must be 'apns' or 'fcm'")
        if not token:
            return err("token is required")

        channel = _get_push_channel(repo, agent_id, caller.org_id)
        if channel is None:
            return err(
                "No push channel provisioned for this agent. "
                "Create one via POST /v1/agents/{id}/channels with channel='push'.",
                status=422,
            )

        from adapters.push.devices import register_device
        try:
            device = register_device(repo, channel, platform, token)
        except RuntimeError as e:
            return err(str(e), status=503)

        return ok(
            {
                "device_id": device.device_id,
                "endpoint_arn": device.endpoint_arn,
                "platform": device.platform,
                "created_at": device.created_at,
            },
            status=201,
        )

    # ── GET /push/devices ──
    if method == "GET" and path.endswith("/devices"):
        channel = _get_push_channel(repo, agent_id, caller.org_id)
        if channel is None:
            return ok({"devices": []})

        from adapters.push.devices import list_devices
        devices = list_devices(repo, channel)
        return ok({
            "devices": [
                {
                    "device_id": d.device_id,
                    "platform": d.platform,
                    "endpoint_arn": d.endpoint_arn,
                    "created_at": d.created_at,
                }
                for d in devices
            ]
        })

    # ── DELETE /push/devices/{device_id} ──
    if method == "DELETE" and device_id:
        channel = _get_push_channel(repo, agent_id, caller.org_id)
        if channel is None:
            return err("No push channel provisioned for this agent.", status=404)

        from adapters.push.devices import delete_device
        try:
            delete_device(repo, channel, device_id)
        except KeyError:
            return err("Device not found", status=404)

        return no_content()

    # ── POST /push/send ──
    if method == "POST" and path.endswith("/send"):
        body = parse_body(event)
        dev_id = body.get("device_id", "").strip()
        body_text = body.get("body_text", "").strip()
        title = body.get("title", "").strip()
        badge = body.get("badge")

        if not dev_id:
            return err("device_id is required")
        if not body_text:
            return err("body_text is required")

        channel = _get_push_channel(repo, agent_id, caller.org_id)
        if channel is None:
            return err("No push channel provisioned for this agent.", status=422)

        from adapters.push.devices import list_devices
        devices = list_devices(repo, channel)
        device = next((d for d in devices if d.device_id == dev_id), None)
        if device is None:
            return err("Device not found", status=404)

        # Build prefixed target ARN for PushAdapter.send
        to_address = f"push:{device.platform}:{device.endpoint_arn}"

        native_overrides = {}
        if title:
            native_overrides["title"] = title
        if badge is not None:
            native_overrides["badge"] = badge

        message = OutboundMessage(
            to=to_address,
            body_text=body_text,
            subject=title or None,
            channel_native_overrides=native_overrides,
        )

        from adapters.push.adapter import PushAdapter
        adapter = PushAdapter()
        result = adapter.send(channel=channel, message=message)

        if result.status == "failed":
            return err(result.error or "send failed", status=502)

        return ok({
            "channel_native_id": result.channel_native_id,
            "status": result.status,
        })

    return err("Not found", status=404)
