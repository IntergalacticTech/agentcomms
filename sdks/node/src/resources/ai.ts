// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import type { Client } from "../client.js";

export class AiResource {
  constructor(private client: Client, private agentId: string) {}

  private path(op: string): string {
    return `/agents/${this.agentId}/ai/${op}`;
  }

  async categorize(params: { message_id: string; labels?: string[]; categories?: string[] }): Promise<Record<string, unknown>> {
    return this.client.request("POST", this.path("categorize"), {
      message_id: params.message_id,
      labels: params.labels ?? params.categories,
    });
  }

  async extract(params: { message_id: string; schema?: Record<string, unknown>; fields?: string[] }): Promise<Record<string, unknown>> {
    const schema =
      params.schema ??
      (params.fields
        ? {
            type: "object",
            properties: Object.fromEntries(params.fields.map((field) => [field, { type: "string" }])),
          }
        : undefined);
    if (!schema) throw new Error("schema is required");
    return this.client.request("POST", this.path("extract"), {
      message_id: params.message_id,
      schema,
    });
  }

  async summarize(params: { text?: string; message_id?: string; thread_key?: string; length?: "short" | "long"; max_length?: number }): Promise<{ summary: string }> {
    return this.client.request("POST", this.path("summarize"), {
      text: params.text,
      message_id: params.message_id,
      thread_key: params.thread_key,
      length: params.length ?? (params.max_length && params.max_length > 500 ? "long" : undefined),
    });
  }

  async search(params: { query: string; limit?: number }): Promise<{ results: unknown[] }> {
    return this.client.request("POST", this.path("search"), params);
  }
}
