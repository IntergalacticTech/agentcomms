// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import type { Client } from "../client.js";
import type { Channel } from "../types.js";

export class ChannelsResource {
  constructor(private client: Client, private agentId: string) {}

  private path(suffix = ""): string {
    return `/agents/${this.agentId}/channels${suffix}`;
  }

  async list(): Promise<Channel[]> {
    const data = await this.client.request<{ channels: Channel[] }>("GET", this.path());
    return data.channels ?? [];
  }

  async get(channelId: string): Promise<Channel> {
    return this.client.request<Channel>("GET", this.path(`/${channelId}`));
  }

  async create(params: { channel: string; mode?: string; config?: Record<string, unknown> }): Promise<Channel> {
    return this.client.request<Channel>("POST", this.path(), params);
  }

  async patch(channelId: string, updates: Partial<{ status: string; config: Record<string, unknown> }>): Promise<Channel> {
    return this.client.request<Channel>("PATCH", this.path(`/${channelId}`), updates);
  }

  async delete(channelId: string): Promise<void> {
    await this.client.request("DELETE", this.path(`/${channelId}`));
  }
}
