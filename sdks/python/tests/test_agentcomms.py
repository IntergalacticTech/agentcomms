# SPDX-License-Identifier: FSL-1.1-Apache-2.0
"""Unit tests for the agentcomms Python SDK."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agentcomms import Client
from agentcomms.exceptions import (
    AgentCommsError,
    NotFoundError,
    AuthenticationError,
    RateLimitError,
    ServerError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int, body: dict, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = body
    resp.text = json.dumps(body)
    resp.headers = headers or {}
    return resp


def _mock_session_request(response: MagicMock):
    """Return a context manager patch that makes Session.request return *response*."""
    return patch("requests.Session.request", return_value=response)


@pytest.fixture(autouse=True)
def _no_sleep():
    """Make retry backoff instant so tests don't actually sleep."""
    with patch("agentcomms.client.time.sleep"):
        yield


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------

class TestClientInit:
    def test_api_key_stored(self):
        client = Client(api_key="ak_live_test")
        assert client.api_key == "ak_live_test"

    def test_base_url_default(self):
        client = Client(api_key="k")
        assert client.base_url == "https://api.agentcomms.dev/v1"

    def test_base_url_custom(self):
        client = Client(api_key="k", base_url="http://localhost:8000/v1/")
        assert client.base_url == "http://localhost:8000/v1"  # trailing slash stripped

    def test_auth_header_set(self):
        client = Client(api_key="ak_live_test")
        assert client._session.headers["Authorization"] == "Bearer ak_live_test"

    def test_user_agent(self):
        client = Client(api_key="k")
        assert "agentcomms-python" in client._session.headers["User-Agent"]


# ---------------------------------------------------------------------------
# Agents resource
# ---------------------------------------------------------------------------

class TestAgentsResource:
    def test_list_issues_get_agents(self):
        resp = _make_response(200, {"agents": [
            {"agent_id": "agt_1", "name": "Bot", "org_id": "org_1"},
        ]})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            agents = client.agents.list()
        mock_req.assert_called_once()
        call_args = mock_req.call_args
        assert call_args[0][0] == "GET"
        assert "/agents" in call_args[0][1]
        assert len(agents) == 1
        assert agents[0].agent_id == "agt_1"

    def test_create_issues_post(self):
        resp = _make_response(201, {"agent_id": "agt_2", "name": "x", "org_id": "org_1"})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            result = client.agents.create(name="x")
        mock_req.assert_called_once()
        assert mock_req.call_args[0][0] == "POST"
        assert result["agent_id"] == "agt_2"

    def test_get_returns_agent_model(self):
        resp = _make_response(200, {"agent_id": "agt_1", "name": "Bot", "org_id": "org_1"})
        with _mock_session_request(resp):
            client = Client(api_key="k")
            agent = client.agents.get("agt_1")
        assert agent.agent_id == "agt_1"

    def test_delete_issues_delete(self):
        resp = _make_response(204, {})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            client.agents.delete("agt_1")
        assert mock_req.call_args[0][0] == "DELETE"

    def test_patch_issues_put(self):
        # The API implements agent update as HTTP PUT, not PATCH.
        resp = _make_response(200, {"agent_id": "agt_1", "name": "Renamed", "org_id": "org_1"})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            agent = client.agents.patch("agt_1", name="Renamed")
        assert mock_req.call_args[0][0] == "PUT"
        assert "/agents/agt_1" in mock_req.call_args[0][1]
        assert agent.name == "Renamed"

    def test_update_alias_issues_put(self):
        resp = _make_response(200, {"agent_id": "agt_1", "name": "Renamed", "org_id": "org_1"})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            client.agents.update("agt_1", name="Renamed")
        assert mock_req.call_args[0][0] == "PUT"

    def test_agent_context_via_call(self):
        client = Client(api_key="k")
        ctx = client.agents("agt_1")
        assert ctx.agent_id == "agt_1"
        # Sub-resources should be present
        assert hasattr(ctx, "messages")
        assert hasattr(ctx, "channels")
        assert hasattr(ctx, "webhooks")


