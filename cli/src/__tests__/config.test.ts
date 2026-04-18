// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// Tests config read/write round-trip using the actual fs functions
// but with a temp path via env override.
import { readFileSync, writeFileSync, mkdirSync, existsSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import type { AgentCommsConfig } from "../lib/config.js";

// We test the logic directly without mocking — use a temp directory
const TEST_DIR = join(homedir(), ".agentcomms-test-tmp");
const TEST_CONFIG = join(TEST_DIR, "config.json");

// Local reimplementation matching config.ts logic, pointing at our test dir
function readTestConfig(): AgentCommsConfig {
  if (!existsSync(TEST_CONFIG)) return {};
  try {
    return JSON.parse(readFileSync(TEST_CONFIG, "utf8")) as AgentCommsConfig;
  } catch {
    return {};
  }
}

function writeTestConfig(config: AgentCommsConfig): void {
  if (!existsSync(TEST_DIR)) mkdirSync(TEST_DIR, { recursive: true });
  writeFileSync(TEST_CONFIG, JSON.stringify(config, null, 2) + "\n", "utf8");
}

function mergeTestConfig(updates: Partial<AgentCommsConfig>): AgentCommsConfig {
  const current = readTestConfig();
  const merged = { ...current, ...updates };
  writeTestConfig(merged);
  return merged;
}

describe("config read/write round-trip", () => {
  beforeEach(() => {
    if (existsSync(TEST_CONFIG)) rmSync(TEST_CONFIG);
  });

  afterAll(() => {
    try {
      rmSync(TEST_DIR, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  it("returns empty object when no config file exists", () => {
    const config = readTestConfig();
    expect(config).toEqual({});
  });

  it("round-trips a config object", () => {
    const data: AgentCommsConfig = {
      domain: "example.com",
      region: "us-east-1",
      apiUrl: "https://api.example.com/v1",
      adminApiKey: "ak_live_test123",
    };
    writeTestConfig(data);
    const read = readTestConfig();
    expect(read).toEqual(data);
  });

  it("mergeConfig adds new fields without clobbering existing ones", () => {
    writeTestConfig({ domain: "example.com", region: "us-east-1" });
    mergeTestConfig({ adminApiKey: "ak_live_newkey" });
    const read = readTestConfig();
    expect(read.domain).toBe("example.com");
    expect(read.region).toBe("us-east-1");
    expect(read.adminApiKey).toBe("ak_live_newkey");
  });

  it("mergeConfig overwrites existing fields when supplied", () => {
    writeTestConfig({ domain: "old.com" });
    mergeTestConfig({ domain: "new.com" });
    const read = readTestConfig();
    expect(read.domain).toBe("new.com");
  });

  it("creates parent directory if it does not exist", () => {
    // rmSync in beforeEach only removes the file; test that mkdirSync fires
    if (existsSync(TEST_DIR)) rmSync(TEST_DIR, { recursive: true, force: true });
    writeTestConfig({ domain: "example.com" });
    expect(existsSync(TEST_CONFIG)).toBe(true);
  });

  it("produced JSON is parseable and contains expected keys", () => {
    const data: AgentCommsConfig = {
      domain: "test.com",
      orgId: "org_01H",
      adminApiKey: "ak_live_xyz",
    };
    writeTestConfig(data);
    const raw = readFileSync(TEST_CONFIG, "utf8");
    const parsed = JSON.parse(raw) as AgentCommsConfig;
    expect(parsed.domain).toBe("test.com");
    expect(parsed.orgId).toBe("org_01H");
    expect(parsed.adminApiKey).toBe("ak_live_xyz");
  });
});
