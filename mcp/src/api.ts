export class FreemailAPI {
  constructor(
    private apiKey: string,
    private baseUrl: string = "https://api.victorymail.dev/v1"
  ) {}

  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "x-api-key": this.apiKey,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (resp.status === 204) return {};
    const data = await resp.json();
    if (!resp.ok) throw new Error(`API error ${resp.status}: ${JSON.stringify(data)}`);
    return data;
  }
}
