# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# adapters/slack/signing.py
"""
Slack request signature verification.

Implements the HMAC-SHA256 signing scheme described at:
https://api.slack.com/authentication/verifying-requests-from-slack

Prevents replay attacks by rejecting timestamps older than 5 minutes.
"""
from __future__ import annotations

import hashlib
import hmac
import time


def verify_slack_request(
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
) -> bool:
    """Verify a Slack-signed HTTP request.

    Args:
        signing_secret: The Slack app's signing secret (from app settings).
        timestamp: Value of the X-Slack-Request-Timestamp header.
        body: Raw request body bytes.
        signature: Value of the X-Slack-Signature header (format: v0={hex}).

    Returns:
        True if the request is valid and recent; False otherwise.
    """
    # Reject stale timestamps (replay protection) — must be within 5 minutes
    try:
        ts_int = int(timestamp)
    except (ValueError, TypeError):
        return False

    if abs(time.time() - ts_int) > 300:
        return False

    # Build the basestring: v0:{timestamp}:{body}
    if isinstance(body, bytes):
        body_str = body.decode("utf-8", errors="replace")
    else:
        body_str = str(body)

    basestring = f"v0:{timestamp}:{body_str}"

    # Compute HMAC-SHA256
    mac = hmac.new(
        signing_secret.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    )
    expected_signature = f"v0={mac.hexdigest()}"

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_signature, signature)
