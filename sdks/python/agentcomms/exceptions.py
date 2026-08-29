# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""AgentComms SDK exceptions."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests


class AgentCommsError(Exception):
    """Base exception for all AgentComms SDK errors."""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self.code, self.message = self._parse_error(body)
        super().__init__(f"[{status_code}] {self.code}: {self.message}")

    @staticmethod
    def _parse_error(body: object) -> tuple[str, str]:
        """Extract ``(code, message)`` from a response body.

        The API returns errors either as a bare string
        (``{"error": "<string>"}``) or as an object
        (``{"error": {"code": ..., "message": ...}}``). Both shapes are
        supported here so any error body maps to a real ``AgentCommsError``.
        """
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            return error.get("code", "UNKNOWN"), error.get("message", str(body))
        if isinstance(error, str):
            return "ERROR", error
        return "UNKNOWN", str(body)

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
