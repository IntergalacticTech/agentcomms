// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
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

  async create(params: { domain_name?: string; domain?: string; metadata?: Record<string, unknown> }): Promise<Domain> {
    return this.client.request<Domain>("POST", "/domains", {
      ...params,
      domain_name: params.domain_name ?? params.domain,
      domain: undefined,
    });
  }

  async delete(domainId: string): Promise<void> {
    await this.client.request("DELETE", `/domains/${domainId}`);
  }
}