# ---------------------------------------------------------------------------
# Messages resource
# ---------------------------------------------------------------------------

class TestMessagesResource:
    def test_list_messages_issues_get(self):
        resp = _make_response(200, {"messages": [
            {"message_id": "msg_1", "agent_id": "agt_1", "channel": "email"},
        ]})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            msgs = client.agents("agt_1").messages.list()
        assert mock_req.call_args[0][0] == "GET"
        assert "/agents/agt_1/messages" in mock_req.call_args[0][1]
        assert len(msgs) == 1
        assert msgs[0].message_id == "msg_1"

    def test_send_issues_post(self):
        resp = _make_response(202, {"message_id": "msg_2"})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            result = client.agents("agt_1").messages.send(to="alice@example.com", body="hi")
        assert mock_req.call_args[0][0] == "POST"
        assert result["message_id"] == "msg_2"

    def test_reply_issues_post_to_reply_endpoint(self):
        resp = _make_response(202, {"message_id": "msg_3"})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            client.agents("agt_1").messages.reply("msg_2", body="thanks")
        assert "/msg_2/reply" in mock_req.call_args[0][1]


# ---------------------------------------------------------------------------
# Vault resource
# ---------------------------------------------------------------------------

class TestVaultResource:
    def test_create_vault_item(self):
        resp = _make_response(201, {"vault_id": "v_1", "name": "MY_SECRET", "type": "secret", "org_id": "org_1"})
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            item = client.vault.create(name="MY_SECRET", value="s3cr3t")
        assert mock_req.call_args[0][0] == "POST"
        assert "/vault" in mock_req.call_args[0][1]
        assert item.vault_id == "v_1"

    def test_list_vault_items(self):
        resp = _make_response(200, {"items": [{"vault_id": "v_1", "name": "x", "type": "secret", "org_id": "org_1"}]})
        with _mock_session_request(resp):
            client = Client(api_key="k")
            items = client.vault.list()
        assert len(items) == 1


# ---------------------------------------------------------------------------
# Webhooks resource
# ---------------------------------------------------------------------------

class TestWebhooksResource:
    def test_create_webhook(self):
        resp = _make_response(201, {
            "webhook_id": "wh_1",
            "agent_id": "agt_1",
            "url": "https://example.com/hook",
            "events": ["message.received"],
        })
        with _mock_session_request(resp) as mock_req:
            client = Client(api_key="k")
            wh = client.agents("agt_1").webhooks.create(url="https://example.com/hook", events=["message.received"])
        assert mock_req.call_args[0][0] == "POST"
        assert wh.webhook_id == "wh_1"


# ---------------------------------------------------------------------------
# Domains resource
# ---------------------------------------------------------------------------

class TestDomainsResource:
    def test_list_domains(self):
        resp = _make_response(200, {"domains": [
            {"domain_id": "dom_1", "domain": "example.com", "org_id": "org_1"},
        ]})
        with _mock_session_request(resp):
            client = Client(api_key="k")
            domains = client.domains.list()
        assert len(domains) == 1
        assert domains[0].domain == "example.com"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_404_raises_not_found_error(self):
        resp = _make_response(404, {"error": {"code": "NOT_FOUND", "message": "Agent not found"}})
        with _mock_session_request(resp):
            client = Client(api_key="k")
            with pytest.raises(NotFoundError) as exc_info:
                client.agents.get("agt_missing")
        assert exc_info.value.status_code == 404

    def test_401_raises_authentication_error(self):
        resp = _make_response(401, {"error": {"code": "UNAUTHORIZED", "message": "Bad key"}})
        with _mock_session_request(resp):
            client = Client(api_key="bad")
            with pytest.raises(AuthenticationError):
                client.agents.list()

    def test_429_raises_rate_limit_error(self):
        resp = _make_response(429, {"error": {"code": "RATE_LIMITED", "message": "slow down"}})
        with _mock_session_request(resp):
            client = Client(api_key="k")
            with pytest.raises(RateLimitError):
                client.agents.list()

    def test_500_raises_agent_comms_error(self):
        resp = _make_response(500, {"error": {"code": "INTERNAL", "message": "oops"}})
        with _mock_session_request(resp):
            client = Client(api_key="k", max_retries=0)
            with pytest.raises(AgentCommsError):
                client.agents.list()

    def test_error_as_string_body(self):
        # The server returns {"error": "<string>"}; it must map to a real
        # AgentCommsError with the string as the message, not an AttributeError.
        resp = _make_response(400, {"error": "bad request payload"})
        with _mock_session_request(resp):
            client = Client(api_key="k")
            with pytest.raises(AgentCommsError) as exc_info:
                client.agents.create(name="x")
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "bad request payload"
        assert exc_info.value.code == "ERROR"

    def test_error_as_string_body_on_subclass(self):
        resp = _make_response(404, {"error": "agent not found"})
        with _mock_session_request(resp):
            client = Client(api_key="k")
            with pytest.raises(NotFoundError) as exc_info:
                client.agents.get("agt_missing")
        assert exc_info.value.message == "agent not found"

    def test_error_object_body_still_parsed(self):
        resp = _make_response(404, {"error": {"code": "NOT_FOUND", "message": "nope"}})
        with _mock_session_request(resp):
            client = Client(api_key="k")
            with pytest.raises(NotFoundError) as exc_info:
                client.agents.get("agt_missing")
        assert exc_info.value.code == "NOT_FOUND"
        assert exc_info.value.message == "nope"


