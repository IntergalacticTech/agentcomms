// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import type { Client } from "../client.js";
import type { VaultItem } from "../types.js";

export class VaultResource {
  constructor(private client: Client) {}

  async create(params: { name: string; value: string; type?: string; metadata?: Record<string, unknown> }): Promise<VaultItem> {
    return this.client.request<VaultItem>("POST", "/vault", params);
  }

  async list(): Promise<VaultItem[]> {
    const data = await this.client.request<{ items: VaultItem[] }>("GET", "/vault");
    return data.items ?? [];
  }

  async get(vaultId: string): Promise<VaultItem> {
    return this.client.request<VaultItem>("GET", `/vault/${vaultId}`);
  }

  async getTotp(vaultId: string): Promise<{ code: string; expires_in: number }> {
    return this.client.request("POST", `/vault/${vaultId}/totp`);
  }

  async delete(vaultId: string): Promise<void> {
    await this.client.request("DELETE", `/vault/${vaultId}`);
  }
}
