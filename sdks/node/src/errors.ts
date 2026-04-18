// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.

export class AgentCommsError extends Error {
  public readonly statusCode: number;
  public readonly code: string;

  constructor(statusCode: number, code: string, message: string) {
    super(`[${statusCode}] ${code}: ${message}`);
    this.name = "AgentCommsError";
    this.statusCode = statusCode;
    this.code = code;
  }

  static async fromResponse(resp: Response): Promise<AgentCommsError> {
    let body: { error?: { code?: string; message?: string } } = {};
    try {
      const parsed = await resp.json() as unknown;
      if (typeof parsed === "object" && parsed !== null) {
        body = parsed as { error?: { code?: string; message?: string } };
      }
    } catch {
      // ignore parse error
    }
    const code = body?.error?.code ?? "UNKNOWN";
    const msg = body?.error?.message ?? resp.statusText;

    if (resp.status === 404) return new NotFoundError(resp.status, code, msg);
    if (resp.status === 401 || resp.status === 403) return new AuthenticationError(resp.status, code, msg);
    if (resp.status === 429) return new RateLimitError(resp.status, code, msg);
    if (resp.status >= 500) return new ServerError(resp.status, code, msg);
    return new AgentCommsError(resp.status, code, msg);
  }
}

export class NotFoundError extends AgentCommsError {
  constructor(statusCode: number, code: string, message: string) {
    super(statusCode, code, message);
    this.name = "NotFoundError";
  }
}

export class AuthenticationError extends AgentCommsError {
  constructor(statusCode: number, code: string, message: string) {
    super(statusCode, code, message);
    this.name = "AuthenticationError";
  }
}

export class RateLimitError extends AgentCommsError {
  constructor(statusCode: number, code: string, message: string) {
    super(statusCode, code, message);
    this.name = "RateLimitError";
  }
}

export class ServerError extends AgentCommsError {
  constructor(statusCode: number, code: string, message: string) {
    super(statusCode, code, message);
    this.name = "ServerError";
  }
}
