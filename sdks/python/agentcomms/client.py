# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""AgentComms Python SDK — main Client class."""
from __future__ import annotations

import os
from typing import Any

import requests

from agentcomms.exceptions import AgentCommsError
from agentcomms.resources.agents import AgentsResource
from agentcomms.resources.vault import VaultResource
from agentcomms.resources.personas import PersonasResource
from agentcomms.resources.domains import DomainsResource


class Client:
    """AgentComms Python SDK client.

    Usage::

        from agentcomms import Client

        client = Client(api_key="ak_live_...")
        agent = client.agents.create(name="InvoiceBot")
        for msg in client.agents(agent["agent_id"]).messages.list():
            print(msg.body_text)

    The ``api_key`` argument falls back to the ``AGENTCOMMS_API_KEY`` environment
    variable when not provided.  ``base_url`` falls back to
    ``AGENTCOMMS_BASE_URL`` or the hosted service ``https://api.agentcomms.dev/v1``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ["AGENTCOMMS_API_KEY"]
        self.base_url = (
            base_url
            or os.environ.get("AGENTCOMMS_BASE_URL", "https://api.agentcomms.dev/v1")
        ).rstrip("/")
        self.timeout = timeout

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "agentcomms-python/1.0.0",
            }
        )

        # Top-level resources
        self.agents = AgentsResource(self)
        self.vault = VaultResource(self)
        self.personas = PersonasResource(self)
        self.domains = DomainsResource(self)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Perform an HTTP request and return the parsed JSON body.

        Raises :class:`~agentcomms.exceptions.AgentCommsError` (or a subclass)
        for any 4xx / 5xx response.
        """
        url = f"{self.base_url}{path}"
        resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
        if resp.status_code >= 400:
            raise AgentCommsError.from_response(resp)
        if resp.status_code == 204:
            return {}
        return resp.json()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
