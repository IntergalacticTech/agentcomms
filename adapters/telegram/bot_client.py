# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# adapters/telegram/bot_client.py
"""
Thin HTTP client for the Telegram Bot API.

Uses only stdlib urllib.request so there is no extra dependency.
All requests are HTTPS POST/GET to https://api.telegram.org/bot{token}/{method}.

Raises TelegramAPIError on non-OK responses.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Any


class TelegramAPIError(Exception):
    """Raised when the Telegram API returns ok=false or an HTTP error."""
    def __init__(self, message: str, description: str | None = None, error_code: int | None = None):
        super().__init__(message)
        self.description = description
        self.error_code = error_code


class TelegramBotClient:
    """Minimal Telegram Bot API HTTP client."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict:
        """Perform a POST request to the Telegram Bot API."""
        url = f"{self.base}/{method}"
        body = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Try to parse the JSON error body from Telegram
            try:
                data = json.loads(e.read().decode("utf-8"))
            except Exception:
                raise TelegramAPIError(
                    f"HTTP {e.code} from Telegram API: {method}",
                    error_code=e.code,
                )

        if not data.get("ok"):
            raise TelegramAPIError(
                data.get("description", f"Telegram API error for {method}"),
                description=data.get("description"),
                error_code=data.get("error_code"),
            )
        return data.get("result", data)

    def get_me(self) -> dict:
        """GET /getMe — returns bot info: id, username, first_name."""
        return self._request("getMe")

    def set_webhook(
        self,
        url: str,
        secret_token: str | None = None,
    ) -> dict:
        """POST /setWebhook — register the webhook URL with Telegram."""
        params: dict[str, Any] = {"url": url}
        if secret_token is not None:
            params["secret_token"] = secret_token
        return self._request("setWebhook", params)

    def delete_webhook(self) -> dict:
        """POST /deleteWebhook — unregister the webhook."""
        return self._request("deleteWebhook", {"drop_pending_updates": False})

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        """POST /sendMessage — send a text message to a chat."""
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode is not None:
            params["parse_mode"] = parse_mode
        if reply_to_message_id is not None:
            params["reply_to_message_id"] = reply_to_message_id
        return self._request("sendMessage", params)

    def get_chat(self, chat_id: int | str) -> dict:
        """POST /getChat — get info about a chat/user."""
        return self._request("getChat", {"chat_id": chat_id})
