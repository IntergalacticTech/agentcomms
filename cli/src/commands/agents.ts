// SPDX-License-Identifier: Apache-2.0
import { Command } from "commander";
import { setMode, emit } from "../lib/ndjson.js";
import { readConfig } from "../lib/config.js";

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

function getApiConfig(): { apiUrl: string; apiKey: string } {
  const config = readConfig();
  if (!config.apiUrl || !config.adminApiKey) {
    emit({
      phase: "agents",
      status: "fail",
      msg: "no API URL or key configured; run agentcomms bootstrap first",
    });
    process.exit(1);
  }
  return { apiUrl: config.apiUrl, apiKey: config.adminApiKey };
}

export function agentsCommand(): Command {
  const agents = new Command("agents").description("Manage agent records");

  agents
    .command("list")
    .description("List all agents")
    .option("--json", "NDJSON output", false)
    .action(async (opts: { json: boolean }) => {
      if (opts.json) setMode("json");
      const { apiUrl, apiKey } = getApiConfig();
      try {
        const data = await apiRequest(apiUrl, "/agents", apiKey);
        emit({ phase: "agents", status: "ok", agents: data });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "agents", status: "fail", msg });
        process.exit(1);
      }
    });

  agents
    .command("create")
    .description("Create a new agent")
    .requiredOption("--name <name>", "agent display name")
    .option("--channels <list>", "comma-separated channels to provision (email,sms,...)", "email")
    .option("--json", "NDJSON output", false)
    .action(async (opts: { name: string; channels: string; json: boolean }) => {
      if (opts.json) setMode("json");
      const { apiUrl, apiKey } = getApiConfig();
      const channels = opts.channels.split(",").filter(Boolean);
      emit({ phase: "agents", status: "running", msg: `creating agent ${opts.name}` });
      try {
        const data = await apiRequest(apiUrl, "/agents", apiKey, "POST", {
          name: opts.name,
          channels,
        });
        emit({ phase: "agents", status: "ok", agent: data });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "agents", status: "fail", msg });
        process.exit(1);
      }
    });

  agents
    .command("delete <agentId>")
    .description("Delete an agent by ID")
    .option("--json", "NDJSON output", false)
    .action(async (agentId: string, opts: { json: boolean }) => {
      if (opts.json) setMode("json");
      const { apiUrl, apiKey } = getApiConfig();
      emit({ phase: "agents", status: "running", msg: `deleting agent ${agentId}` });
      try {
        await apiRequest(apiUrl, `/agents/${agentId}`, apiKey, "DELETE");
        emit({ phase: "agents", status: "ok", msg: `agent ${agentId} deleted` });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "agents", status: "fail", msg });
        process.exit(1);
      }
    });

  return agents;
}
