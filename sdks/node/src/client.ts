// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import { AgentsResource } from "./resources/agents.js";
import { VaultResource } from "./resources/vault.js";
import { PersonasResource } from "./resources/personas.js";
import { DomainsResource } from "./resources/domains.js";
import { AgentCommsError } from "./errors.js";

export interface ClientOptions {
  apiKey?: string;
  baseUrl?: string;
  timeout?: number;
}

export class Client {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly timeout: number;
  readonly agents: AgentsResource;
  readonly vault: VaultResource;
  readonly personas: PersonasResource;
  readonly domains: DomainsResource;

  constructor(opts: ClientOptions = {}) {
    this.apiKey =
      opts.apiKey ??
      process.env["AGENTCOMMS_API_KEY"] ??
      (() => {
        throw new Error("AgentComms API key required — pass apiKey or set AGENTCOMMS_API_KEY");
      })();
    this.baseUrl = (
      opts.baseUrl ??
      process.env["AGENTCOMMS_BASE_URL"] ??
      "https://api.agentcomms.dev/v1"
    ).replace(/\/$/, "");
    this.timeout = opts.timeout ?? 30_000;

    this.agents = new AgentsResource(this);
    this.vault = new VaultResource(this);
    this.personas = new PersonasResource(this);
    this.domains = new DomainsResource(this);
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    try {
      const resp = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          "Content-Type": "application/json",
          "User-Agent": "@agentcomms/client/1.0.0",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      if (!resp.ok) throw await AgentCommsError.fromResponse(resp);
      if (resp.status === 204) return undefined as T;
      return (await resp.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }
}
