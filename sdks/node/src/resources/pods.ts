import type {
  Pod,
  PaginatedResponse,
  CreatePodOptions,
  ListPodOptions,
} from "../types.js";

type RequestFn = <T>(method: string, path: string, body?: unknown) => Promise<T>;

export class PodResource {
  constructor(private request: RequestFn) {}

  async list(options?: ListPodOptions): Promise<PaginatedResponse<Pod>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.page_token) params.set("page_token", options.page_token);
    const qs = params.toString();
    return this.request("GET", `/pods${qs ? `?${qs}` : ""}`);
  }

  async get(podId: string): Promise<Pod> {
    return this.request("GET", `/pods/${podId}`);
  }

  async create(options: CreatePodOptions): Promise<Pod> {
    return this.request("POST", "/pods", options);
  }

  async delete(podId: string): Promise<void> {
    await this.request("DELETE", `/pods/${podId}`);
  }
}
