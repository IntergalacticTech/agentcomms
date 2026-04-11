import type {
  ApiKey,
  PaginatedResponse,
  CreateApiKeyOptions,
  ListApiKeyOptions,
} from "../types.js";

type RequestFn = <T>(method: string, path: string, body?: unknown) => Promise<T>;

export class ApiKeyResource {
  constructor(private request: RequestFn) {}

  async list(options?: ListApiKeyOptions): Promise<PaginatedResponse<ApiKey>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.page_token) params.set("page_token", options.page_token);
    const qs = params.toString();
    return this.request("GET", `/api-keys${qs ? `?${qs}` : ""}`);
  }

  async create(options: CreateApiKeyOptions): Promise<ApiKey> {
    return this.request("POST", "/api-keys", options);
  }

  async delete(apiKeyId: string): Promise<void> {
    await this.request("DELETE", `/api-keys/${apiKeyId}`);
  }
}
