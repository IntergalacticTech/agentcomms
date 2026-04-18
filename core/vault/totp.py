# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/vault/totp.py
"""RFC 6238 TOTP code generator — stdlib only, no external deps.

Algorithm:
  1. Decode the base32 seed.
  2. Compute the HOTP counter as floor(unix_time / period).
  3. HMAC-SHA1 the counter (big-endian 8-byte).
  4. Dynamic truncate → 31-bit integer → mod 10^digits → zero-pad.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import math
import struct
import time


def generate_totp_code(
    seed_b32: str,
    t: int | None = None,
    digits: int = 6,
    period: int = 30,
) -> str:
    """Return the current TOTP code for *seed_b32*.

    Args:
        seed_b32: Base32-encoded shared secret (RFC 4648; case-insensitive,
                  spaces allowed).
        t:        Unix timestamp to evaluate at. Defaults to ``time.time()``.
        digits:   Number of digits in the OTP (default 6).
        period:   Time-step in seconds (default 30).

    Returns:
        Zero-padded decimal string of length *digits*.
    """
    if t is None:
        t = int(time.time())

    # Normalise seed
    normalised = seed_b32.strip().replace(" ", "").upper()
    # Pad to a multiple of 8 if needed
    padding = (8 - len(normalised) % 8) % 8
    key = base64.b32decode(normalised + "=" * padding, casefold=True)

    counter = t // period
    msg = struct.pack(">Q", counter)
    mac = hmac.new(key, msg, hashlib.sha1).digest()

    offset = mac[-1] & 0x0F
    code_int = (
        ((mac[offset] & 0x7F) << 24)
        | ((mac[offset + 1] & 0xFF) << 16)
        | ((mac[offset + 2] & 0xFF) << 8)
        | (mac[offset + 3] & 0xFF)
    )
    return str(code_int % (10 ** digits)).zfill(digits)


def totp_valid_until(t: int | None = None, period: int = 30) -> int:
    """Return the Unix epoch at which the current time-step expires."""
    if t is None:
        t = int(time.time())
    return (t // period + 1) * period
