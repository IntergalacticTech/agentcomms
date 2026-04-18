// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { apiRequest } from "../client.js";
import type { Tool } from "./agents.js";

export const messageTools: Tool[] = [
  {
    name: "messages_list",
    description:
      "List messages for an agent with optional filters for time range, channels, and limit.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        since: { type: "string", description: "ISO 8601 timestamp lower bound" },
        until: { type: "string", description: "ISO 8601 timestamp upper bound" },
        channels: {
          type: "array",
          items: { type: "string" },
          description: "Filter by channel IDs",
        },
        limit: { type: "number", description: "Max messages to return (default 25)" },
      },
      required: ["agent_id"],
    },
    handler: async (args) => {
      const params = new URLSearchParams();
      if (args.since) params.set("since", String(args.since));
      if (args.until) params.set("until", String(args.until));
      if (Array.isArray(args.channels)) {
        (args.channels as string[]).forEach((c) => params.append("channels", c));
      }
      if (args.limit) params.set("limit", String(args.limit));
      const qs = params.toString();
      return apiRequest("GET", `/agents/${args.agent_id}/messages${qs ? `?${qs}` : ""}`);
    },
  },
  {
    name: "message_get",
    description: "Get a single message by ID. Requires received_at_ms for DynamoDB sort key lookup.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        message_id: { type: "string", description: "The message ID" },
        received_at_ms: {
          type: "number",
          description: "Unix timestamp in milliseconds when the message was received",
        },
      },
      required: ["agent_id", "message_id", "received_at_ms"],
    },
    handler: async (args) => {
      return apiRequest(
        "GET",
        `/agents/${args.agent_id}/messages/${args.message_id}?received_at_ms=${args.received_at_ms}`
      );
    },
  },
  {
    name: "message_send",
    description:
      "Send a message from an agent to a recipient. Channel is auto-inferred from the 'to' address if omitted.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID to send from" },
        to: { type: "string", description: "Recipient address (email, phone, etc.)" },
        body: { type: "string", description: "Message body text" },
        channel: { type: "string", description: "Channel ID (optional; auto-inferred if omitted)" },
        subject: { type: "string", description: "Subject line for email messages" },
      },
      required: ["agent_id", "to", "body"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = {
        to: args.to,
        body: args.body,
      };
      if (args.channel) body.channel = args.channel;
      if (args.subject) body.subject = args.subject;
      return apiRequest("POST", `/agents/${args.agent_id}/messages`, body);
    },
  },
  {
    name: "message_reply",
    description: "Reply to an existing message thread.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        message_id: { type: "string", description: "The message ID to reply to" },
        body: { type: "string", description: "Reply body text" },
      },
      required: ["agent_id", "message_id", "body"],
    },
    handler: async (args) => {
      return apiRequest(
        "POST",
        `/agents/${args.agent_id}/messages/${args.message_id}/reply`,
        { body: args.body }
      );
    },
  },
  {
    name: "wait_for_message",
    description:
      "Long-poll for a new message matching optional criteria. Returns the message when it arrives or times out.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID to wait on" },
        channel: { type: "string", description: "Restrict to a specific channel ID" },
        from: { type: "string", description: "Filter by sender address" },
        subject_contains: { type: "string", description: "Substring to match in subject" },
        timeout_sec: {
          type: "number",
          description: "Max seconds to wait (default 25, max 60)",
        },
      },
      required: ["agent_id"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = {};
      if (args.channel) body.channel = args.channel;
      if (args.from) body.from = args.from;
      if (args.subject_contains) body.subject_contains = args.subject_contains;
      if (args.timeout_sec) body.timeout_sec = args.timeout_sec;
      return apiRequest("POST", `/agents/${args.agent_id}/wait`, body);
    },
  },
  {
    name: "extract_otp",
    description:
      "Wait for a message and extract a one-time password or verification code from it.",
    inputSchema: {
      type: "object",
      properties: {
        agent_id: { type: "string", description: "The agent ID" },
        channel: { type: "string", description: "Restrict to a specific channel ID" },
        from: { type: "string", description: "Filter by sender address" },
        max_age_sec: {
          type: "number",
          description: "Only consider messages received within this many seconds",
        },
      },
      required: ["agent_id"],
    },
    handler: async (args) => {
      const body: Record<string, unknown> = {};
      if (args.channel) body.channel = args.channel;
      if (args.from) body.from = args.from;
      if (args.max_age_sec) body.max_age_sec = args.max_age_sec;
      return apiRequest("POST", `/agents/${args.agent_id}/extract-otp`, body);
    },
  },
];
