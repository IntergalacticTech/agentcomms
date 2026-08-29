// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import type { Client } from "../client.js";
import type { Draft } from "../types.js";

export class DraftsResource {
  constructor(private client: Client, private agentId: string) {}

  private path(suffix = ""): string {
    return `/agents/${this.agentId}/drafts${suffix}`;
  }

  async list(): Promise<Draft[]> {
    const data = await this.client.request<{ drafts: Draft[] }>("GET", this.path());
    return data.drafts ?? [];
  }

  async get(draftId: string): Promise<Draft> {
    return this.client.request<Draft>("GET", this.path(`/${draftId}`));
  }

  async create(params: { to?: string; subject?: string; body_text?: string; body_html?: string; channel?: string }): Promise<Draft> {
    return this.client.request<Draft>("POST", this.path(), params);
  }

  async patch(draftId: string, updates: Partial<Draft>): Promise<Draft> {
    return this.client.request<Draft>("PATCH", this.path(`/${draftId}`), updates);
  }

  async delete(draftId: string): Promise<void> {
    await this.client.request("DELETE", this.path(`/${draftId}`));
  }
}
