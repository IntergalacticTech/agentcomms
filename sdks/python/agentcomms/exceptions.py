# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""AgentComms SDK exceptions."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests


class AgentCommsError(Exception):
    """Base exception for all AgentComms SDK errors."""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self.code = body.get("error", {}).get("code", "UNKNOWN")
        self.message = body.get("error", {}).get("message", str(body))
        super().__init__(f"[{status_code}] {self.code}: {self.message}")

    @classmethod
    def from_response(cls, resp: "requests.Response") -> "AgentCommsError":
        try:
            body = resp.json()
        except Exception:
            body = {"error": {"code": "UNKNOWN", "message": resp.text}}

        if resp.status_code == 404:
            return NotFoundError(resp.status_code, body)
        if resp.status_code in (401, 403):
            return AuthenticationError(resp.status_code, body)
        if resp.status_code == 429:
            return RateLimitError(resp.status_code, body)
        if resp.status_code >= 500:
            return ServerError(resp.status_code, body)
        return cls(resp.status_code, body)


class NotFoundError(AgentCommsError):
    """Raised when the API returns 404."""


class AuthenticationError(AgentCommsError):
    """Raised when authentication fails (401/403)."""


class RateLimitError(AgentCommsError):
    """Raised when the API rate limit is exceeded (429)."""


class ServerError(AgentCommsError):
    """Raised when the API returns a 5xx error."""
