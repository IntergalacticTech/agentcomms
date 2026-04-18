// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
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
