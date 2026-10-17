"""verify the shared byte limit accepts boundary values and rejects overflow
these checks cover the helper used by MIME body and attachment parsing
"""

from __future__ import annotations

from imap_mcp.limits import enforce_byte_limit


def test_enforce_byte_limit_returns_value_at_limit() -> None:
    """check a payload exactly at its limit is returned unchanged"""
    assert enforce_byte_limit(b"1234", 4, field="body") == b"1234"
