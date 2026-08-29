// SPDX-License-Identifier: Apache-2.0
import { jest, describe, it, expect, beforeEach, afterEach } from "@jest/globals";

// Must set env before importing config
process.env.AGENTCOMMS_API_KEY = "ak_test_mockkey";
process.env.AGENTCOMMS_BASE_URL = "https://api.agentcomms.dev/v1";

import { agentTools } from "../tools/agents.js";
import { vaultTools } from "../tools/vault.js";
import { messageTools } from "../tools/messages.js";
import { channelTools } from "../tools/channels.js";

// Typed fetch mock
type FetchImpl = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

function makeFetchMock(body: unknown, status = 200): FetchImpl {
  return jest.fn<FetchImpl>().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  );
}

describe("agent_list tool", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("returns an array of agents from the API", async () => {
    const mockAgents = [
      { agent_id: "ag_1", name: "TestBot" },
      { agent_id: "ag_2", name: "ScrapeBot" },
    ];
    global.fetch = makeFetchMock(mockAgents) as typeof fetch;

    const tool = agentTools.find((t) => t.name === "agent_list")!;
    const result = await tool.handler({});

    expect(result).toEqual(mockAgents);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/agents"),
      expect.objectContaining({ method: "GET" })
    );
  });
});

describe("vault_get_totp tool", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("returns {code, valid_until} for a TOTP vault entry", async () => {
    const mockTotp = { code: "123456", valid_until: 1750000030000 };
    global.fetch = makeFetchMock(mockTotp) as typeof fetch;

    const tool = vaultTools.find((t) => t.name === "vault_get_totp")!;
    const result = await tool.handler({ vault_id: "vlt_abc123" }) as typeof mockTotp;

    expect(result).toHaveProperty("code");
    expect(result).toHaveProperty("valid_until");
    expect(result.code).toBe("123456");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/vault/vlt_abc123/totp"),
      expect.objectContaining({ method: "GET" })
    );
  });
});

describe("message_send tool", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("sends without channel and API receives auto-inference body", async () => {
    const mockResponse = { message_id: "msg_xyz", status: "queued" };
    global.fetch = makeFetchMock(mockResponse) as typeof fetch;

    const tool = messageTools.find((t) => t.name === "message_send")!;
    await tool.handler({
      agent_id: "ag_1",
      to: "user@example.com",
      body: "Hello!",
    });

    const callArgs = (global.fetch as jest.MockedFunction<FetchImpl>).mock.calls[0];
    const requestInit = callArgs[1] as RequestInit;
    const sentBody = JSON.parse(requestInit.body as string);

    expect(sentBody).toHaveProperty("to", "user@example.com");
    expect(sentBody).toHaveProperty("body", "Hello!");
    expect(sentBody).not.toHaveProperty("channel");
  });

  it("includes channel when explicitly provided", async () => {
    const mockResponse = { message_id: "msg_abc", status: "queued" };
    global.fetch = makeFetchMock(mockResponse) as typeof fetch;

    const tool = messageTools.find((t) => t.name === "message_send")!;
    await tool.handler({
      agent_id: "ag_1",
      to: "user@example.com",
      body: "Hello via email!",
      channel: "ch_email_001",
    });

    const callArgs = (global.fetch as jest.MockedFunction<FetchImpl>).mock.calls[0];
    const requestInit = callArgs[1] as RequestInit;
    const sentBody = JSON.parse(requestInit.body as string);

    expect(sentBody).toHaveProperty("channel", "ch_email_001");
  });
});

describe("channels_list tool", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("calls the correct endpoint for the agent", async () => {
    const mockChannels = [
      { channel_id: "ch_1", type: "email", address: "bot@agentcomms.dev" },
    ];
    global.fetch = makeFetchMock(mockChannels) as typeof fetch;

    const tool = channelTools.find((t) => t.name === "channels_list")!;
    const result = await tool.handler({ agent_id: "ag_99" });

    expect(result).toEqual(mockChannels);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/agents/ag_99/channels"),
      expect.anything()
    );
  });
});

describe("apiRequest error handling", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("surfaces the HTTP status on a non-ok response (checked before parsing)", async () => {
    global.fetch = makeFetchMock("internal boom", 500) as typeof fetch;

    const tool = agentTools.find((t) => t.name === "agent_list")!;
    await expect(tool.handler({})).rejects.toThrow(/API error 500/);
  });

  it("surfaces status even when the error body is not valid JSON", async () => {
    // A non-JSON body would previously blow up in resp.json(); now we check
    // resp.ok first and read the body as text.
    const nonJson: FetchImpl = jest.fn<FetchImpl>().mockResolvedValue(
      new Response("<html>502 Bad Gateway</html>", {
        status: 502,
        headers: { "Content-Type": "text/html" },
      })
    );
    global.fetch = nonJson as typeof fetch;

    const tool = agentTools.find((t) => t.name === "agent_list")!;
    await expect(tool.handler({})).rejects.toThrow(/API error 502/);
  });

  it("passes an AbortSignal for timeout enforcement", async () => {
    global.fetch = makeFetchMock([]) as typeof fetch;

    const tool = agentTools.find((t) => t.name === "agent_list")!;
    await tool.handler({});

    const callArgs = (global.fetch as jest.MockedFunction<FetchImpl>).mock.calls[0];
    const requestInit = callArgs[1] as RequestInit;
    expect(requestInit.signal).toBeInstanceOf(AbortSignal);
  });
});