# ---------------------------------------------------------------------------
# Retry / resilience
# ---------------------------------------------------------------------------

class TestRetries:
    def test_retries_idempotent_on_429_then_succeeds(self):
        err = _make_response(429, {"error": "slow down"})
        ok = _make_response(200, {"agents": []})
        with patch("requests.Session.request", side_effect=[err, ok]) as mock_req:
            client = Client(api_key="k")
            agents = client.agents.list()
        assert mock_req.call_count == 2
        assert agents == []

    def test_retries_idempotent_on_500_then_succeeds(self):
        err = _make_response(503, {"error": "unavailable"})
        ok = _make_response(200, {"agents": []})
        with patch("requests.Session.request", side_effect=[err, ok]) as mock_req:
            client = Client(api_key="k")
            client.agents.list()
        assert mock_req.call_count == 2

    def test_retries_exhaust_then_raise(self):
        resp = _make_response(500, {"error": "boom"})
        with patch("requests.Session.request", return_value=resp) as mock_req:
            client = Client(api_key="k", max_retries=2)
            with pytest.raises(ServerError):
                client.agents.list()
        # 1 initial attempt + 2 retries
        assert mock_req.call_count == 3

    def test_non_idempotent_not_retried(self):
        resp = _make_response(500, {"error": "boom"})
        with patch("requests.Session.request", return_value=resp) as mock_req:
            client = Client(api_key="k", max_retries=3)
            with pytest.raises(ServerError):
                client.agents.create(name="x")  # POST — not idempotent
        assert mock_req.call_count == 1

    def test_retry_after_header_honored(self):
        err = _make_response(429, {"error": "slow"}, headers={"Retry-After": "2"})
        ok = _make_response(200, {"agents": []})
        with patch("requests.Session.request", side_effect=[err, ok]):
            with patch("agentcomms.client.time.sleep") as mock_sleep:
                client = Client(api_key="k")
                client.agents.list()
        mock_sleep.assert_called_once_with(2.0)


# ---------------------------------------------------------------------------
# Deprecation shim
# ---------------------------------------------------------------------------

class TestDeprecationShim:
    def test_freemail_import_emits_deprecation_warning(self):
        import sys
        # Remove cached module so warning fires fresh
        for mod in list(sys.modules.keys()):
            if mod.startswith("freemail"):
                del sys.modules[mod]
        with pytest.warns(DeprecationWarning, match="freemail.*deprecated"):
            import freemail  # noqa: F401

    def test_freemail_re_exports_client(self):
        import sys
        for mod in list(sys.modules.keys()):
            if mod.startswith("freemail"):
                del sys.modules[mod]
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from freemail import Client as FMClient
        assert FMClient is Client
