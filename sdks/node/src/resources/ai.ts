// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import type { Client } from "../client.js";

export class AiResource {
  constructor(private client: Client, private agentId: string) {}

  private path(op: string): string {
    return `/agents/${this.agentId}/ai/${op}`;
  }

  async categorize(params: { message_id: string; categories?: string[] }): Promise<Record<string, unknown>> {
    return this.client.request("POST", this.path("categorize"), params);
  }

  async extract(params: { message_id: string; fields: string[] }): Promise<Record<string, unknown>> {
    return this.client.request("POST", this.path("extract"), params);
  }

  async summarize(params: { message_id: string; max_length?: number }): Promise<{ summary: string }> {
    return this.client.request("POST", this.path("summarize"), params);
  }

  async search(params: { query: string; limit?: number }): Promise<{ results: unknown[] }> {
    return this.client.request("POST", this.path("search"), params);
  }
}
