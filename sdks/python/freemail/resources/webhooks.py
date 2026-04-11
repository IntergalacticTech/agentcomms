from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    import httpx


class WebhookResource:
    """Operations on webhooks."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> dict:
        from ..client import _handle_response
        resp = self._client.request(method, path, **kwargs)
        return _handle_response(resp)

    def list(self) -> dict:
        return self._request("GET", "/webhooks")

    def create(
        self,
        url: str,
        events: List[str],
        filter: Optional[dict] = None,
    ) -> dict:
        body: dict = {"url": url, "events": events}
        if filter is not None:
            body["filter"] = filter
        return self._request("POST", "/webhooks", json=body)

    def update(self, webhook_id: str, **kwargs) -> dict:
        return self._request("PATCH", f"/webhooks/{webhook_id}", json=kwargs)

    def delete(self, webhook_id: str) -> None:
        self._request("DELETE", f"/webhooks/{webhook_id}")
