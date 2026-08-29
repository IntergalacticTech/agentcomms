// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Victory (Intergalactic Tech).
// Licensed under the Apache License, Version 2.0. See LICENSE for details.
/**
 * @agentcomms/client — Official Node.js SDK for AgentComms.
 *
 * @example
 * ```ts
 * import { Client } from "@agentcomms/client";
 * const client = new Client({ apiKey: "ak_live_..." });
 * const agents = await client.agents.list();
 * const msgs = await client.agents.agent(agents[0].agent_id).messages.list();
 * ```
 */
export { Client } from "./client.js";
export type { ClientOptions } from "./client.js";
export {
  AgentCommsError,
  NotFoundError,
  AuthenticationError,
  RateLimitError,
  ServerError,
} from "./errors.js";
export type {
  Agent,
  AgentCreateResponse,
  Channel,
  ChannelDetails,
  Message,
  Recipient,
  Thread,
  Draft,
  Webhook,
  VaultItem,
  Persona,
  Domain,
  PaginatedMessages,
  AgentsList,
} from "./types.js";
