"""verify IMAP wire boundaries and mailbox version identity across fetch flows
exercise stale cursors, literal limits, Unicode searches, and aggregate header caps
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from test_imap_client import FakeConnection, settings

from imap_mcp.imap_client import ImapClient


class WireFixture(FakeConnection):
    """record selected mailbox versions and bounded search or fetch responses"""

    literal: bytes | None = None
    validity: bytes = b"101"
    declared_size = 3

    def response(self, code: str) -> tuple[str, list[bytes]]:
        """return the fixture UIDVALIDITY and verify the requested response code"""
        assert code == "UIDVALIDITY"
        return code, [self.validity]

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        """record the command and respond to search, size, or bounded body fetch"""
        self.uid_calls.append((command, args))
        if command == "SEARCH":
            return "OK", [b"42"]
        if args[-1] == "(RFC822.SIZE)":
            return "OK", [f"1 (UID 42 RFC822.SIZE {self.declared_size})".encode()]
        return "OK", [(b"1 (UID 42 BODY[] {3}", b"abc"), b")"]


def test_stale_uidvalidity_rejected_before_message_fetch() -> None:
    """check a changed mailbox version prevents reuse of an old search result"""
    conn = WireFixture()
    with ImapClient(settings(), connection_factory=lambda *_: conn) as client:
        with pytest.raises(ValueError, match="mailbox changed"):
            client.fetch_rfc822("INBOX", 42, 100)
    assert conn.uid_calls == []


def test_declared_oversize_never_downloads_body() -> None:
    """check declared message size is rejected before the body fetch"""
    conn = WireFixture()
    conn.declared_size = 100
    config = settings()
    config = replace(config, limits=replace(config.limits, max_message_bytes=10))
    with ImapClient(config, connection_factory=lambda *_: conn) as client:
        with pytest.raises(ValueError, match="size limit"):
            client.fetch_rfc822("INBOX", 42, 101)
    assert conn.uid_calls == [("FETCH", ("42", "(RFC822.SIZE)"))]


def test_body_download_is_a_bounded_peek_even_when_size_claim_is_small() -> None:
    """check body retrieval remains capped and uses a read-only selection"""
    conn = WireFixture()
    config = settings()
    config = replace(config, limits=replace(config.limits, max_message_bytes=10))
    with ImapClient(config, connection_factory=lambda *_: conn) as client:
        assert client.fetch_rfc822("INBOX", 42, 101) == b"abc"
    assert conn.uid_calls[-1] == ("FETCH", ("42", "(BODY.PEEK[]<0.11>)"))
    assert conn.selected == [('"INBOX"', True)]


def test_unicode_search_is_a_literal_and_identity_includes_uidvalidity() -> None:
    """check UTF-8 search values use literals and results retain mailbox version"""
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
    """check the IMAP reader rejects an oversized literal before consuming bytes"""
    import io

    from imap_mcp.imap_client import LimitedIMAP4

    conn = LimitedIMAP4.__new__(LimitedIMAP4)
    conn.maximum = 10
    conn.file = io.BytesIO(b"0123456789over")
    with pytest.raises(OSError, match="literal exceeds"):
        conn.read(11)
    assert conn.file.tell() == 0


def test_operation_limit_and_release_on_login_failure() -> None:
    """check concurrent sessions are capped and failed login releases its slot"""
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
        """raise a synthetic authentication failure for each connection attempt"""
        raise imaplib.IMAP4.error("synthetic login error")

    for _ in range(3):
        with pytest.raises(ImapAuthenticationError):
            with ImapClient(config, connection_factory=failed):
                pytest.fail("failed login was accepted")


def test_search_headers_have_a_separate_partial_fetch_and_size_boundary() -> None:
    """check header retrieval uses its own partial fetch size limit"""

    class HeaderBomb(WireFixture):
        """return an oversized header literal after a normal search response"""

        def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
            """record the request and return an oversized header body"""
            self.uid_calls.append((command, args))
            if command == "SEARCH":
                return "OK", [b"42"]
            return "OK", [(b"1 (UID 42 BODY[HEADER] {65537}", b"x" * 65537)]

    conn = HeaderBomb()
    with ImapClient(settings(), connection_factory=lambda *_: conn) as client:
        with pytest.raises(ValueError, match="header.*limit"):
            client.search_headers(
                "INBOX",
                query=None,
                sender=None,
                subject=None,
                after_date=None,
                before_date=None,
                unread_only=False,
                before_uid=None,
                maximum=25,
            )
    assert conn.uid_calls[-1][1][-1] == (
        "(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)]<0.65537> FLAGS)"
    )
    assert conn.maximum == 65537


def test_mailbox_with_spaces_is_one_quoted_imap_argument() -> None:
    """check mailbox names with spaces stay one quoted select argument"""
    conn = WireFixture()
    config = replace(settings(), allowed_mailboxes=("Sent Messages",))
    with ImapClient(config, connection_factory=lambda *_: conn) as client:
        assert client.fetch_rfc822("Sent Messages", 42, 101) == b"abc"
    assert conn.selected == [('"Sent Messages"', True)]


def test_unicode_mailbox_names_use_modified_utf7_and_list_roundtrips() -> None:
    """check modified UTF-7 mailbox encoding and decoding round-trip"""
    from imap_mcp.imap_client import _encode_mailbox, _mailbox_name

    assert _encode_mailbox("台北 & Archive") == "&U,BTFw- &- Archive"
    assert _mailbox_name(b'(\\HasNoChildren) "/" "&U,BTFw- &- Archive"') == "台北 & Archive"


def test_search_retained_headers_have_an_aggregate_budget() -> None:
    """check many valid-sized headers still obey the aggregate response cap"""

    class HeaderPage(WireFixture):
        """return many search UIDs and one maximum-sized header per fetch"""

        def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
            """record search and header requests with fixture responses"""
            self.uid_calls.append((command, args))
            if command == "SEARCH":
                return "OK", [b" ".join(str(i).encode() for i in range(1, 101))]
            return "OK", [(b"1 (UID 1 BODY[HEADER] {65536}", b"x" * 65536)]

    conn = HeaderPage()
    with ImapClient(settings(), connection_factory=lambda *_: conn) as client:
        with pytest.raises(ValueError, match="aggregate size limit"):
            client.search_headers(
                "INBOX",
                query=None,
                sender=None,
                subject=None,
                after_date=None,
                before_date=None,
                unread_only=False,
                before_uid=None,
                maximum=100,
            )
