import type {
  Inbox,
  Message,
  PaginatedResponse,
  CreateInboxOptions,
  ListInboxesOptions,
  WaitForMessageOptions,
  ExtractOtpOptions,
  ExtractOtpResult,
} from "../types.js";

type RequestFn = <T>(method: string, path: string, body?: unknown) => Promise<T>;

export class InboxResource {
  constructor(private request: RequestFn) {}

  async list(options?: ListInboxesOptions): Promise<PaginatedResponse<Inbox>> {
    const params = new URLSearchParams();
    if (options?.pod_id) params.set("pod_id", options.pod_id);
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.page_token) params.set("page_token", options.page_token);
    const qs = params.toString();
    return this.request("GET", `/inboxes${qs ? `?${qs}` : ""}`);
  }

  async get(inboxId: string): Promise<Inbox> {
    return this.request("GET", `/inboxes/${inboxId}`);
  }

  async create(options?: CreateInboxOptions): Promise<Inbox> {
    return this.request("POST", "/inboxes", options ?? {});
  }

  async update(inboxId: string, updates: Partial<Inbox>): Promise<Inbox> {
    return this.request("PATCH", `/inboxes/${inboxId}`, updates);
  }

  async delete(inboxId: string): Promise<void> {
    await this.request("DELETE", `/inboxes/${inboxId}`);
  }

  async waitForMessage(
    inboxId: string,
    options?: WaitForMessageOptions
  ): Promise<Message> {
    const params = new URLSearchParams();
    if (options?.timeout) params.set("timeout", String(options.timeout));
    if (options?.sender) params.set("sender", options.sender);
    if (options?.subject_contains)
      params.set("subject_contains", options.subject_contains);
    const qs = params.toString();
    return this.request(
      "GET",
      `/inboxes/${inboxId}/wait${qs ? `?${qs}` : ""}`
    );
  }

  async extractOtp(
    inboxId: string,
    options?: ExtractOtpOptions
  ): Promise<ExtractOtpResult> {
    const params = new URLSearchParams();
    if (options?.timeout) params.set("timeout", String(options.timeout));
    if (options?.sender) params.set("sender", options.sender);
    if (options?.subject_contains)
      params.set("subject_contains", options.subject_contains);
    const qs = params.toString();
    return this.request(
      "GET",
      `/inboxes/${inboxId}/extract-otp${qs ? `?${qs}` : ""}`
    );
  }
}
