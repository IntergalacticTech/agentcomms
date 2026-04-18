// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import type { Client } from "../client.js";
import type { Thread } from "../types.js";

export class ThreadsResource {
  constructor(private client: Client, private agentId: string) {}

  async list(params: { channel?: string; limit?: number } = {}): Promise<Thread[]> {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.channel) qs.set("channel", params.channel);
    const query = qs.toString() ? `?${qs}` : "";
    const data = await this.client.request<{ threads: Thread[] }>(
      "GET",
      `/agents/${this.agentId}/threads${query}`,
    );
    return data.threads ?? [];
  }

  async get(threadId: string): Promise<Thread> {
    return this.client.request<Thread>("GET", `/agents/${this.agentId}/threads/${threadId}`);
  }
}
