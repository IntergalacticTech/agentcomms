// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import type { Client } from "../client.js";
import type { Message, PaginatedMessages } from "../types.js";

export interface ListMessagesParams {
  since?: string;
  channels?: string[];
  limit?: number;
  cursor?: string;
}

export interface SendMessageParams {
  to: string | Record<string, unknown>;
  body?: string;
  body_text?: string;
  body_html?: string;
  subject?: string;
  channel?: string;
  thread_key?: string;
}

export class MessagesResource {
  constructor(private client: Client, private agentId: string) {}

  private path(suffix = ""): string {
    return `/agents/${this.agentId}/messages${suffix}`;
  }

  async list(params: ListMessagesParams = {}): Promise<Message[]> {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.since) qs.set("since", params.since);
    if (params.channels?.length) qs.set("channels", params.channels.join(","));
    if (params.cursor) qs.set("cursor", params.cursor);
    const query = qs.toString() ? `?${qs}` : "";
    const data = await this.client.request<PaginatedMessages>("GET", `${this.path()}${query}`);
    return data.messages ?? [];
  }

  async listPage(params: ListMessagesParams = {}): Promise<PaginatedMessages> {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.since) qs.set("since", params.since);
    if (params.channels?.length) qs.set("channels", params.channels.join(","));
    if (params.cursor) qs.set("cursor", params.cursor);
    const query = qs.toString() ? `?${qs}` : "";
    return this.client.request<PaginatedMessages>("GET", `${this.path()}${query}`);
  }

  async get(messageId: string): Promise<Message> {
    return this.client.request<Message>("GET", this.path(`/${messageId}`));
  }

  async send(params: SendMessageParams): Promise<{ message_id: string }> {
    return this.client.request("POST", this.path(), params);
  }

  async reply(messageId: string, body: { body: string; body_html?: string }): Promise<{ message_id: string }> {
    return this.client.request("POST", this.path(`/${messageId}/reply`), body);
  }

  async markRead(messageId: string): Promise<void> {
    await this.client.request("POST", this.path(`/${messageId}/read`));
  }

  async wait(params: { timeout?: number; sender?: string; subject_contains?: string; channels?: string[] } = {}): Promise<Message> {
    return this.client.request<Message>("POST", `/agents/${this.agentId}/wait`, {
      timeout_sec: params.timeout,
      from: params.sender,
      subject_contains: params.subject_contains,
      channels: params.channels,
    });
  }

  async extractOtp(params: { timeout?: number; sender?: string } = {}): Promise<{ code: string; message_id: string }> {
    return this.client.request("POST", `/agents/${this.agentId}/extract-otp`, {
      max_age_sec: params.timeout,
      from: params.sender,
    });
  }
}
