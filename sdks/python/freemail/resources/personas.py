from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import httpx


class PersonaResource:
    """Persistent synthetic-identity profiles for agents."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> Any:
        from ..client import _handle_response
        resp = self._client.request(method, path, **kwargs)
        return _handle_response(resp)

    def list(self, limit: int = 25, page_token: Optional[str] = None) -> dict:
        params: dict = {"limit": limit}
        if page_token:
            params["page_token"] = page_token
        return self._request("GET", "/personas", params=params)

    def get(self, persona_id: str) -> dict:
        return self._request("GET", f"/personas/{persona_id}")

    def create(self, **fields) -> dict:
        """Create a persona. Pass explicit fields or ``generate=True`` with
        an optional ``hint`` string to have one produced via Bedrock."""
        return self._request("POST", "/personas", json=fields)

    def update(self, persona_id: str, **fields) -> dict:
        return self._request("PATCH", f"/personas/{persona_id}", json=fields)

    def delete(self, persona_id: str) -> None:
        self._request("DELETE", f"/personas/{persona_id}")
