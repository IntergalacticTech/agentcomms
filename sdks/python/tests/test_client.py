"""Unit tests for the FreeMail Python SDK."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from freemail import FreeMail, FreemailAPIError


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "https://test"),
    )
    return resp


class TestCreateInbox:
    def test_create_inbox(self):
        expected = {"id": "inbox_123", "email": "agent@mail.freemail.dev", "display_name": "My Agent"}

        with patch.object(httpx.Client, "request", return_value=_mock_response(200, expected)) as mock_req:
            client = FreeMail("am_live_test_key")
            result = client.inboxes.create(display_name="My Agent")

            assert result == expected
            mock_req.assert_called_once_with(
                "POST", "/inboxes", json={"display_name": "My Agent"}
            )
            client.close()


class TestSendMessage:
    def test_send_message(self):
        expected = {"id": "msg_456", "subject": "Hello!", "status": "sent"}

        with patch.object(httpx.Client, "request", return_value=_mock_response(200, expected)) as mock_req:
            client = FreeMail("am_live_test_key")
            result = client.messages.send(
                "inbox_123",
                to=[{"address": "user@example.com"}],
                subject="Hello!",
                body_text="Sent from FreeMail",
            )

            assert result == expected
            mock_req.assert_called_once_with(
                "POST",
                "/inboxes/inbox_123/messages",
                json={
                    "to": [{"address": "user@example.com"}],
                    "subject": "Hello!",
                    "body_text": "Sent from FreeMail",
                },
            )
            client.close()


class TestListInboxes:
    def test_list_inboxes(self):
        expected = {
            "data": [
                {"id": "inbox_1", "email": "a@mail.freemail.dev"},
                {"id": "inbox_2", "email": "b@mail.freemail.dev"},
            ],
            "has_more": False,
        }

        with patch.object(httpx.Client, "request", return_value=_mock_response(200, expected)) as mock_req:
            client = FreeMail("am_live_test_key")
            result = client.inboxes.list()

            assert result == expected
            mock_req.assert_called_once_with(
                "GET", "/inboxes", params={"limit": 25}
            )
            client.close()


class TestErrorHandling:
    def test_api_error_raised(self):
        error_body = {"error": {"code": "NOT_FOUND", "message": "Inbox not found"}}

        with patch.object(httpx.Client, "request", return_value=_mock_response(404, error_body)):
            client = FreeMail("am_live_test_key")

            with pytest.raises(FreemailAPIError) as exc_info:
                client.inboxes.get("inbox_nonexistent")

            assert exc_info.value.status_code == 404
            assert exc_info.value.code == "NOT_FOUND"
            client.close()

    def test_auth_error(self):
        error_body = {"error": {"code": "UNAUTHORIZED", "message": "Invalid API key"}}

        with patch.object(httpx.Client, "request", return_value=_mock_response(401, error_body)):
            client = FreeMail("am_live_bad_key")

            from freemail.exceptions import AuthenticationError
            with pytest.raises(AuthenticationError):
                client.get_organization()

            client.close()

    def test_context_manager(self):
        with patch.object(httpx.Client, "request", return_value=_mock_response(200, {"ok": True})):
            with FreeMail("am_live_test_key") as client:
                result = client.get_organization()
                assert result == {"ok": True}
