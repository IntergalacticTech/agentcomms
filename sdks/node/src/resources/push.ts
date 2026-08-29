// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
import type { Client } from "../client.js";

export class PushResource {
  constructor(private client: Client, private agentId: string) {}

  async registerDevice(params: { platform: string; token: string; metadata?: Record<string, unknown> }): Promise<unknown> {
    return this.client.request("POST", `/agents/${this.agentId}/push/devices`, params);
  }

  async send(params: {
    device_id?: string;
    body_text?: string;
    title?: string;
    body?: string;
    device_ids?: string[];
    badge?: number;
    data?: Record<string, unknown>;
  }): Promise<unknown> {
    const deviceId = params.device_id ?? params.device_ids?.[0];
    if (!deviceId) throw new Error("device_id is required");
    return this.client.request("POST", `/agents/${this.agentId}/push/send`, {
      device_id: deviceId,
      body_text: params.body_text ?? params.body,
      title: params.title,
      badge: params.badge,
      data: params.data,
    });
  }
}
