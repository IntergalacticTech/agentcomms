// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { Command } from "commander";
import { setMode, emit } from "../lib/ndjson.js";
import { readConfig } from "../lib/config.js";

const KNOWN_CHANNELS = ["email", "sms", "slack", "telegram", "push", "discord"];

async function apiRequest(
  apiUrl: string,
  path: string,
  apiKey: string,
  method = "GET",
  body?: unknown
): Promise<unknown> {
  const url = `${apiUrl}${path}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${apiKey}`,
    "Content-Type": "application/json",
  };
  const opts: RequestInit = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return resp.json();
}

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
      const config = readConfig();
      const apiUrl = config.apiUrl;
      const apiKey = config.adminApiKey;

      if (!apiUrl || !apiKey) {
        emit({
          phase: "channels",
          status: "fail",
          msg: "no API URL or key configured; run agentcomms bootstrap first",
        });
        process.exit(1);
      }

      try {
        const data = await apiRequest(apiUrl, "/channels", apiKey);
        emit({ phase: "channels", status: "ok", channels: data });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "channels", status: "fail", msg });
        process.exit(1);
      }
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
      const config = readConfig();
      const apiUrl = config.apiUrl;
      const apiKey = config.adminApiKey;

      if (!apiUrl || !apiKey) {
        emit({
          phase: "channels",
          status: "fail",
          msg: "no API URL or key configured; run agentcomms bootstrap first",
        });
        process.exit(1);
      }

      emit({ phase: "channels", status: "running", msg: `enabling ${channel}` });
      try {
        const data = await apiRequest(apiUrl, `/channels/${channel}/enable`, apiKey, "POST");
        emit({ phase: "channels", status: "ok", channel, result: data });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "channels", status: "fail", channel, msg });
        process.exit(1);
      }
    });

  channels
    .command("disable <channel>")
    .description("Disable a channel adapter")
    .option("--json", "NDJSON output", false)
    .action(async (channel: string, opts: { json: boolean }) => {
      if (opts.json) setMode("json");
      const config = readConfig();
      const apiUrl = config.apiUrl;
      const apiKey = config.adminApiKey;

      if (!apiUrl || !apiKey) {
        emit({
          phase: "channels",
          status: "fail",
          msg: "no API URL or key configured; run agentcomms bootstrap first",
        });
        process.exit(1);
      }

      emit({ phase: "channels", status: "running", msg: `disabling ${channel}` });
      try {
        const data = await apiRequest(apiUrl, `/channels/${channel}/disable`, apiKey, "POST");
        emit({ phase: "channels", status: "ok", channel, result: data });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "channels", status: "fail", channel, msg });
        process.exit(1);
      }
    });

  return channels;
}
