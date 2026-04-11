import type {
  Webhook,
  PaginatedResponse,
  CreateWebhookOptions,
  UpdateWebhookOptions,
  ListWebhookOptions,
} from "../types.js";

type RequestFn = <T>(method: string, path: string, body?: unknown) => Promise<T>;

export class WebhookResource {
  constructor(private request: RequestFn) {}

  async list(
    options?: ListWebhookOptions
  ): Promise<PaginatedResponse<Webhook>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.page_token) params.set("page_token", options.page_token);
    const qs = params.toString();
    return this.request("GET", `/webhooks${qs ? `?${qs}` : ""}`);
  }

  async create(options: CreateWebhookOptions): Promise<Webhook> {
    return this.request("POST", "/webhooks", options);
  }

  async update(
    webhookId: string,
    updates: UpdateWebhookOptions
  ): Promise<Webhook> {
    return this.request("PATCH", `/webhooks/${webhookId}`, updates);
  }

  async delete(webhookId: string): Promise<void> {
    await this.request("DELETE", `/webhooks/${webhookId}`);
  }
}
