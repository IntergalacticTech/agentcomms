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
    let parsed: unknown = undefined;
    try {
      parsed = await resp.json();
    } catch {
      // ignore parse error
    }
    const { code, msg } = AgentCommsError.parseError(parsed, resp.statusText);

    if (resp.status === 404) return new NotFoundError(resp.status, code, msg);
    if (resp.status === 401 || resp.status === 403) return new AuthenticationError(resp.status, code, msg);
    if (resp.status === 429) return new RateLimitError(resp.status, code, msg);
    if (resp.status >= 500) return new ServerError(resp.status, code, msg);
    return new AgentCommsError(resp.status, code, msg);
  }

  /**
   * Extract `{code, message}` from a parsed error body. The API returns
   * errors either as a bare string (`{"error": "<string>"}`) or as an object
   * (`{"error": {"code", "message"}}`). Both shapes are supported so the
   * message is never silently discarded.
   */
  private static parseError(
    parsed: unknown,
    fallbackMessage: string,
  ): { code: string; msg: string } {
    if (typeof parsed === "object" && parsed !== null && "error" in parsed) {
      const error = (parsed as { error: unknown }).error;
      if (typeof error === "string") {
        return { code: "ERROR", msg: error };
      }
      if (typeof error === "object" && error !== null) {
        const e = error as { code?: string; message?: string };
        return { code: e.code ?? "UNKNOWN", msg: e.message ?? fallbackMessage };
      }
    }
    return { code: "UNKNOWN", msg: fallbackMessage };
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
