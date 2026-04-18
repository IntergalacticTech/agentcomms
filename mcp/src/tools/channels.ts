// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { apiRequest } from "../client.js";
import type { Tool } from "./agents.js";

export const channelTools: Tool[] = [
  {
    name: "channels_list",
    description: "List all channels (email addresses, phone numbers) assigned to an agent.",
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
    description: "Provision a new channel (e.g. an email address) for an agent.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        type: {
          type: "string",
          enum: ["email", "sms"],
          description: "Channel type to provision",
        },
        address: {
          type: "string",
          description: "Preferred address or prefix (optional; auto-generated if omitted)",
        },
      },
      required: ["agent_id"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = {};
      if (args.type) body.type = args.type;
      if (args.address) body.address = args.address;
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
