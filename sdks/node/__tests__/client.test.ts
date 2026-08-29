// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
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
    const spy = mockFetch(201, { message_id: "msg_out_1" });
    const client = new Client({ apiKey: "k" });
    const result = await client.agents.agent("agt_1").messages.send({
      to: "alice@example.com",
      body: "Hello",
    });
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    expect((result as { message_id: string }).message_id).toBe("msg_out_1");
  });
});

describe("agents.agent().ai.summarize()", () => {
  test("sends raw text payload", async () => {
    const spy = mockFetch(200, { summary: "Short summary" });
    const client = new Client({ apiKey: "k" });
    const result = await client.agents.agent("agt_1").ai.summarize({
      text: "Long body",
      length: "short",
    });
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agents/agt_1/ai/summarize");
    expect(JSON.parse(String(init.body))).toEqual({ text: "Long body", length: "short" });
    expect(result.summary).toBe("Short summary");
  });
});

describe("agents.agent().messages.wait()", () => {
  test("sends canonical channels array for multi-channel filters", async () => {
    const spy = mockFetch(200, { message_id: "msg_1", agent_id: "agt_1", channel: "email" });
    const client = new Client({ apiKey: "k" });
    await client.agents.agent("agt_1").messages.wait({ channels: ["email", "slack"] });
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toMatchObject({ channels: ["email", "slack"] });
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
    const client = new Client({ apiKey: "k", maxRetries: 0 });
    await expect(client.agents.list()).rejects.toBeInstanceOf(RateLimitError);
  });

  test("500 response throws AgentCommsError", async () => {
    mockFetch(500, { error: { code: "INTERNAL", message: "oops" } });
    const client = new Client({ apiKey: "k", maxRetries: 0 });
    await expect(client.agents.list()).rejects.toBeInstanceOf(AgentCommsError);
  });

  test("error body as bare string is used as the message", async () => {
    mockFetch(400, { error: "bad request payload" });
    const client = new Client({ apiKey: "k", maxRetries: 0 });
    await expect(client.agents.create({ name: "x" })).rejects.toMatchObject({
      statusCode: 400,
      code: "ERROR",
      message: expect.stringContaining("bad request payload"),
    });
  });

  test("error body as string on a 404 maps to NotFoundError with the message", async () => {
    mockFetch(404, { error: "agent not found" });
    const client = new Client({ apiKey: "k", maxRetries: 0 });
    await expect(client.agents.get("missing")).rejects.toMatchObject({
      name: "NotFoundError",
      message: expect.stringContaining("agent not found"),
    });
  });
});

// ---------------------------------------------------------------------------
// Agent update (PUT)
// ---------------------------------------------------------------------------

describe("agents.patch()/update()", () => {
  test("patch issues PUT to /agents/:id", async () => {
    const spy = mockFetch(200, { agent_id: "agt_1", name: "Renamed", org_id: "org_1" });
    const client = new Client({ apiKey: "k" });
    const agent = await client.agents.patch("agt_1", { name: "Renamed" });
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect(url).toContain("/agents/agt_1");
    expect(agent.name).toBe("Renamed");
  });

  test("update alias also issues PUT", async () => {
    const spy = mockFetch(200, { agent_id: "agt_1", name: "Renamed", org_id: "org_1" });
    const client = new Client({ apiKey: "k" });
    await client.agents.update("agt_1", { name: "Renamed" });
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("PUT");
  });
});

// ---------------------------------------------------------------------------
// Retry / resilience
// ---------------------------------------------------------------------------

describe("retry behavior", () => {
  test("retries idempotent GET on 429 then succeeds", async () => {
    const spy = jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockResponse(429, { error: "slow down" }) as never)
      .mockResolvedValueOnce(mockResponse(200, { agents: [] }) as never);
    const client = new Client({ apiKey: "k", retryBaseMs: 0 });
    const agents = await client.agents.list();
    expect(spy).toHaveBeenCalledTimes(2);
    expect(agents).toEqual([]);
  });

  test("retries idempotent GET on 503 then succeeds", async () => {
    const spy = jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockResponse(503, { error: "unavailable" }) as never)
      .mockResolvedValueOnce(mockResponse(200, { agents: [] }) as never);
    const client = new Client({ apiKey: "k", retryBaseMs: 0 });
    await client.agents.list();
    expect(spy).toHaveBeenCalledTimes(2);
  });

  test("exhausts retries then throws", async () => {
    const spy = jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockResponse(500, { error: "boom" }) as never);
    const client = new Client({ apiKey: "k", maxRetries: 2, retryBaseMs: 0 });
    await expect(client.agents.list()).rejects.toBeInstanceOf(AgentCommsError);
    // 1 initial attempt + 2 retries
    expect(spy).toHaveBeenCalledTimes(3);
  });

  test("does not retry non-idempotent POST", async () => {
    const spy = jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockResponse(500, { error: "boom" }) as never);
    const client = new Client({ apiKey: "k", maxRetries: 3, retryBaseMs: 0 });
    await expect(client.agents.create({ name: "x" })).rejects.toBeInstanceOf(AgentCommsError);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
