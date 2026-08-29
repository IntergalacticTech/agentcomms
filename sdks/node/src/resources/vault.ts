// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import type { Client } from "../client.js";
import type { VaultItem } from "../types.js";

export class VaultResource {
  constructor(private client: Client) {}

  async create(params: {
    label?: string;
    name?: string;
    value?: string;
    seed?: string;
    type?: string;
    tags?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
  }): Promise<VaultItem> {
    const label = params.label ?? params.name;
    if (!label) throw new Error("label is required");
    const body: Record<string, unknown> = {
      label,
      type: params.type ?? "secret",
    };
    if (body.type === "totp") body.seed = params.seed ?? params.value;
    else if (params.value !== undefined) body.value = params.value;
    if (params.tags) body.tags = params.tags;
    else if (params.metadata) body.tags = params.metadata;
    return this.client.request<VaultItem>("POST", "/vault", body);
  }

  async list(): Promise<VaultItem[]> {
    const data = await this.client.request<{ items: VaultItem[] }>("GET", "/vault");
    return data.items ?? [];
  }

  async get(vaultId: string): Promise<VaultItem> {
    return this.client.request<VaultItem>("GET", `/vault/${vaultId}`);
  }

  async getTotp(vaultId: string): Promise<{ code: string; valid_until: number }> {
    return this.client.request("GET", `/vault/${vaultId}/totp`);
  }

  async delete(vaultId: string): Promise<void> {
    await this.client.request("DELETE", `/vault/${vaultId}`);
  }
}
