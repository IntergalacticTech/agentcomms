// SPDX-License-Identifier: FSL-1.1-Apache-2.0
import { API_KEY, BASE_URL } from "./config.js";

export async function apiRequest(
  method: string,
  path: string,
  body?: unknown
): Promise<unknown> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 204) return {};
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(`API error ${resp.status}: ${JSON.stringify(data)}`);
  }
  return data;
}
