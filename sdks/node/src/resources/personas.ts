// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
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
