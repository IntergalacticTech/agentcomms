// SPDX-License-Identifier: Apache-2.0
import { apiRequest } from "../client.js";
import type { Tool } from "./agents.js";

export const personaTools: Tool[] = [
  {
    name: "persona_list",
    description: "List all synthetic personas in the organization.",
    inputSchema: {
      type: "object",
      properties: {},
    },
    handler: async (_args) => {
      return apiRequest("GET", "/personas");
    },
  },
  {
    name: "persona_create",
    description:
      "Create a synthetic persona. Pass generate=true to have the API auto-fill realistic demographic data.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Full name for the persona" },
        address: { type: "string", description: "Street address" },
        dob: { type: "string", description: "Date of birth (YYYY-MM-DD)" },
        phone: { type: "string", description: "Phone number" },
        email: { type: "string", description: "Email address" },
        metadata: { type: "object", description: "Arbitrary metadata" },
        generate: {
          type: "boolean",
          description: "Auto-generate realistic demographic data for any omitted fields",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = { name: args.name };
      if (args.address) body.address = args.address;
      if (args.dob) body.dob = args.dob;
      if (args.phone) body.phone = args.phone;
      if (args.email) body.email = args.email;
      if (args.metadata) body.metadata = args.metadata;
      if (args.generate !== undefined) body.generate = args.generate;
      return apiRequest("POST", "/personas", body);
    },
  },
  {
    name: "persona_associate",
    description: "Associate an existing persona with an agent.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        persona_id: { type: "string", description: "The persona ID to associate" },
      },
      required: ["agent_id", "persona_id"],
    },
    handler: async (args) => {
      return apiRequest("POST", `/agents/${args.agent_id}/personas`, {
        persona_id: args.persona_id,
      });
    },
  },
  {
    name: "persona_delete",
    description: "Delete a persona permanently.",
    inputSchema: {
      type: "object",
      properties: {
        persona_id: { type: "string", description: "The persona ID to delete" },
      },
      required: ["persona_id"],
    },
    handler: async (args) => {
      return apiRequest("DELETE", `/personas/${args.persona_id}`);
    },
  },
];
