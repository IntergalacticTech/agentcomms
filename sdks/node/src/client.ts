import {
  FreemailAPIError,
  NotFoundError,
  AuthenticationError,
  RateLimitError,
  QuotaExceededError,
} from "./errors.js";
import { InboxResource } from "./resources/inboxes.js";
import { MessageResource } from "./resources/messages.js";
import { PodResource } from "./resources/pods.js";
import { DomainResource } from "./resources/domains.js";
import { WebhookResource } from "./resources/webhooks.js";
import { ApiKeyResource } from "./resources/api-keys.js";
import type { Organization } from "./types.js";

export interface FreemailClientOptions {
  baseUrl?: string;
}

export class FreeMail {
  private apiKey: string;
  private baseUrl: string;

  readonly inboxes: InboxResource;
  readonly messages: MessageResource;
  readonly pods: PodResource;
  readonly domains: DomainResource;
  readonly webhooks: WebhookResource;
  readonly apiKeys: ApiKeyResource;

  constructor(apiKey: string, options?: FreemailClientOptions) {
    this.apiKey = apiKey;
    this.baseUrl = (
      options?.baseUrl || "https://api.victorymail.dev/v1"
    ).replace(/\/$/, "");

    const boundRequest = this.request.bind(this);
    this.inboxes = new InboxResource(boundRequest);
    this.messages = new MessageResource(boundRequest);
    this.pods = new PodResource(boundRequest);
    this.domains = new DomainResource(boundRequest);
    this.webhooks = new WebhookResource(boundRequest);
    this.apiKeys = new ApiKeyResource(boundRequest);
  }

  async getOrganization(): Promise<Organization> {
    return this.request("GET", "/organization");
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {
      "x-api-key": this.apiKey,
      "Content-Type": "application/json",
    };

    const resp = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const errorData = data as { error?: { code?: string; message?: string } };
      const code = errorData?.error?.code || "UNKNOWN";
      const msg = errorData?.error?.message || resp.statusText;

      if (resp.status === 404)
        throw new NotFoundError(resp.status, code, msg);
      if (resp.status === 401)
        throw new AuthenticationError(resp.status, code, msg);
      if (resp.status === 429)
        throw new RateLimitError(resp.status, code, msg);
      if (resp.status === 403 && code === "QUOTA_EXCEEDED")
        throw new QuotaExceededError(resp.status, code, msg);

      throw new FreemailAPIError(resp.status, code, msg);
    }

    if (resp.status === 204) return {} as T;
    return resp.json() as Promise<T>;
  }
}
