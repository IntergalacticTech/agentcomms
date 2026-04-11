from __future__ import annotations

import httpx

from .exceptions import (
    AuthenticationError,
    FreemailAPIError,
    NotFoundError,
    RateLimitError,
)
from .resources import (
    ApiKeyResource,
    DomainResource,
    InboxResource,
    MessageResource,
    PodResource,
    WebhookResource,
)


def _handle_response(resp: httpx.Response) -> dict:
    """Shared response handler used by the client and all resource classes."""
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {"error": {"code": "UNKNOWN", "message": resp.text}}

        if resp.status_code == 404:
            raise NotFoundError(resp.status_code, body)
        if resp.status_code in (401, 403):
            raise AuthenticationError(resp.status_code, body)
        if resp.status_code == 429:
            raise RateLimitError(resp.status_code, body)
        raise FreemailAPIError(resp.status_code, body)

    if resp.status_code == 204:
        return {}
    return resp.json()


class FreeMail:
    """FreeMail API client.

    Usage::

        client = FreeMail("am_live_...")
        inbox = client.inboxes.create(display_name="My Agent")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.victorymail.dev/v1",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        # Resource accessors
        self.inboxes = InboxResource(self._client)
        self.messages = MessageResource(self._client)
        self.pods = PodResource(self._client)
        self.domains = DomainResource(self._client)
        self.webhooks = WebhookResource(self._client)
        self.api_keys = ApiKeyResource(self._client)

    def get_organization(self) -> dict:
        """Get the current organization."""
        resp = self._client.request("GET", "/organizations/me")
        return _handle_response(resp)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> FreeMail:
        return self

    def __exit__(self, *args) -> None:
        self.close()
