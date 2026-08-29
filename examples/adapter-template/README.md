# AgentComms Adapter Template

This is a minimal external adapter package. It demonstrates the package shape, entry-point registration, channel slug handling, inbound normalization, outbound sends, and tests without depending on a real provider account.

Copy this directory when starting a new adapter such as Discord, Matrix, WhatsApp, fax, voice, postal mail, or another event-shaped transport.

## Files

| File | Purpose |
|---|---|
| `pyproject.toml` | Package metadata and `agentcomms.adapters` entry point |
| `agentcomms_adapter_echo/adapter.py` | `ChannelAdapter` implementation |
| `agentcomms_adapter_echo/normalize.py` | Inbound payload to `UnifiedMessage` mapping |
| `tests/test_adapter.py` | Contract-style unit tests |

## Run Tests

From the repository root:

```bash
./.venv/bin/python -m pytest examples/adapter-template -q
```

To develop it like a standalone package:

```bash
cd examples/adapter-template
python -m venv .venv
source .venv/bin/activate
pip install -e ../..
pip install -e ".[dev]"
pytest -q
```

## Entry Point

The important registration line is:

```toml
[project.entry-points."agentcomms.adapters"]
echo = "agentcomms_adapter_echo.adapter:EchoAdapter"
```

Installed packages in that entry-point group are discovered by `core.adapters.registry.load_registry()`.

## Replace Echo With Your Provider

For a real adapter:

- Change `EchoAdapter.channel_name` to your stable slug.
- Replace `provision` with provider account, address, bot, number, or webhook setup.
- Add signature verification before `ingest` parses provider content.
- Store secrets in SSM/KMS-backed configuration, not API-visible channel config.
- Preserve provider-native IDs in `external_id` and `channel_native`.
- Add native surfaces if the provider has rooms, channels, threads, workspaces, guilds, or folders.

See [docs/adapter-authoring.md](../../docs/adapter-authoring.md) for the full contract.
