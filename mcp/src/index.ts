#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { API_KEY } from "./config.js";
import { agentTools } from "./tools/agents.js";
import { messageTools } from "./tools/messages.js";
import { channelTools } from "./tools/channels.js";
import { vaultTools } from "./tools/vault.js";
import { personaTools } from "./tools/personas.js";
import { aiTools } from "./tools/ai.js";

if (!API_KEY) {
  console.error("AGENTCOMMS_API_KEY environment variable is required");
  process.exit(1);
}

const ALL_TOOLS = [
  ...agentTools,
  ...messageTools,
  ...channelTools,
  ...vaultTools,
  ...personaTools,
  ...aiTools,
];

const server = new Server(
  { name: "agentcomms-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: ALL_TOOLS.map((t) => ({
    name: t.name,
    description: t.description,
    inputSchema: t.inputSchema,
  })),
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const tool = ALL_TOOLS.find((t) => t.name === req.params.name);
  if (!tool) throw new Error(`Unknown tool: ${req.params.name}`);
  try {
    const result = await tool.handler(
      (req.params.arguments ?? {}) as Record<string, unknown>
    );
    return {
      content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    };
  } catch (error) {
    return {
      content: [{ type: "text", text: `Error: ${error}` }],
      isError: true,
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
console.error("agentcomms-mcp listening on stdio");
