// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
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
