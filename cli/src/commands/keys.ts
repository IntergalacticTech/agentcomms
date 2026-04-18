// SPDX-License-Identifier: FSL-1.1-Apache-2.0
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
      phase: "keys",
      status: "fail",
      msg: "no API URL or key configured; run agentcomms bootstrap first",
    });
    process.exit(1);
  }
  return { apiUrl: config.apiUrl, apiKey: config.adminApiKey };
}

export function keysCommand(): Command {
  const keys = new Command("keys").description("Manage API keys");

  keys
    .command("list")
    .description("List all API keys")
    .option("--json", "NDJSON output", false)
    .action(async (opts: { json: boolean }) => {
      if (opts.json) setMode("json");
      const { apiUrl, apiKey } = getApiConfig();
      try {
        const data = await apiRequest(apiUrl, "/keys", apiKey);
        emit({ phase: "keys", status: "ok", keys: data });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "keys", status: "fail", msg });
        process.exit(1);
      }
    });

  keys
    .command("create")
    .description("Create a new API key")
    .requiredOption("--name <name>", "name for the key")
    .option("--scope <scope>", "permission scope (org, read, write)", "write")
    .option("--json", "NDJSON output", false)
    .action(async (opts: { name: string; scope: string; json: boolean }) => {
      if (opts.json) setMode("json");
      const { apiUrl, apiKey } = getApiConfig();
      emit({ phase: "keys", status: "running", msg: `creating key ${opts.name}` });
      try {
        const data = await apiRequest(apiUrl, "/keys", apiKey, "POST", {
          name: opts.name,
          scope: opts.scope,
        });
        emit({ phase: "keys", status: "ok", key: data, note: "shown once — store securely" });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "keys", status: "fail", msg });
        process.exit(1);
      }
    });

  keys
    .command("revoke <keyId>")
    .description("Revoke an API key by ID or name")
    .option("--json", "NDJSON output", false)
    .action(async (keyId: string, opts: { json: boolean }) => {
      if (opts.json) setMode("json");
      const { apiUrl, apiKey } = getApiConfig();
      emit({ phase: "keys", status: "running", msg: `revoking key ${keyId}` });
      try {
        await apiRequest(apiUrl, `/keys/${keyId}`, apiKey, "DELETE");
        emit({ phase: "keys", status: "ok", msg: `key ${keyId} revoked` });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        emit({ phase: "keys", status: "fail", msg });
        process.exit(1);
      }
    });

  return keys;
}
