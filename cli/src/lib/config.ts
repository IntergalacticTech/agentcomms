// SPDX-License-Identifier: Apache-2.0
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export interface AgentCommsConfig {
  domain?: string;
  region?: string;
  apiUrl?: string;
  consoleUrl?: string;
  adminEmail?: string;
  adminApiKey?: string;
  orgId?: string;
  lastBootstrapped?: string;
}

export function configDir(): string {
  return join(homedir(), ".agentcomms");
}

export function configPath(): string {
  return join(configDir(), "config.json");
}

export function readConfig(): AgentCommsConfig {
  const path = configPath();
  if (!existsSync(path)) {
    return {};
  }
  try {
    const raw = readFileSync(path, "utf8");
    return JSON.parse(raw) as AgentCommsConfig;
  } catch {
    return {};
  }
}

export function writeConfig(config: AgentCommsConfig): void {
  const dir = configDir();
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
  writeFileSync(configPath(), JSON.stringify(config, null, 2) + "\n", "utf8");
}

export function mergeConfig(updates: Partial<AgentCommsConfig>): AgentCommsConfig {
  const current = readConfig();
  const merged = { ...current, ...updates };
  writeConfig(merged);
  return merged;
}
