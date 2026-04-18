# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""AgentComms Python SDK — official client library for the AgentComms hub."""
from agentcomms.client import Client
from agentcomms.exceptions import (
    AgentCommsError,
    NotFoundError,
    AuthenticationError,
    RateLimitError,
    ServerError,
)
from agentcomms.models import (
    Agent,
    Channel,
    Message,
    Thread,
    Draft,
    Webhook,
    VaultItem,
    Persona,
    Domain,
)

__version__ = "1.0.0"

__all__ = [
    "Client",
    "AgentCommsError",
    "NotFoundError",
    "AuthenticationError",
    "RateLimitError",
    "ServerError",
    "Agent",
    "Channel",
    "Message",
    "Thread",
    "Draft",
    "Webhook",
    "VaultItem",
    "Persona",
    "Domain",
]
