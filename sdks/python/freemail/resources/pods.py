from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import httpx


class PodResource:
    """Operations on pods."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> dict:
        from ..client import _handle_response
        resp = self._client.request(method, path, **kwargs)
        return _handle_response(resp)

    def list(
        self,
        limit: int = 25,
        page_token: Optional[str] = None,
    ) -> dict:
        params: dict = {"limit": limit}
        if page_token:
            params["page_token"] = page_token
        return self._request("GET", "/pods", params=params)

    def get(self, pod_id: str) -> dict:
        return self._request("GET", f"/pods/{pod_id}")

    def create(
        self,
        name: str,
        description: Optional[str] = None,
    ) -> dict:
        body: dict = {"name": name}
        if description is not None:
            body["description"] = description
        return self._request("POST", "/pods", json=body)

    def delete(self, pod_id: str) -> None:
        self._request("DELETE", f"/pods/{pod_id}")
