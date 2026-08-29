# Discord Adapter Scaffold

**Status:** SCAFFOLD ONLY — not functional in Phase 3.

This directory is a template for a Discord channel adapter. It documents the
adapter pattern so a Phase 3.5 implementer or community contributor can fill it
in without needing to read all of core/.

## Where to start

1. Read `adapter.py` in this directory — the class skeleton with inline
   implementation notes (quoted from the module docstring):

   > 1. Use discord.py or raw HTTP against https://discord.com/api/v10
   > 2. Bridge mode via Discord OAuth2 (similar to Slack OAuth v2)
   > 3. Events via interactions endpoint (signature verified with Ed25519)
   > 4. Native hierarchy: guilds → channels → DMs
   > 5. DM inference: channel.type == 1 (DM) OR message @mentions bot

2. Copy the Slack adapter (`adapters/slack/`) as the closest analogue — Discord
   also uses OAuth v2 bridge mode, a signing-secret for request verification,
   and a bot-token stored in SSM.

3. Read **Spec §4** (`docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md`)
   for the full adapter contract and CDK wiring requirements.

## Activating the adapter

When the implementation is ready:

1. Uncomment the `[adapter]` section in `manifest.toml`.
2. Add a `stack.py` CDK class for the Discord webhook Lambda + SQS outbound queue.
3. Register CDK stack reference in `manifest.toml` under `cdk_stack`.
4. Add tests under `adapters/discord/tests/`.
5. Run the full suite: `pytest tests/core tests/api tests/e2e adapters -q`.
