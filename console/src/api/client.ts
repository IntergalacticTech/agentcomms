const API_BASE =
  import.meta.env.VITE_API_URL ||
  "https://api.victorymail.dev/v1";

class ApiClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
  }

  clearToken() {
    this.token = null;
  }

  async request(method: string, path: string, body?: unknown) {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
      headers["x-api-key"] = this.token;
    }
    const resp = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (resp.status === 401) {
      // Token expired or invalid
      throw new Error("Unauthorized");
    }
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`API ${resp.status}: ${text}`);
    }
    if (resp.status === 204) return null;
    return resp.json();
  }

  get(path: string) {
    return this.request("GET", path);
  }
  post(path: string, body?: unknown) {
    return this.request("POST", path, body);
  }
  patch(path: string, body?: unknown) {
    return this.request("PATCH", path, body);
  }
  delete(path: string) {
    return this.request("DELETE", path);
  }
}

export const api = new ApiClient();
