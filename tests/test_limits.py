from __future__ import annotations

import pytest

from imap_mcp.limits import LimitExceededError, enforce_byte_limit


def test_enforce_byte_limit_returns_value_at_limit() -> None:
    assert enforce_byte_limit(b"1234", 4, field="body") == b"1234"


def test_enforce_byte_limit_rejects_oversized_value() -> None:
    with pytest.raises(LimitExceededError, match="body exceeds"):
        enforce_byte_limit(b"12345", 4, field="body")
