from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import httpx


class ApiKeyResource:
    """Operations on API keys."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> dict:
        from ..client import _handle_response
        resp = self._client.request(method, path, **kwargs)
        return _handle_response(resp)

    def list(self) -> dict:
        return self._request("GET", "/api-keys")

    def create(
        self,
        name: str,
        scope: str = "org",
        scope_resource_id: Optional[str] = None,
    ) -> dict:
        body: dict = {"name": name, "scope": scope}
        if scope_resource_id is not None:
            body["scope_resource_id"] = scope_resource_id
        return self._request("POST", "/api-keys", json=body)

    def delete(self, key_id: str) -> None:
        self._request("DELETE", f"/api-keys/{key_id}")
