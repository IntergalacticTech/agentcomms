from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


class DomainResource:
    """Operations on domains."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> dict:
        from ..client import _handle_response
        resp = self._client.request(method, path, **kwargs)
        return _handle_response(resp)

    def list(self) -> dict:
        return self._request("GET", "/domains")

    def get(self, domain_id: str) -> dict:
        return self._request("GET", f"/domains/{domain_id}")

    def create(self, domain: str) -> dict:
        return self._request("POST", "/domains", json={"domain": domain})

    def verify(self, domain_id: str) -> dict:
        return self._request("POST", f"/domains/{domain_id}/verify")

    def delete(self, domain_id: str) -> None:
        self._request("DELETE", f"/domains/{domain_id}")
