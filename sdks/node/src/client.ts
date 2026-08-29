// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import { AgentsResource } from "./resources/agents.js";
import { VaultResource } from "./resources/vault.js";
import { PersonasResource } from "./resources/personas.js";
import { DomainsResource } from "./resources/domains.js";
import { AgentCommsError } from "./errors.js";

export interface ClientOptions {
  apiKey?: string;
  baseUrl?: string;
  timeout?: number;
  /** Max retries for idempotent requests on 429/5xx. Default 3. */
  maxRetries?: number;
  /** Base backoff in ms for exponential retry delay. Default 500. */
  retryBaseMs?: number;
}

// HTTP methods that are safe to retry (idempotent). POST/PATCH are excluded.
const IDEMPOTENT_METHODS = new Set(["GET", "HEAD", "PUT", "DELETE", "OPTIONS"]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class Client {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly timeout: number;
  readonly maxRetries: number;
  readonly retryBaseMs: number;
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
    this.maxRetries = opts.maxRetries ?? 3;
    this.retryBaseMs = opts.retryBaseMs ?? 500;

    this.agents = new AgentsResource(this);
    this.vault = new VaultResource(this);
    this.personas = new PersonasResource(this);
    this.domains = new DomainsResource(this);
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    // Idempotent requests are retried on 429/5xx with bounded exponential
    // backoff, honoring a Retry-After header when present.
    const retryable = IDEMPOTENT_METHODS.has(method.toUpperCase());
    let attempt = 0;
    for (;;) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeout);
      let resp: Response;
      try {
        resp = await fetch(`${this.baseUrl}${path}`, {
          method,
          headers: {
            Authorization: `Bearer ${this.apiKey}`,
            "Content-Type": "application/json",
            "User-Agent": "@agentcomms/client/1.0.0",
          },
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timer);
      }
      if (!resp.ok) {
        if (
          retryable &&
          attempt < this.maxRetries &&
          (resp.status === 429 || resp.status >= 500)
        ) {
          await sleep(this.retryDelay(resp, attempt));
          attempt++;
          continue;
        }
        throw await AgentCommsError.fromResponse(resp);
      }
      if (resp.status === 204) return undefined as T;
      return (await resp.json()) as T;
    }
  }

  /** Delay (ms) before the next retry, honoring Retry-After when present. */
  private retryDelay(resp: Response, attempt: number): number {
    const retryAfter = resp.headers?.get?.("Retry-After");
    if (retryAfter) {
      const seconds = Number(retryAfter);
      if (!Number.isNaN(seconds)) return Math.max(0, seconds * 1000);
      const when = Date.parse(retryAfter);
      if (!Number.isNaN(when)) return Math.max(0, when - Date.now());
    }
    return this.retryBaseMs * 2 ** attempt;
  }
}
