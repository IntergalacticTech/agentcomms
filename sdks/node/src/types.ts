// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
/**
 * TypeScript interfaces mirroring AgentComms API response shapes.
 */

export interface ChannelDetails {
  address?: string;
  phone_e164?: string;
  bot_username?: string;
  oauth_url?: string;
  status?: string;
  [key: string]: unknown;
}

export interface Channel {
  channel_id: string;
  channel: string;
  agent_id: string;
  mode?: string;
  status?: string;
  details?: ChannelDetails;
  created_at?: string;
  updated_at?: string;
}

export interface Agent {
  agent_id: string;
  org_id?: string;
  name: string;
  metadata?: Record<string, unknown>;
  channels?: Channel[];
  created_at?: string;
  updated_at?: string;
}

/** Response from POST /agents — includes a one-time api_key. */
export interface AgentCreateResponse extends Agent {
  api_key?: string;
}

export interface Recipient {
  address?: string;
  display_name?: string;
  platform_user_id?: string;
}

export interface Message {
  message_id: string;
  agent_id: string;
  channel_id?: string;
  channel?: string;
  direction?: "inbound" | "outbound";
  status?: string;
  from?: Recipient;
  to?: Recipient[];
  subject?: string;
  body_text?: string;
  body_html?: string;
  thread_key?: string;
  is_dm?: boolean;
  received_at?: string;
  created_at?: string;
  channel_native?: Record<string, unknown>;
}

export interface Thread {
  thread_key: string;
  agent_id: string;
  channel?: string;
  message_count?: number;
  last_message_at?: string;
  created_at?: string;
}

export interface Draft {
  draft_id: string;
  agent_id: string;
  channel?: string;
  to?: string;
  subject?: string;
  body_text?: string;
  body_html?: string;
  created_at?: string;
  updated_at?: string;
}

export interface Webhook {
  webhook_id: string;
  agent_id: string;
  url: string;
  events: string[];
  channels?: string[];
  created_at?: string;
}

export interface VaultItem {
  vault_id: string;
  org_id: string;
  name: string;
  type: string;
  created_at?: string;
}

export interface Persona {
  persona_id: string;
  org_id: string;
  name: string;
  email?: string;
  phone?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}

export interface Domain {
  domain_id: string;
  org_id: string;
  domain: string;
  status?: string;
  dkim_verified?: boolean;
  created_at?: string;
}

export interface PaginatedMessages {
  messages: Message[];
  next_cursor?: string;
}

export interface AgentsList {
  agents: Agent[];
}
