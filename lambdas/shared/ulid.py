"""ULID generation utilities."""

from ulid import ULID


def generate_ulid() -> str:
    """Generate a new ULID as a lowercase string."""
    return str(ULID()).lower()
