// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import type { Client } from "../client.js";
import type { Domain } from "../types.js";

export class DomainsResource {
  constructor(private client: Client) {}

  async list(): Promise<Domain[]> {
    const data = await this.client.request<{ domains: Domain[] }>("GET", "/domains");
    return data.domains ?? [];
  }

  async get(domainId: string): Promise<Domain> {
    return this.client.request<Domain>("GET", `/domains/${domainId}`);
  }

  async create(params: { domain: string; metadata?: Record<string, unknown> }): Promise<Domain> {
    return this.client.request<Domain>("POST", "/domains", params);
  }

  async delete(domainId: string): Promise<void> {
    await this.client.request("DELETE", `/domains/${domainId}`);
  }
}
