"""ULID generation utilities - zero dependency implementation."""

import os
import time

# Crockford Base32 alphabet
_ENCODING = "0123456789abcdefghjkmnpqrstvwxyz"


def generate_ulid() -> str:
    """Generate a new ULID as a 26-character lowercase Crockford Base32 string."""
    # 48-bit timestamp (milliseconds since Unix epoch)
    timestamp_ms = int(time.time() * 1000)
    # 80-bit randomness
    randomness = int.from_bytes(os.urandom(10), "big")

    # Encode timestamp (10 chars)
    t_chars = []
    for _ in range(10):
        t_chars.append(_ENCODING[timestamp_ms & 0x1F])
        timestamp_ms >>= 5
    t_chars.reverse()

    # Encode randomness (16 chars)
    r_chars = []
    for _ in range(16):
        r_chars.append(_ENCODING[randomness & 0x1F])
        randomness >>= 5
    r_chars.reverse()

    return "".join(t_chars) + "".join(r_chars)
