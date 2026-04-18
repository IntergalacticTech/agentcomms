# tests/core/test_registry.py
import sys
import pytest
from pathlib import Path
from core.adapters.registry import load_registry, AdapterEntry


def _purge_adapter_modules(monkeypatch):
    """Remove any cached adapters.* entries from sys.modules so each test
    gets a fresh import from its own tmp_path."""
    stale = [k for k in sys.modules if k == "adapters" or k.startswith("adapters.")]
    for key in stale:
        monkeypatch.delitem(sys.modules, key)


def test_load_registry_scans_manifests(tmp_path, monkeypatch):
    # Create a fake adapters directory
    adapters_dir = tmp_path / "adapters"
    fake_adapter_dir = adapters_dir / "fakechan"
    fake_adapter_dir.mkdir(parents=True)
    (adapters_dir / "__init__.py").write_text("")
    (fake_adapter_dir / "__init__.py").write_text("")
    (fake_adapter_dir / "manifest.toml").write_text("""
[adapter]
channel = "fakechan"
class = "adapters.fakechan.adapter:FakeAdapter"
modes = ["provision"]
min_hub_version = "0.1"

[webhook_routes]

[ssm_secrets]
""")
    (fake_adapter_dir / "adapter.py").write_text("""
from core.adapters.base import ChannelAdapter, ProvisionResult, HealthStatus

class FakeAdapter(ChannelAdapter):
    channel_name = "fakechan"
    supports_modes = ["provision"]
    def provision(self, *, agent, config):
        return ProvisionResult(status="active", channel_id="chan_fake_1", details={})
    def teardown(self, *, channel): pass
    def health_check(self, *, channel): return HealthStatus(ok=True, last_success_at="x")
    def ingest(self, *, payload): return None
    def send(self, *, channel, message):
        from core.adapters.base import SendResult
        return SendResult(channel_native_id="x", status="sent")
""")

    _purge_adapter_modules(monkeypatch)
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = load_registry(adapters_root=adapters_dir)
    assert "fakechan" in registry
    entry = registry["fakechan"]
    assert isinstance(entry, AdapterEntry)
    assert entry.channel == "fakechan"
    assert entry.modes == ["provision"]
    assert entry.adapter.channel_name == "fakechan"


def test_load_registry_skips_missing_manifest(tmp_path):
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir()
    (adapters_dir / "notes.txt").write_text("not an adapter")
    registry = load_registry(adapters_root=adapters_dir)
    assert registry == {}


def test_adapter_entry_webhook_routes(tmp_path, monkeypatch):
    adapters_dir = tmp_path / "adapters"
    fake = adapters_dir / "hooked"
    fake.mkdir(parents=True)
    (adapters_dir / "__init__.py").write_text("")
    (fake / "__init__.py").write_text("")
    (fake / "manifest.toml").write_text("""
[adapter]
channel = "hooked"
class = "adapters.hooked.adapter:HookedAdapter"
modes = ["provision"]

[webhook_routes]
inbound = { path = "/webhooks/hooked", method = "POST" }
""")
    (fake / "adapter.py").write_text("""
from core.adapters.base import ChannelAdapter, ProvisionResult, HealthStatus, SendResult
class HookedAdapter(ChannelAdapter):
    channel_name = "hooked"
    supports_modes = ["provision"]
    def provision(self, *, agent, config): return ProvisionResult(status="active", channel_id="x", details={})
    def teardown(self, *, channel): pass
    def health_check(self, *, channel): return HealthStatus(ok=True, last_success_at="x")
    def ingest(self, *, payload): return None
    def send(self, *, channel, message): return SendResult(channel_native_id="x", status="sent")
""")
    _purge_adapter_modules(monkeypatch)
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = load_registry(adapters_root=adapters_dir)
    assert registry["hooked"].webhook_routes == {
        "inbound": {"path": "/webhooks/hooked", "method": "POST"}
    }


def test_discord_scaffold_skipped(monkeypatch):
    """Discord manifest has no [adapter] section → registry must not load it."""
    # Ensure the real project root is in sys.path so adapter imports resolve.
    project_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(project_root))
    _purge_adapter_modules(monkeypatch)

    from core.adapters.registry import load_registry
    registry = load_registry(
        adapters_root=project_root / "adapters",
        load_entry_points=False,
    )
    assert "discord" not in registry, (
        "Discord scaffold should not be registered (manifest has no [adapter] section)"
    )
    # Sanity: email should still be present
    assert "email" in registry
