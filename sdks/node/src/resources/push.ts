// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
import type { Client } from "../client.js";

export class PushResource {
  constructor(private client: Client, private agentId: string) {}

  async registerDevice(params: { platform: string; token: string; metadata?: Record<string, unknown> }): Promise<unknown> {
    return this.client.request("POST", `/agents/${this.agentId}/push/devices`, params);
  }

  async send(params: { title: string; body: string; device_ids?: string[]; data?: Record<string, unknown> }): Promise<unknown> {
    return this.client.request("POST", `/agents/${this.agentId}/push/send`, params);
  }
}
