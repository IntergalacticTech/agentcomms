class FreemailError(Exception):
    """Base exception for FreeMail SDK."""
    pass


class FreemailAPIError(FreemailError):
    """Raised when the FreeMail API returns an error response."""

    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.code = body.get("error", {}).get("code", "UNKNOWN")
        self.message = body.get("error", {}).get("message", str(body))
        super().__init__(f"{self.code}: {self.message}")


class NotFoundError(FreemailAPIError):
    """Raised when the requested resource is not found (404)."""
    pass


class AuthenticationError(FreemailAPIError):
    """Raised when authentication fails (401/403)."""
    pass


class RateLimitError(FreemailAPIError):
    """Raised when the API rate limit is exceeded (429)."""
    pass
