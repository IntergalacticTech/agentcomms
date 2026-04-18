// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { apiRequest } from "../client.js";
import type { Tool } from "./agents.js";

export const vaultTools: Tool[] = [
  {
    name: "vault_list",
    description: "List all secrets/credentials stored in the vault.",
    inputSchema: {
      type: "object",
      properties: {
        tags: {
          type: "array",
          items: { type: "string" },
          description: "Filter by tags",
        },
      },
    },
    handler: async (args) => {
      const params = new URLSearchParams();
      if (Array.isArray(args.tags)) {
        (args.tags as string[]).forEach((t) => params.append("tags", t));
      }
      const qs = params.toString();
      return apiRequest("GET", `/vault${qs ? `?${qs}` : ""}`);
    },
  },
  {
    name: "vault_create",
    description: "Store a new secret or credential in the vault.",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          enum: ["totp", "password", "api_key", "note"],
          description: "Secret type",
        },
        label: { type: "string", description: "Human-readable label" },
        seed: { type: "string", description: "TOTP seed (base32 encoded, for type=totp)" },
        value: { type: "string", description: "Secret value (for password/api_key/note)" },
        tags: {
          type: "array",
          items: { type: "string" },
          description: "Optional tags for organization",
        },
      },
      required: ["type", "label"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = {
        type: args.type,
        label: args.label,
      };
      if (args.seed) body.seed = args.seed;
      if (args.value) body.value = args.value;
      if (args.tags) body.tags = args.tags;
      return apiRequest("POST", "/vault", body);
    },
  },
  {
    name: "vault_get",
    description: "Retrieve a vault entry by ID.",
    inputSchema: {
      type: "object",
      properties: {
        vault_id: { type: "string", description: "The vault entry ID" },
      },
      required: ["vault_id"],
    },
    handler: async (args) => {
      return apiRequest("GET", `/vault/${args.vault_id}`);
    },
  },
  {
    name: "vault_get_totp",
    description: "Get the current TOTP code for a TOTP vault entry. Returns {code, valid_until}.",
    inputSchema: {
      type: "object",
      properties: {
        vault_id: { type: "string", description: "The vault entry ID (must be type=totp)" },
      },
      required: ["vault_id"],
    },
    handler: async (args) => {
      return apiRequest("GET", `/vault/${args.vault_id}/totp`);
    },
  },
  {
    name: "vault_delete",
    description: "Delete a vault entry permanently.",
    inputSchema: {
      type: "object",
      properties: {
        vault_id: { type: "string", description: "The vault entry ID to delete" },
      },
      required: ["vault_id"],
    },
    handler: async (args) => {
      return apiRequest("DELETE", `/vault/${args.vault_id}`);
    },
  },
];
