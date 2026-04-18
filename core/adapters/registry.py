# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/adapters/registry.py
"""
Discovers channel adapters in two ways:
  1. In-repo: scans `adapters/*/manifest.toml` at the supplied root.
  2. Third-party: scans Python entry points in the `agentcomms.adapters` group.

Returns a dict keyed by channel name.
"""
from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.adapters.base import ChannelAdapter


@dataclass
class AdapterEntry:
    channel: str
    adapter: ChannelAdapter
    modes: list[str]
    min_hub_version: str = "0.1"
    webhook_routes: dict[str, dict[str, str]] = field(default_factory=dict)
    ssm_secrets: dict[str, str] = field(default_factory=dict)
    cdk_stack_ref: str | None = None


def _load_class(dotted: str) -> type:
    module_path, class_name = dotted.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _entry_from_manifest(manifest_path: Path) -> AdapterEntry | None:
    with manifest_path.open("rb") as f:
        manifest = tomllib.load(f)
    adapter_cfg = manifest.get("adapter")
    if not adapter_cfg:
        return None
    cls = _load_class(adapter_cfg["class"])
    instance = cls()
    return AdapterEntry(
        channel=adapter_cfg["channel"],
        adapter=instance,
        modes=adapter_cfg.get("modes", []),
        min_hub_version=adapter_cfg.get("min_hub_version", "0.1"),
        webhook_routes=manifest.get("webhook_routes", {}),
        ssm_secrets=manifest.get("ssm_secrets", {}),
        cdk_stack_ref=adapter_cfg.get("cdk_stack"),
    )


def load_registry(
    adapters_root: Path | None = None,
    *,
    load_entry_points: bool = True,
) -> dict[str, AdapterEntry]:
    if adapters_root is None:
        adapters_root = Path(__file__).resolve().parents[2] / "adapters"
    registry: dict[str, AdapterEntry] = {}
    if adapters_root.exists():
        for child in sorted(adapters_root.iterdir()):
            manifest = child / "manifest.toml"
            if not manifest.is_file():
                continue
            entry = _entry_from_manifest(manifest)
            if entry is not None:
                registry[entry.channel] = entry

    if load_entry_points:
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="agentcomms.adapters")
        except Exception:
            eps = []
        for ep in eps:
            cls = ep.load()
            instance = cls()
            if instance.channel_name not in registry:
                registry[instance.channel_name] = AdapterEntry(
                    channel=instance.channel_name,
                    adapter=instance,
                    modes=list(instance.supports_modes),
                )

    return registry
