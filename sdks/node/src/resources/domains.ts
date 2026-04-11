import type {
  Domain,
  PaginatedResponse,
  CreateDomainOptions,
  ListDomainOptions,
} from "../types.js";

type RequestFn = <T>(method: string, path: string, body?: unknown) => Promise<T>;

export class DomainResource {
  constructor(private request: RequestFn) {}

  async list(options?: ListDomainOptions): Promise<PaginatedResponse<Domain>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.page_token) params.set("page_token", options.page_token);
    const qs = params.toString();
    return this.request("GET", `/domains${qs ? `?${qs}` : ""}`);
  }

  async get(domainId: string): Promise<Domain> {
    return this.request("GET", `/domains/${domainId}`);
  }

  async create(options: CreateDomainOptions): Promise<Domain> {
    return this.request("POST", "/domains", options);
  }

  async verify(domainId: string): Promise<Domain> {
    return this.request("POST", `/domains/${domainId}/verify`);
  }

  async delete(domainId: string): Promise<void> {
    await this.request("DELETE", `/domains/${domainId}`);
  }
}
