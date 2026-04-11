export class FreemailError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FreemailError";
  }
}

export class FreemailAPIError extends FreemailError {
  public statusCode: number;
  public code: string;

  constructor(statusCode: number, code: string, message: string) {
    super(`${code}: ${message}`);
    this.name = "FreemailAPIError";
    this.statusCode = statusCode;
    this.code = code;
  }
}

export class NotFoundError extends FreemailAPIError {
  constructor(statusCode: number, code: string, message: string) {
    super(statusCode, code, message);
    this.name = "NotFoundError";
  }
}

export class AuthenticationError extends FreemailAPIError {
  constructor(statusCode: number, code: string, message: string) {
    super(statusCode, code, message);
    this.name = "AuthenticationError";
  }
}

export class RateLimitError extends FreemailAPIError {
  constructor(statusCode: number, code: string, message: string) {
    super(statusCode, code, message);
    this.name = "RateLimitError";
  }
}

export class QuotaExceededError extends FreemailAPIError {
  constructor(statusCode: number, code: string, message: string) {
    super(statusCode, code, message);
    this.name = "QuotaExceededError";
  }
}
