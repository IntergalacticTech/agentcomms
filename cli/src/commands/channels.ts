// SPDX-License-Identifier: Apache-2.0
import { Command } from "commander";
import { setMode, emit } from "../lib/ndjson.js";

const KNOWN_CHANNELS = ["email", "sms", "slack", "telegram", "push", "discord"];

export function channelsCommand(): Command {
  const channels = new Command("channels").description(
    "Enable, disable, or list channel adapters"
  );

  channels
    .command("list")
    .description("List all channels and their status")
    .option("--json", "NDJSON output", false)
    .action(async (opts: { json: boolean }) => {
      if (opts.json) setMode("json");
      emit({
        phase: "channels",
        status: "ok",
        channels: KNOWN_CHANNELS.map((name) => ({
          name,
          adapter: name === "discord" ? "scaffold" : "built-in",
        })),
        note: "Per-agent channels are created with POST /v1/agents/{agent_id}/channels or the SDK/MCP channel_create tool.",
      });
    });

  channels
    .command("enable <channel>")
    .description(`Enable a channel adapter (${KNOWN_CHANNELS.join(", ")})`)
    .option("--json", "NDJSON output", false)
    .action(async (channel: string, opts: { json: boolean }) => {
      if (opts.json) setMode("json");
      if (!KNOWN_CHANNELS.includes(channel)) {
        emit({
          phase: "channels",
          status: "fail",
          msg: `unknown channel ${channel}; valid: ${KNOWN_CHANNELS.join(", ")}`,
        });
        process.exit(1);
      }
      emit({
        phase: "channels",
        status: "fail",
        channel,
        msg: "Adapter enablement is deploy-time today. Rerun bootstrap without this channel in --skip-channels, then create per-agent channels through /v1/agents/{agent_id}/channels.",
      });
      process.exit(1);
    });

  channels
    .command("disable <channel>")
    .description("Disable a channel adapter")
    .option("--json", "NDJSON output", false)
    .action(async (channel: string, opts: { json: boolean }) => {
      if (opts.json) setMode("json");
      emit({
        phase: "channels",
        status: "fail",
        channel,
        msg: "Adapter disablement is deploy-time today. Redeploy with --skip-channels or delete per-agent channel records with the SDK/API.",
      });
      process.exit(1);
    });

  return channels;
}
