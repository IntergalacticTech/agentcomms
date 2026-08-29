# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

"""Discord channel adapter for AgentComms.

STATUS: SCAFFOLD ONLY — not implemented in Phase 3.
See docs/superpowers/plans/2026-04-17-agentcomms-phase3-slack-telegram.md Task 7.

Copy this scaffold to implement Discord:
  1. Use discord.py or raw HTTP against https://discord.com/api/v10
  2. Bridge mode via Discord OAuth2 (similar to Slack OAuth v2)
  3. Events via interactions endpoint (signature verified with Ed25519)
  4. Native hierarchy: guilds → channels → DMs
  5. DM inference: channel.type == 1 (DM) OR message @mentions bot

This scaffold is intentionally non-functional to document the adapter
pattern without silently breaking production.
"""
from core.adapters.base import (
    ChannelAdapter, HealthStatus, IngestPayload, OutboundMessage,
    ProvisionResult, SendResult,
)


class DiscordAdapter(ChannelAdapter):
    channel_name = "discord"
    supports_modes = ["bridge"]

    def provision(self, *, agent, config):
        raise NotImplementedError("Discord adapter is scaffold only; not implemented yet")

    def bridge_start(self, *, agent, config):
        raise NotImplementedError

    def bridge_complete(self, *, channel, callback_params):
        raise NotImplementedError

    def teardown(self, *, channel):
        raise NotImplementedError

    def health_check(self, *, channel):
        return HealthStatus(ok=False, last_success_at="", error="Discord adapter scaffold only; not implemented")

    def ingest(self, *, payload):
        raise NotImplementedError

    def send(self, *, channel, message):
        raise NotImplementedError
