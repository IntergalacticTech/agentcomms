from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    import httpx


class MessageResource:
    """Operations on messages within an inbox."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> dict:
        from ..client import _handle_response
        resp = self._client.request(method, path, **kwargs)
        return _handle_response(resp)

    def list(
        self,
        inbox_id: str,
        limit: int = 25,
        page_token: Optional[str] = None,
    ) -> dict:
        params: dict = {"limit": limit}
        if page_token:
            params["page_token"] = page_token
        return self._request("GET", f"/inboxes/{inbox_id}/messages", params=params)

    def get(self, inbox_id: str, message_id: str) -> dict:
        return self._request("GET", f"/inboxes/{inbox_id}/messages/{message_id}")

    def send(
        self,
        inbox_id: str,
        to: List[dict],
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        **kwargs,
    ) -> dict:
        body: dict = {"to": to, "subject": subject, **kwargs}
        if body_text is not None:
            body["body_text"] = body_text
        if body_html is not None:
            body["body_html"] = body_html
        return self._request("POST", f"/inboxes/{inbox_id}/messages", json=body)

    def reply(
        self,
        inbox_id: str,
        message_id: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
    ) -> dict:
        body: dict = {}
        if body_text is not None:
            body["body_text"] = body_text
        if body_html is not None:
            body["body_html"] = body_html
        return self._request(
            "POST", f"/inboxes/{inbox_id}/messages/{message_id}/reply", json=body
        )

    def forward(
        self,
        inbox_id: str,
        message_id: str,
        to: List[dict],
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
    ) -> dict:
        body: dict = {"to": to}
        if body_text is not None:
            body["body_text"] = body_text
        if body_html is not None:
            body["body_html"] = body_html
        return self._request(
            "POST", f"/inboxes/{inbox_id}/messages/{message_id}/forward", json=body
        )

    def update(self, inbox_id: str, message_id: str, **kwargs) -> dict:
        return self._request(
            "PATCH", f"/inboxes/{inbox_id}/messages/{message_id}", json=kwargs
        )
