"""verify search input bounds and normalized paginated result shapes
use a fake client to inspect the server cap without opening an IMAP connection
"""

from __future__ import annotations

import pytest

from imap_mcp.config import Settings, load_settings
from imap_mcp.imap_client import MessageHeader
from imap_mcp.tools.search import make_search_messages


class FakeSearchClient:
    """capture search settings and return one deterministic header fixture"""

    def __init__(self, settings: Settings) -> None:
        """retain settings and initialize the observed result cap"""
        self.settings = settings
        self.maximum: int | None = None

    def __enter__(self) -> FakeSearchClient:
        """let the fake stand in for a context-managed IMAP session"""
        return self

    def __exit__(self, *_: object) -> None:
        """complete the fake session without external cleanup"""
        return None

    def search_headers(self, mailbox: str, **kwargs: object) -> tuple[MessageHeader, ...]:
        """record the requested maximum and return one raw header result"""
        assert mailbox == "INBOX"
        self.maximum = kwargs["maximum"] if isinstance(kwargs["maximum"], int) else None
        return (
            MessageHeader(
                22,
                b"Subject: Fixture\r\nFrom: sender@example.test\r\n"
                b"To: recipient@example.test\r\n\r\n",
                True,
            ),
        )


def settings() -> Settings:
    """build settings with low limits so clamping is observable"""
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX",
            "IMAP_MAX_RESULTS": "2",
            "IMAP_MAX_QUERY_LENGTH": "8",
        }
    )


def test_search_returns_compact_metadata_and_clamps_limit() -> None:
    """check metadata normalization and the configured result cap"""
    client: FakeSearchClient | None = None

    def factory(configuration: Settings) -> FakeSearchClient:
        """capture the client instance so the test can inspect its requested cap"""
        nonlocal client
        client = FakeSearchClient(configuration)
        return client

    result = make_search_messages(settings(), client_factory=factory)("INBOX", limit=99)

    assert result == {
        "messages": [
            {
                "uid": 22,
                "uidvalidity": 0,
                "subject": "Fixture",
                "sender": "sender@example.test",
                "recipients": ["recipient@example.test"],
                "date": "",
                "is_unread": True,
            }
        ],
        "next_before_uid": None,
    }
    assert client is not None
    assert client.maximum == 2


def test_search_rejects_query_larger_than_server_limit() -> None:
    """check query length is enforced before search reaches the client"""
    tool = make_search_messages(settings(), client_factory=FakeSearchClient)

    with pytest.raises(ValueError, match="query length"):
        tool("INBOX", query="too long!")


def test_search_rejects_inverted_date_range() -> None:
    """check a date range with no forward interval is rejected"""
    tool = make_search_messages(settings(), client_factory=FakeSearchClient)

    with pytest.raises(ValueError, match="earlier"):
        tool("INBOX", after_date="2026-08-05", before_date="2026-08-05")
