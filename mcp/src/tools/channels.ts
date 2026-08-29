// SPDX-License-Identifier: Apache-2.0
import { apiRequest } from "../client.js";
import type { Tool } from "./agents.js";

export const channelTools: Tool[] = [
  {
    name: "channels_list",
    description: "List all communication channels assigned to an agent.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
      },
      required: ["agent_id"],
    },
    handler: async (args) => {
      return apiRequest("GET", `/agents/${args.agent_id}/channels`);
    },
  },
  {
    name: "channel_create",
    description: "Provision or bridge a new channel for an agent.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        channel: {
          type: "string",
          pattern: "^[a-z][a-z0-9_-]{0,62}$",
          description: "Built-in channel or external adapter slug to provision or bridge",
        },
        mode: {
          type: "string",
          enum: ["provision", "bridge"],
          description: "Use provision for owned identities, bridge for OAuth/imported identities",
        },
        config: {
          type: "object",
          description: "Channel-specific config, such as email local_part/domain",
        },
      },
      required: ["agent_id", "channel"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = {
        channel: args.channel,
        mode: args.mode ?? "provision",
        config: args.config ?? {},
      };
      return apiRequest("POST", `/agents/${args.agent_id}/channels`, body);
    },
  },
  {
    name: "channel_delete",
    description: "Delete a channel from an agent.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        channel_id: { type: "string", description: "The channel ID to delete" },
      },
      required: ["agent_id", "channel_id"],
    },
    handler: async (args) => {
      return apiRequest("DELETE", `/agents/${args.agent_id}/channels/${args.channel_id}`);
    },
  },
];
