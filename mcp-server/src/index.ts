#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { FreemailAPI } from "./api.js";
import { getTools, handleTool } from "./tools.js";

const apiKey = process.env.FREEMAIL_API_KEY;
if (!apiKey) {
  console.error("FREEMAIL_API_KEY environment variable is required");
  process.exit(1);
}

const baseUrl = process.env.FREEMAIL_API_URL || "https://api.victorymail.dev/v1";
const api = new FreemailAPI(apiKey, baseUrl);

const server = new Server(
  { name: "freemail", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: getTools(),
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  try {
    const result = await handleTool(name, args || {}, api);
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

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
