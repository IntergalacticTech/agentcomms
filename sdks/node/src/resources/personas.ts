// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import type { Client } from "../client.js";
import type { Persona } from "../types.js";

export class PersonasResource {
  constructor(private client: Client) {}

  async create(params: { name: string; email?: string; phone?: string; metadata?: Record<string, unknown> }): Promise<Persona> {
    return this.client.request<Persona>("POST", "/personas", params);
  }

  async list(): Promise<Persona[]> {
    const data = await this.client.request<{ personas: Persona[] }>("GET", "/personas");
    return data.personas ?? [];
  }

  async get(personaId: string): Promise<Persona> {
    return this.client.request<Persona>("GET", `/personas/${personaId}`);
  }

  async delete(personaId: string): Promise<void> {
    await this.client.request("DELETE", `/personas/${personaId}`);
  }
}
