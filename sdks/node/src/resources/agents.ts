// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import type { Client } from "../client.js";
import type { Agent, AgentCreateResponse, AgentsList } from "../types.js";
import { MessagesResource } from "./messages.js";
import { ChannelsResource } from "./channels.js";
import { ThreadsResource } from "./threads.js";
import { DraftsResource } from "./drafts.js";
import { WebhooksResource } from "./webhooks.js";
import { AiResource } from "./ai.js";
import { SlackResource } from "./slack.js";
import { TelegramResource } from "./telegram.js";
import { PushResource } from "./push.js";

export class AgentContext {
  readonly messages: MessagesResource;
  readonly channels: ChannelsResource;
  readonly threads: ThreadsResource;
  readonly drafts: DraftsResource;
  readonly webhooks: WebhooksResource;
  readonly ai: AiResource;
  readonly slack: SlackResource;
  readonly telegram: TelegramResource;
  readonly push: PushResource;

  constructor(private client: Client, readonly agentId: string) {
    this.messages = new MessagesResource(client, agentId);
    this.channels = new ChannelsResource(client, agentId);
    this.threads = new ThreadsResource(client, agentId);
    this.drafts = new DraftsResource(client, agentId);
    this.webhooks = new WebhooksResource(client, agentId);
    this.ai = new AiResource(client, agentId);
    this.slack = new SlackResource(client, agentId);
    this.telegram = new TelegramResource(client, agentId);
    this.push = new PushResource(client, agentId);
  }
}

export class AgentsResource {
  constructor(private client: Client) {}

  /** Get per-agent sub-resources: `client.agents.agent("agt_...").messages.list()` */
  agent(id: string): AgentContext {
    return new AgentContext(this.client, id);
  }

  async create(params: {
    name: string;
    metadata?: Record<string, unknown>;
    provision?: Record<string, unknown>;
    bridge?: Record<string, unknown>;
  }): Promise<AgentCreateResponse> {
    return this.client.request<AgentCreateResponse>("POST", "/agents", params);
  }

  async get(id: string): Promise<Agent> {
    return this.client.request<Agent>("GET", `/agents/${id}`);
  }

  async list(): Promise<Agent[]> {
    const data = await this.client.request<AgentsList>("GET", "/agents");
    return data.agents ?? [];
  }

  /**
   * Update mutable fields on an agent. The API implements agent update as
   * HTTP `PUT /agents/{id}`, so this issues a `PUT` even though the method
   * is named `patch` (kept stable for backwards compatibility).
   */
  async patch(id: string, updates: Partial<Pick<Agent, "name" | "metadata">>): Promise<Agent> {
    return this.client.request<Agent>("PUT", `/agents/${id}`, updates);
  }

  /** Alias for {@link patch} — the natural name for a PUT-based update. */
  async update(id: string, updates: Partial<Pick<Agent, "name" | "metadata">>): Promise<Agent> {
    return this.patch(id, updates);
  }

  async delete(id: string): Promise<void> {
    await this.client.request("DELETE", `/agents/${id}`);
  }

  async provision(
    id: string,
    params: { provision: Record<string, unknown>; bridge?: Record<string, unknown> },
  ): Promise<AgentCreateResponse> {
    return this.client.request<AgentCreateResponse>("POST", `/agents/${id}/provision`, params);
  }
}
