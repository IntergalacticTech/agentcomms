from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import httpx


class InboxResource:
    """Operations on inboxes."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> dict:
        from ..client import _handle_response
        resp = self._client.request(method, path, **kwargs)
        return _handle_response(resp)

    def list(
        self,
        pod_id: Optional[str] = None,
        limit: int = 25,
        page_token: Optional[str] = None,
    ) -> dict:
        params: dict = {"limit": limit}
        if pod_id:
            params["pod_id"] = pod_id
        if page_token:
            params["page_token"] = page_token
        return self._request("GET", "/inboxes", params=params)

    def get(self, inbox_id: str) -> dict:
        return self._request("GET", f"/inboxes/{inbox_id}")

    def create(
        self,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        pod_id: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> dict:
        """Create a new inbox.

        Pass ``domain`` to pick which platform domain the random inbox
        address is generated on (e.g. ``"karmascale.net"``). Defaults to
        ``"victorymail.dev"``. Pass ``email`` to choose an exact address;
        the domain must still be one of the platform domains.
        """
        body: dict = {}
        if display_name is not None:
            body["display_name"] = display_name
        if email is not None:
            body["email"] = email
        if pod_id is not None:
            body["pod_id"] = pod_id
        if domain is not None:
            body["domain"] = domain
        return self._request("POST", "/inboxes", json=body)

    def update(self, inbox_id: str, **kwargs) -> dict:
        return self._request("PATCH", f"/inboxes/{inbox_id}", json=kwargs)

    def delete(self, inbox_id: str) -> None:
        self._request("DELETE", f"/inboxes/{inbox_id}")

    def wait_for_message(
        self,
        inbox_id: str,
        timeout: int = 25,
        sender: Optional[str] = None,
        subject_contains: Optional[str] = None,
    ) -> dict:
        params: dict = {"timeout": timeout}
        if sender:
            params["sender"] = sender
        if subject_contains:
            params["subject_contains"] = subject_contains
        return self._request("GET", f"/inboxes/{inbox_id}/wait", params=params)

    def extract_otp(
        self,
        inbox_id: str,
        timeout: int = 25,
        sender: Optional[str] = None,
        subject_contains: Optional[str] = None,
    ) -> dict:
        params: dict = {"timeout": timeout}
        if sender:
            params["sender"] = sender
        if subject_contains:
            params["subject_contains"] = subject_contains
        return self._request("GET", f"/inboxes/{inbox_id}/otp", params=params)
