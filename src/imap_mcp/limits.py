"""share fixed size checks across message and attachment parsing
keep input limits enforced independently of MCP caller parameters
"""

from __future__ import annotations


class LimitExceededError(ValueError):
    """report data that exceeds a configured server-side limit"""


def enforce_byte_limit(value: bytes, maximum: int, *, field: str) -> bytes:
    """return data only when it fits its server-controlled maximum size"""
    if len(value) > maximum:
        raise LimitExceededError(f"{field} exceeds the configured size limit")
    return value
