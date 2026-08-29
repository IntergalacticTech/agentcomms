# tests/core/test_adapter_base.py
import pytest
from core.adapters.base import (
    ChannelAdapter, IngestPayload, OutboundMessage, HealthStatus,
    ProvisionResult, BridgeStart,
)


class _StubAdapter(ChannelAdapter):
    channel_name = "stub"
    supports_modes = ["provision"]

    def provision(self, *, agent, config):
        return ProvisionResult(status="active", channel_id="chan_stub_1", details={})

    def teardown(self, *, channel):
        pass

    def health_check(self, *, channel):
        return HealthStatus(ok=True, last_success_at="2026-01-01T00:00:00Z")

    def ingest(self, *, payload):
        return None

    def send(self, *, channel, message):
        from core.adapters.base import SendResult
        return SendResult(channel_native_id="x", status="sent")


def test_abstract_methods_required():
    """Instantiating ChannelAdapter without implementing abstract methods raises."""
    class Broken(ChannelAdapter):
        channel_name = "broken"
        supports_modes = []
    with pytest.raises(TypeError):
        Broken()


def test_stub_adapter_instantiates():
    a = _StubAdapter()
    assert a.channel_name == "stub"


def test_bridge_methods_default_raise_not_implemented():
    a = _StubAdapter()
    with pytest.raises(NotImplementedError):
        a.bridge_start(agent=None, config={})
    with pytest.raises(NotImplementedError):
        a.bridge_complete(channel=None, callback_params={})


def test_list_native_containers_defaults_empty():
    a = _StubAdapter()
    assert a.list_native_containers(channel=None) == []


def test_ingest_payload_construction():
    p = IngestPayload(source="sns", headers={"a": "b"}, body=b"x", path_params={})
    assert p.source == "sns"


def test_outbound_message_construction():
    o = OutboundMessage(to="x@y.com", body_text="hi")
    assert o.to == "x@y.com"
