// SPDX-License-Identifier: Apache-2.0
import { API_KEY, BASE_URL } from "./config.js";

// Default per-request timeout (ms). Overridable via AGENTCOMMS_TIMEOUT_MS.
const DEFAULT_TIMEOUT_MS = Number(process.env.AGENTCOMMS_TIMEOUT_MS) || 30_000;

export async function apiRequest(
  method: string,
  path: string,
  body?: unknown,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let resp: Response;
  try {
    resp = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${API_KEY}`,
        "Content-Type": "application/json",
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  if (resp.status === 204) return {};
  // Check status before parsing so a non-JSON error body cannot mask the
  // real HTTP status.
  if (!resp.ok) {
    let detail = "";
    try {
      detail = await resp.text();
    } catch {
      // ignore read error
    }
    throw new Error(`API error ${resp.status}: ${detail || resp.statusText}`);
  }
  return await resp.json();
}
