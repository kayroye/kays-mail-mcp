"""Shared helpers for enforcing server-side safety limits."""

from __future__ import annotations


class LimitExceededError(ValueError):
    """Raised when untrusted data exceeds a configured server-side limit."""


def enforce_byte_limit(value: bytes, maximum: int, *, field: str) -> bytes:
    """Return data only when it fits its non-client-overridable maximum size."""
    if len(value) > maximum:
        raise LimitExceededError(f"{field} exceeds the configured size limit")
    return value
