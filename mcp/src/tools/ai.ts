// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { apiRequest } from "../client.js";
import type { Tool } from "./agents.js";

export const aiTools: Tool[] = [
  {
    name: "ai_categorize",
    description:
      "Use AI to categorize a message against a set of labels. Returns the best matching label and confidence.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        message_id: { type: "string", description: "The message ID to categorize" },
        labels: {
          type: "array",
          items: { type: "string" },
          description: "Labels to classify against (uses defaults if omitted)",
        },
      },
      required: ["agent_id", "message_id"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = { message_id: args.message_id };
      if (args.labels) body.labels = args.labels;
      return apiRequest("POST", `/agents/${args.agent_id}/ai/categorize`, body);
    },
  },
  {
    name: "ai_extract",
    description:
      "Use AI to extract structured data from a message body according to a JSON schema.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        message_id: { type: "string", description: "The message ID to extract from" },
        schema: {
          type: "object",
          description: "JSON Schema describing the data to extract",
        },
      },
      required: ["agent_id", "message_id", "schema"],
    },
    handler: async (args) => {
      return apiRequest("POST", `/agents/${args.agent_id}/ai/extract`, {
        message_id: args.message_id,
        schema: args.schema,
      });
    },
  },
  {
    name: "ai_summarize",
    description:
      "Use AI to summarize a message or an entire thread. Provide either message_id or thread_key.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        message_id: { type: "string", description: "Single message to summarize" },
        thread_key: { type: "string", description: "Thread key to summarize the entire thread" },
        length: {
          type: "string",
          enum: ["short", "medium", "long"],
          description: "Desired summary length (default: medium)",
        },
      },
      required: ["agent_id"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = {};
      if (args.message_id) body.message_id = args.message_id;
      if (args.thread_key) body.thread_key = args.thread_key;
      if (args.length) body.length = args.length;
      return apiRequest("POST", `/agents/${args.agent_id}/ai/summarize`, body);
    },
  },
  {
    name: "ai_search",
    description:
      "Semantic search across an agent's messages using natural language.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        query: { type: "string", description: "Natural language search query" },
        channel: { type: "string", description: "Restrict search to a channel ID" },
        limit: { type: "number", description: "Max results to return (default 10)" },
        since: { type: "string", description: "ISO 8601 timestamp lower bound" },
      },
      required: ["agent_id", "query"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = { query: args.query };
      if (args.channel) body.channel = args.channel;
      if (args.limit) body.limit = args.limit;
      if (args.since) body.since = args.since;
      return apiRequest("POST", `/agents/${args.agent_id}/ai/search`, body);
    },
  },
];
