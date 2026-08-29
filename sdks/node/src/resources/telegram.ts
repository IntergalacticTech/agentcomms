// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import type { Client } from "../client.js";

export class TelegramResource {
  constructor(private client: Client, private agentId: string) {}

  async chats(): Promise<unknown[]> {
    const data = await this.client.request<{ chats: unknown[] }>(
      "GET",
      `/agents/${this.agentId}/telegram/chats`,
    );
    return data.chats ?? [];
  }

  async chatMessages(chatId: string | number, params: { limit?: number } = {}): Promise<unknown[]> {
    const qs = params.limit ? `?limit=${params.limit}` : "";
    const data = await this.client.request<{ messages: unknown[] }>(
      "GET",
      `/agents/${this.agentId}/telegram/chats/${chatId}/messages${qs}`,
    );
    return data.messages ?? [];
  }

  async send(chatId: string | number, params: { body: string }): Promise<unknown> {
    return this.client.request(
      "POST",
      `/agents/${this.agentId}/telegram/chats/${chatId}/messages`,
      { text: params.body },
    );
  }
}
