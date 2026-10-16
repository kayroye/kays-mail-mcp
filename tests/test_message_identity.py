from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from test_imap_client import FakeConnection, settings

from imap_mcp.imap_client import ImapClient


class WireFixture(FakeConnection):
    literal: bytes | None = None
    validity: bytes = b"101"
    declared_size = 3

    def response(self, code: str) -> tuple[str, list[bytes]]:
        assert code == "UIDVALIDITY"
        return code, [self.validity]

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        self.uid_calls.append((command, args))
        if command == "SEARCH":
            return "OK", [b"42"]
        if args[-1] == "(RFC822.SIZE)":
            return "OK", [f"1 (UID 42 RFC822.SIZE {self.declared_size})".encode()]
        return "OK", [(b"1 (UID 42 BODY[] {3}", b"abc"), b")"]


def test_stale_uidvalidity_rejected_before_message_fetch() -> None:
    conn = WireFixture()
    with ImapClient(settings(), connection_factory=lambda *_: conn) as client:
        with pytest.raises(ValueError, match="mailbox changed"):
            client.fetch_rfc822("INBOX", 42, 100)
    assert conn.uid_calls == []


def test_declared_oversize_never_downloads_body() -> None:
    conn = WireFixture()
    conn.declared_size = 100
    config = settings()
    config = replace(config, limits=replace(config.limits, max_message_bytes=10))
    with ImapClient(config, connection_factory=lambda *_: conn) as client:
        with pytest.raises(ValueError, match="size limit"):
            client.fetch_rfc822("INBOX", 42, 101)
    assert conn.uid_calls == [("FETCH", ("42", "(RFC822.SIZE)"))]


def test_body_download_is_a_bounded_peek_even_when_size_claim_is_small() -> None:
    conn = WireFixture()
    config = settings()
    config = replace(config, limits=replace(config.limits, max_message_bytes=10))
    with ImapClient(config, connection_factory=lambda *_: conn) as client:
        assert client.fetch_rfc822("INBOX", 42, 101) == b"abc"
    assert conn.uid_calls[-1] == ("FETCH", ("42", "(BODY.PEEK[]<0.11>)"))
    assert conn.selected == [("INBOX", True)]


def test_unicode_search_is_a_literal_and_identity_includes_uidvalidity() -> None:
    conn = WireFixture()
    with ImapClient(settings(), connection_factory=lambda *_: conn) as client:
        headers = client.search_headers(
            "INBOX",
            query="café",
            sender=None,
            subject=None,
            after_date=None,
            before_date=None,
            unread_only=False,
            before_uid=None,
            maximum=2,
        )
    assert conn.literal == "café".encode()
    assert ("SEARCH", ("CHARSET", "UTF-8", "TEXT")) in conn.uid_calls
    assert headers[0].uidvalidity == 101


def test_wire_literal_rejected_before_reading_any_payload() -> None:
    import io

    from imap_mcp.imap_client import LimitedIMAP4

    conn = LimitedIMAP4.__new__(LimitedIMAP4)
    conn.maximum = 10
    conn.file = io.BytesIO(b"0123456789over")
    with pytest.raises(OSError, match="literal exceeds"):
        conn.read(11)
    assert conn.file.tell() == 0


def test_operation_limit_and_release_on_login_failure() -> None:
    import imaplib

    from imap_mcp.errors import ImapAuthenticationError, ImapConnectionError

    config = settings()
    config = replace(config, limits=replace(config.limits, timeout_seconds=1))
    conn = WireFixture()
    with ImapClient(config, connection_factory=lambda *_: conn):
        with ImapClient(config, connection_factory=lambda *_: WireFixture()):
            with pytest.raises(ImapConnectionError, match="operation limit"):
                with ImapClient(config, connection_factory=lambda *_: WireFixture()):
                    pytest.fail("third operation acquired a slot")

    def failed(*_: object) -> WireFixture:
        raise imaplib.IMAP4.error("synthetic login error")

    for _ in range(3):
        with pytest.raises(ImapAuthenticationError):
            with ImapClient(config, connection_factory=failed):
                pytest.fail("failed login was accepted")
