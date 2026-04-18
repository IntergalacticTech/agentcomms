// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { apiRequest } from "../client.js";

export interface Tool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  handler: (args: Record<string, unknown>) => Promise<unknown>;
}

export const agentTools: Tool[] = [
  {
    name: "agent_list",
    description: "List all agents in the organization. Returns an array of {agent_id, name}.",
    inputSchema: {
      type: "object",
      properties: {},
    },
    handler: async (_args) => {
      return apiRequest("GET", "/agents");
    },
  },
  {
    name: "agent_create",
    description: "Create a new agent with a name and optional metadata, provisioning, or bridge config.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Display name for the agent" },
        metadata: { type: "object", description: "Optional arbitrary metadata key/value pairs" },
        provision: {
          type: "object",
          description: "Optional provisioning config (e.g. {email: true, sms: true})",
        },
        bridge: {
          type: "object",
          description: "Optional bridge config for outbound channels",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = { name: args.name };
      if (args.metadata) body.metadata = args.metadata;
      if (args.provision) body.provision = args.provision;
      if (args.bridge) body.bridge = args.bridge;
      return apiRequest("POST", "/agents", body);
    },
  },
  {
    name: "agent_get",
    description: "Get full details for a single agent by ID.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
      },
      required: ["agent_id"],
    },
    handler: async (args) => {
      return apiRequest("GET", `/agents/${args.agent_id}`);
    },
  },
  {
    name: "agent_delete",
    description: "Delete an agent and all associated channels.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID to delete" },
      },
      required: ["agent_id"],
    },
    handler: async (args) => {
      return apiRequest("DELETE", `/agents/${args.agent_id}`);
    },
  },
];
