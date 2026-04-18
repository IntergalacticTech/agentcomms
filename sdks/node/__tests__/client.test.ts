// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import { jest } from "@jest/globals";
import { Client } from "../src/client.js";
import {
  AgentCommsError,
  NotFoundError,
  AuthenticationError,
  RateLimitError,
} from "../src/errors.js";

// ---------------------------------------------------------------------------
// Helper: create a mock Response that globalThis.fetch will return
// ---------------------------------------------------------------------------

function mockResponse(status: number, body: unknown): Response {
  const json = JSON.stringify(body);
  return new Response(json, {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(status: number, body: unknown) {
  return jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockResponse(status, body) as never);
}

afterEach(() => {
  jest.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Client construction
// ---------------------------------------------------------------------------

describe("Client construction", () => {
  test("stores api key and default base url", () => {
    const client = new Client({ apiKey: "ak_live_test" });
    expect(client.apiKey).toBe("ak_live_test");
    expect(client.baseUrl).toBe("https://api.agentcomms.dev/v1");
  });

  test("strips trailing slash from custom base url", () => {
    const client = new Client({ apiKey: "k", baseUrl: "http://localhost:8000/v1/" });
    expect(client.baseUrl).toBe("http://localhost:8000/v1");
  });

  test("throws when no api key provided", () => {
    const saved = process.env["AGENTCOMMS_API_KEY"];
    delete process.env["AGENTCOMMS_API_KEY"];
    expect(() => new Client()).toThrow(/api key required/i);
    if (saved !== undefined) process.env["AGENTCOMMS_API_KEY"] = saved;
  });
});

// ---------------------------------------------------------------------------
// Agents resource
// ---------------------------------------------------------------------------

describe("agents.list()", () => {
  test("hits GET /agents with Bearer auth and returns array", async () => {
    const spy = mockFetch(200, {
      agents: [{ agent_id: "agt_1", name: "Bot", org_id: "org_1" }],
    });
    const client = new Client({ apiKey: "ak_live_test" });
    const agents = await client.agents.list();
    expect(spy).toHaveBeenCalledTimes(1);
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agents");
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer ak_live_test");
    expect(agents).toHaveLength(1);
    expect(agents[0].agent_id).toBe("agt_1");
  });
});

describe("agents.create()", () => {
  test("issues POST to /agents", async () => {
    const spy = mockFetch(201, { agent_id: "agt_2", name: "x", org_id: "org_1" });
    const client = new Client({ apiKey: "k" });
    const result = await client.agents.create({ name: "x" });
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    expect(result.agent_id).toBe("agt_2");
  });
});

describe("agents.agent().messages.list()", () => {
  test("hits GET /agents/:id/messages", async () => {
    const spy = mockFetch(200, {
      messages: [{ message_id: "msg_1", agent_id: "agt_1" }],
    });
    const client = new Client({ apiKey: "k" });
    const msgs = await client.agents.agent("agt_1").messages.list();
    const [url] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agents/agt_1/messages");
    expect(msgs).toHaveLength(1);
  });
});

describe("agents.agent().messages.send()", () => {
  test("issues POST with body", async () => {
    const spy = mockFetch(202, { message_id: "msg_out_1" });
    const client = new Client({ apiKey: "k" });
    const result = await client.agents.agent("agt_1").messages.send({
      to: "alice@example.com",
      body: "Hello",
    });
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    expect((result as { message_id: string }).message_id).toBe("msg_out_1");
  });
});

// ---------------------------------------------------------------------------
// Vault resource
// ---------------------------------------------------------------------------

describe("vault.create()", () => {
  test("issues POST to /vault", async () => {
    const spy = mockFetch(201, { vault_id: "v_1", name: "MY_KEY", type: "secret", org_id: "org_1" });
    const client = new Client({ apiKey: "k" });
    const item = await client.vault.create({ name: "MY_KEY", value: "s3cr3t" });
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    expect((item as { vault_id: string }).vault_id).toBe("v_1");
  });
});

// ---------------------------------------------------------------------------
// Webhooks resource
// ---------------------------------------------------------------------------

describe("agents.agent().webhooks.create()", () => {
  test("issues POST to /agents/:id/webhooks", async () => {
    const spy = mockFetch(201, {
      webhook_id: "wh_1",
      agent_id: "agt_1",
      url: "https://example.com/hook",
      events: ["message.received"],
    });
    const client = new Client({ apiKey: "k" });
    await client.agents.agent("agt_1").webhooks.create({
      url: "https://example.com/hook",
      events: ["message.received"],
    });
    const [url] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agents/agt_1/webhooks");
  });
});

// ---------------------------------------------------------------------------
// Domains resource
// ---------------------------------------------------------------------------

describe("domains.list()", () => {
  test("issues GET to /domains", async () => {
    const spy = mockFetch(200, {
      domains: [{ domain_id: "dom_1", domain: "example.com", org_id: "org_1" }],
    });
    const client = new Client({ apiKey: "k" });
    const domains = await client.domains.list();
    const [url] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/domains");
    expect(domains).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

describe("error handling", () => {
  test("404 response throws NotFoundError", async () => {
    mockFetch(404, { error: { code: "NOT_FOUND", message: "Agent not found" } });
    const client = new Client({ apiKey: "k" });
    await expect(client.agents.get("missing")).rejects.toBeInstanceOf(NotFoundError);
  });

  test("401 response throws AuthenticationError", async () => {
    mockFetch(401, { error: { code: "UNAUTHORIZED", message: "Bad key" } });
    const client = new Client({ apiKey: "bad" });
    await expect(client.agents.list()).rejects.toBeInstanceOf(AuthenticationError);
  });

  test("429 response throws RateLimitError", async () => {
    mockFetch(429, { error: { code: "RATE_LIMITED", message: "slow down" } });
    const client = new Client({ apiKey: "k" });
    await expect(client.agents.list()).rejects.toBeInstanceOf(RateLimitError);
  });

  test("500 response throws AgentCommsError", async () => {
    mockFetch(500, { error: { code: "INTERNAL", message: "oops" } });
    const client = new Client({ apiKey: "k" });
    await expect(client.agents.list()).rejects.toBeInstanceOf(AgentCommsError);
  });
});
