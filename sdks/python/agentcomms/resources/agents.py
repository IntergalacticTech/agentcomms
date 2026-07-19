# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""Agents resource and per-agent context accessor."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcomms.models import Agent

if TYPE_CHECKING:
    from agentcomms.client import Client


class AgentContext:
    """Accessor returned by ``client.agents("agt_...")`` giving access to
    per-agent sub-resources: messages, channels, threads, etc."""

    def __init__(self, client: "Client", agent_id: str) -> None:
        self._client = client
        self.agent_id = agent_id
        # Lazy import to avoid circular dependencies
        from agentcomms.resources.messages import MessagesResource
        from agentcomms.resources.channels import ChannelsResource
        from agentcomms.resources.threads import ThreadsResource
        from agentcomms.resources.drafts import DraftsResource
        from agentcomms.resources.webhooks import WebhooksResource
        from agentcomms.resources.ai import AiResource
        from agentcomms.resources.slack import SlackResource
        from agentcomms.resources.telegram import TelegramResource
        from agentcomms.resources.push import PushResource

        self.messages = MessagesResource(client, agent_id)
        self.channels = ChannelsResource(client, agent_id)
        self.threads = ThreadsResource(client, agent_id)
        self.drafts = DraftsResource(client, agent_id)
        self.webhooks = WebhooksResource(client, agent_id)
        self.ai = AiResource(client, agent_id)
        self.slack = SlackResource(client, agent_id)
        self.telegram = TelegramResource(client, agent_id)
        self.push = PushResource(client, agent_id)


class AgentsResource:
    """Top-level agents resource. Call as a function to get a per-agent context.

    >>> agent = client.agents.create(name="InvoiceBot")
    >>> msgs = client.agents(agent["agent_id"]).messages.list()
    """

    def __init__(self, client: "Client") -> None:
        self._client = client

    def __call__(self, agent_id: str) -> AgentContext:
        """Return an :class:`AgentContext` for the given ``agent_id``."""
        return AgentContext(self._client, agent_id)

    def create(
        self,
        *,
        name: str,
        metadata: dict[str, Any] | None = None,
        provision: dict[str, Any] | None = None,
        bridge: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new agent (optionally provisioning channels in one call).

        Returns the raw dict (includes the agent-scoped API key on first creation).
        """
        body: dict[str, Any] = {
            "name": name,
            "metadata": metadata or {},
            "provision": provision or {},
            "bridge": bridge or {},
        }
        return self._client._request("POST", "/agents", json=body)

    def get(self, agent_id: str) -> Agent:
        """Fetch a single agent by ID."""
        data = self._client._request("GET", f"/agents/{agent_id}")
        return Agent.model_validate(data)

    def list(self) -> list[Agent]:
        """List all agents in the organisation."""
        data = self._client._request("GET", "/agents")
        return [Agent.model_validate(a) for a in data.get("agents", [])]

    def patch(self, agent_id: str, **kwargs: Any) -> Agent:
        """Update mutable fields on an agent.

        The API implements agent update as HTTP ``PUT /agents/{agent_id}``,
        so this issues a ``PUT`` even though the method is named ``patch``
        (kept stable for backwards compatibility).
        """
        data = self._client._request("PUT", f"/agents/{agent_id}", json=kwargs)
        return Agent.model_validate(data)

    # ``update`` is the natural name for a PUT-based update; kept as an alias.
    update = patch

    def delete(self, agent_id: str) -> None:
        """Delete an agent and all its channels."""
        self._client._request("DELETE", f"/agents/{agent_id}")

    def provision(self, agent_id: str, *, provision: dict[str, Any], bridge: dict[str, Any] | None = None) -> dict[str, Any]:
        """Add channels to an existing agent."""
        body: dict[str, Any] = {"provision": provision}
        if bridge:
            body["bridge"] = bridge
        return self._client._request("POST", f"/agents/{agent_id}/provision", json=body)
