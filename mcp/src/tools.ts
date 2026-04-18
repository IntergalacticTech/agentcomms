import { FreemailAPI } from "./api.js";

interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export function getTools(): ToolDefinition[] {
  return [
    {
      name: "create_inbox",
      description: "Create a new email inbox. Returns the inbox details including its email address.",
      inputSchema: {
        type: "object",
        properties: {
          display_name: {
            type: "string",
            description: "Optional display name for the inbox",
          },
          pod_id: {
            type: "string",
            description: "Optional pod ID to associate the inbox with",
          },
        },
      },
    },
    {
      name: "list_inboxes",
      description: "List all email inboxes in the organization.",
      inputSchema: {
        type: "object",
        properties: {
          pod_id: {
            type: "string",
            description: "Optional pod ID to filter inboxes by",
          },
          limit: {
            type: "number",
            description: "Maximum number of inboxes to return (default 25)",
          },
        },
      },
    },
    {
      name: "send_email",
      description: "Send an email from an inbox.",
      inputSchema: {
        type: "object",
        properties: {
          inbox_id: {
            type: "string",
            description: "The inbox ID to send from",
          },
          to: {
            type: "array",
            items: {
              type: "object",
              properties: {
                address: { type: "string" },
              },
              required: ["address"],
            },
            description: "Array of recipient objects with address field",
          },
          subject: {
            type: "string",
            description: "Email subject line",
          },
          body_text: {
            type: "string",
            description: "Plain text email body",
          },
          body_html: {
            type: "string",
            description: "HTML email body",
          },
        },
        required: ["inbox_id", "to", "subject"],
      },
    },
    {
      name: "list_messages",
      description: "List messages in an inbox.",
      inputSchema: {
        type: "object",
        properties: {
          inbox_id: {
            type: "string",
            description: "The inbox ID to list messages from",
          },
          limit: {
            type: "number",
            description: "Maximum number of messages to return",
          },
        },
        required: ["inbox_id"],
      },
    },
    {
      name: "get_message",
      description: "Get a specific message with its full body content.",
      inputSchema: {
        type: "object",
        properties: {
          inbox_id: {
            type: "string",
            description: "The inbox ID",
          },
          message_id: {
            type: "string",
            description: "The message ID to retrieve",
          },
        },
        required: ["inbox_id", "message_id"],
      },
    },
    {
      name: "reply_to_message",
      description: "Reply to a specific message in an inbox.",
      inputSchema: {
        type: "object",
        properties: {
          inbox_id: {
            type: "string",
            description: "The inbox ID",
          },
          message_id: {
            type: "string",
            description: "The message ID to reply to",
          },
          body_text: {
            type: "string",
            description: "Plain text reply body",
          },
          body_html: {
            type: "string",
            description: "HTML reply body",
          },
        },
        required: ["inbox_id", "message_id", "body_text"],
      },
    },
    {
      name: "wait_for_email",
      description: "Wait for a new email matching criteria to arrive in an inbox.",
      inputSchema: {
        type: "object",
        properties: {
          inbox_id: {
            type: "string",
            description: "The inbox ID to wait on",
          },
          timeout: {
            type: "number",
            description: "Timeout in seconds (default 25)",
          },
          sender: {
            type: "string",
            description: "Optional sender address to filter by",
          },
          subject_contains: {
            type: "string",
            description: "Optional substring to match in subject",
          },
        },
        required: ["inbox_id"],
      },
    },
    {
      name: "extract_otp",
      description: "Wait for an email and extract a verification/OTP code from it.",
      inputSchema: {
        type: "object",
        properties: {
          inbox_id: {
            type: "string",
            description: "The inbox ID to wait on",
          },
          timeout: {
            type: "number",
            description: "Timeout in seconds",
          },
          sender: {
            type: "string",
            description: "Optional sender address to filter by",
          },
          subject_contains: {
            type: "string",
            description: "Optional substring to match in subject",
          },
        },
        required: ["inbox_id"],
      },
    },
    {
      name: "delete_inbox",
      description: "Delete an inbox and all its messages.",
      inputSchema: {
        type: "object",
        properties: {
          inbox_id: {
            type: "string",
            description: "The inbox ID to delete",
          },
        },
        required: ["inbox_id"],
      },
    },
    {
      name: "get_organization",
      description: "Get information about the current organization.",
      inputSchema: {
        type: "object",
        properties: {},
      },
    },
  ];
}

export async function handleTool(
  name: string,
  args: Record<string, unknown>,
  api: FreemailAPI
): Promise<unknown> {
  switch (name) {
    case "create_inbox": {
      const body: Record<string, unknown> = {};
      if (args.display_name) body.display_name = args.display_name;
      if (args.pod_id) body.pod_id = args.pod_id;
      return api.request("POST", "/inboxes", body);
    }

    case "list_inboxes": {
      const params = new URLSearchParams();
      if (args.pod_id) params.set("pod_id", String(args.pod_id));
      if (args.limit) params.set("limit", String(args.limit));
      const qs = params.toString();
      return api.request("GET", `/inboxes${qs ? `?${qs}` : ""}`);
    }

    case "send_email": {
      const body: Record<string, unknown> = {
        to: args.to,
        subject: args.subject,
      };
      if (args.body_text) body.body_text = args.body_text;
      if (args.body_html) body.body_html = args.body_html;
      return api.request("POST", `/inboxes/${args.inbox_id}/messages`, body);
    }

    case "list_messages": {
      const params = new URLSearchParams();
      if (args.limit) params.set("limit", String(args.limit));
      const qs = params.toString();
      return api.request("GET", `/inboxes/${args.inbox_id}/messages${qs ? `?${qs}` : ""}`);
    }

    case "get_message": {
      return api.request("GET", `/inboxes/${args.inbox_id}/messages/${args.message_id}`);
    }

    case "reply_to_message": {
      const body: Record<string, unknown> = {
        body_text: args.body_text,
      };
      if (args.body_html) body.body_html = args.body_html;
      return api.request(
        "POST",
        `/inboxes/${args.inbox_id}/messages/${args.message_id}/reply`,
        body
      );
    }

    case "wait_for_email": {
      const body: Record<string, unknown> = {};
      if (args.timeout) body.timeout = args.timeout;
      if (args.sender) body.sender = args.sender;
      if (args.subject_contains) body.subject_contains = args.subject_contains;
      return api.request("POST", `/inboxes/${args.inbox_id}/wait`, body);
    }

    case "extract_otp": {
      const body: Record<string, unknown> = {};
      if (args.timeout) body.timeout = args.timeout;
      if (args.sender) body.sender = args.sender;
      if (args.subject_contains) body.subject_contains = args.subject_contains;
      return api.request("POST", `/inboxes/${args.inbox_id}/extract-otp`, body);
    }

    case "delete_inbox": {
      return api.request("DELETE", `/inboxes/${args.inbox_id}`);
    }

    case "get_organization": {
      return api.request("GET", "/organizations/me");
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}
