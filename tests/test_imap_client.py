"""verify read-only IMAP command selection and safe search value handling
use a fake wire connection to check emitted commands without network access
"""

from __future__ import annotations

from builtins import list as builtin_list
from dataclasses import dataclass, field
from typing import Any

import pytest

from imap_mcp.config import Settings, load_settings
from imap_mcp.errors import MailboxNotAllowedError, MessageNotFoundError
from imap_mcp.imap_client import ImapClient, _search_criteria


@dataclass
class FakeConnection:
    """record client commands and return deterministic IMAP responses"""

    list_response: list[bytes | None] = field(
        default_factory=lambda: [b'(\\HasNoChildren) "/" "INBOX"']
    )
    fetched_message: bytes | None = b"Subject: fixture\r\n\r\nbody"
    selected: list[tuple[str, bool]] = field(default_factory=list)
    uid_calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    logged_out: bool = False
    literal: bytes | None = None
    maximum: int = 26_214_401
    remaining: int | None = None

    def response(self, code: str) -> tuple[str, list[bytes]]:
        """return a valid UIDVALIDITY response for mailbox selection"""
        return code, [b"101"]

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        """accept the fixture credentials without contacting a server"""
        del user, password
        return "OK", [b"logged in"]

    def logout(self) -> tuple[str, list[bytes]]:
        """record session closure"""
        self.logged_out = True
        return "BYE", [b"logout"]

    def noop(self) -> tuple[str, list[bytes]]:
        """accept a read-only liveness probe"""
        return "OK", [b"ready"]

    def list(self) -> tuple[str, Any]:
        """return the configured fixture mailbox listing"""
        return "OK", self.list_response

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, builtin_list[bytes]]:
        """record the mailbox name and requested read-only mode"""
        self.selected.append((mailbox, readonly))
        return "OK", [b"1"]

    def uid(self, command: str, *args: str) -> tuple[str, builtin_list[object]]:
        """record UID commands and return a size or message fixture"""
        self.uid_calls.append((command, args))
        if args[-1] == "(RFC822.SIZE)":
            return "OK", [b"1 (UID 42 RFC822.SIZE 100)"]
        if self.fetched_message is None:
            return "OK", [None]
        return "OK", [(b"1 (RFC822 {1})", self.fetched_message)]


def settings() -> Settings:
    """build minimal settings with two allowed mailboxes"""
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX, Archive",
        }
    )


def test_client_lists_only_configured_existing_mailboxes() -> None:
    """check mailbox listing intersects server results with the configured allowlist"""
    connection = FakeConnection(
        list_response=[b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Other"']
    )
    with ImapClient(
        settings(), connection_factory=lambda _settings, _context: connection
    ) as client:
        assert client.list_mailboxes() == ("INBOX",)

    assert connection.logged_out


def test_client_rejects_unallowed_mailboxes_and_invalid_uid() -> None:
    """check mailbox policy and positive UID validation run before fetch"""
    connection = FakeConnection()
    with ImapClient(
        settings(), connection_factory=lambda _settings, _context: connection
    ) as client:
        with pytest.raises(MailboxNotAllowedError):
            client.fetch_rfc822("Other", 1, 101)
        with pytest.raises(MessageNotFoundError):
            client.fetch_rfc822("INBOX", 0, 101)


def test_search_values_are_quoted_and_control_characters_are_rejected() -> None:
    """check search values remain one quoted argument and reject controls"""
    criteria = _search_criteria('two "words"', "sender@example.test", None, None, None, False, None)

    assert criteria == ("ALL", "TEXT", '"two \\"words\\""', "FROM", '"sender@example.test"')
    with pytest.raises(ValueError, match="control characters"):
        _search_criteria("unsafe\r\nquery", None, None, None, None, False, None)
