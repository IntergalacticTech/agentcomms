// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import type { Client } from "../client.js";

export class SlackWorkspaceChannels {
  constructor(private client: Client, private agentId: string, private teamId: string) {}

  async list(): Promise<unknown[]> {
    const data = await this.client.request<{ channels: unknown[] }>(
      "GET",
      `/agents/${this.agentId}/slack/workspaces/${this.teamId}/channels`,
    );
    return data.channels ?? [];
  }

  async messages(channelId: string, params: { limit?: number } = {}): Promise<unknown[]> {
    const qs = params.limit ? `?limit=${params.limit}` : "";
    const data = await this.client.request<{ messages: unknown[] }>(
      "GET",
      `/agents/${this.agentId}/slack/workspaces/${this.teamId}/channels/${channelId}/messages${qs}`,
    );
    return data.messages ?? [];
  }

  async post(channelId: string, params: { body: string; blocks?: unknown }): Promise<unknown> {
    return this.client.request(
      "POST",
      `/agents/${this.agentId}/slack/workspaces/${this.teamId}/channels/${channelId}/messages`,
      { text: params.body, blocks: params.blocks },
    );
  }
}

export class SlackWorkspace {
  readonly channels: SlackWorkspaceChannels;

  constructor(private client: Client, private agentId: string, readonly teamId: string) {
    this.channels = new SlackWorkspaceChannels(client, agentId, teamId);
  }

  async dm(userId: string, params: { body: string }): Promise<unknown> {
    return this.client.request(
      "POST",
      `/agents/${this.agentId}/slack/workspaces/${this.teamId}/users/${userId}/messages`,
      { text: params.body },
    );
  }
}

export class SlackResource {
  constructor(private client: Client, private agentId: string) {}

  async workspaces(): Promise<unknown[]> {
    const data = await this.client.request<{ workspaces: unknown[] }>(
      "GET",
      `/agents/${this.agentId}/slack/workspaces`,
    );
    return data.workspaces ?? [];
  }

  workspace(teamId: string): SlackWorkspace {
    return new SlackWorkspace(this.client, this.agentId, teamId);
  }
}
