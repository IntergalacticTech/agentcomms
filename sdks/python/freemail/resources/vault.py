from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import httpx


class VaultResource:
    """Encrypted secret storage with optional TOTP support."""

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
        return self._request("GET", "/vault", params=params)

    def get(self, secret_id: str, reveal: bool = False) -> dict:
        """Fetch secret metadata. Pass ``reveal=True`` to also decrypt and
        return the ``value`` field."""
        params = {"reveal": "true"} if reveal else None
        return self._request("GET", f"/vault/{secret_id}", params=params)

    def create(
        self,
        label: str,
        value: str,
        is_totp: bool = False,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        body: dict = {"label": label, "value": value}
        if is_totp:
            body["is_totp"] = True
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = metadata
        return self._request("POST", "/vault", json=body)

    def totp(self, secret_id: str) -> dict:
        """Return the current 6-digit TOTP code for a TOTP-flagged secret."""
        return self._request("GET", f"/vault/{secret_id}/totp")

    def delete(self, secret_id: str) -> None:
        self._request("DELETE", f"/vault/{secret_id}")
