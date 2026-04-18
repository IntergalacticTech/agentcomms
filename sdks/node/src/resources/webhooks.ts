// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import type { Client } from "../client.js";
import type { Webhook } from "../types.js";

export class WebhooksResource {
  constructor(private client: Client, private agentId: string) {}

  private path(suffix = ""): string {
    return `/agents/${this.agentId}/webhooks${suffix}`;
  }

  async list(): Promise<Webhook[]> {
    const data = await this.client.request<{ webhooks: Webhook[] }>("GET", this.path());
    return data.webhooks ?? [];
  }

  async get(webhookId: string): Promise<Webhook> {
    return this.client.request<Webhook>("GET", this.path(`/${webhookId}`));
  }

  async create(params: { url: string; events: string[]; channels?: string[]; secret?: string }): Promise<Webhook> {
    return this.client.request<Webhook>("POST", this.path(), params);
  }

  async patch(webhookId: string, updates: Partial<{ url: string; events: string[]; channels: string[] }>): Promise<Webhook> {
    return this.client.request<Webhook>("PATCH", this.path(`/${webhookId}`), updates);
  }

  async delete(webhookId: string): Promise<void> {
    await this.client.request("DELETE", this.path(`/${webhookId}`));
  }
}
