import type {
  Message,
  PaginatedResponse,
  SendMessageOptions,
  ReplyMessageOptions,
  ForwardMessageOptions,
  UpdateMessageOptions,
  ListMessagesOptions,
} from "../types.js";

type RequestFn = <T>(method: string, path: string, body?: unknown) => Promise<T>;

export class MessageResource {
  constructor(private request: RequestFn) {}

  async list(
    inboxId: string,
    options?: ListMessagesOptions
  ): Promise<PaginatedResponse<Message>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.page_token) params.set("page_token", options.page_token);
    const qs = params.toString();
    return this.request(
      "GET",
      `/inboxes/${inboxId}/messages${qs ? `?${qs}` : ""}`
    );
  }

  async get(inboxId: string, messageId: string): Promise<Message> {
    return this.request("GET", `/inboxes/${inboxId}/messages/${messageId}`);
  }

  async send(inboxId: string, options: SendMessageOptions): Promise<Message> {
    return this.request("POST", `/inboxes/${inboxId}/messages`, options);
  }

  async reply(
    inboxId: string,
    messageId: string,
    options: ReplyMessageOptions
  ): Promise<Message> {
    return this.request(
      "POST",
      `/inboxes/${inboxId}/messages/${messageId}/reply`,
      options
    );
  }

  async forward(
    inboxId: string,
    messageId: string,
    options: ForwardMessageOptions
  ): Promise<Message> {
    return this.request(
      "POST",
      `/inboxes/${inboxId}/messages/${messageId}/forward`,
      options
    );
  }

  async update(
    inboxId: string,
    messageId: string,
    updates: UpdateMessageOptions
  ): Promise<Message> {
    return this.request(
      "PATCH",
      `/inboxes/${inboxId}/messages/${messageId}`,
      updates
    );
  }
}
