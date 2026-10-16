"""exercise batched UID header responses, identities, flags and bounded payloads"""

from __future__ import annotations

import io
from typing import Any

import pytest
from test_imap_client import FakeConnection, settings

from imap_mcp.errors import ImapConnectionError, MessageNotFoundError
from imap_mcp.imap_client import ImapClient, LimitedIMAP4, LimitedIMAP4SSL


class BatchConnection(FakeConnection):
    """return deliberately reordered headers with flags on either side of literals"""

    responses: list[Any] = [
        (b"1 (UID 11 FLAGS (\\Seen) BODY[HEADER] {3}", b"old"),
        b")",
        (b"3 (BODY[HEADER] {3}", b"new"),
        b" UID 33 FLAGS ())",
        (b"2 (UID 22 FLAGS (\\Seen) BODY[HEADER] {3}", b"mid"),
        b")",
    ]

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        self.uid_calls.append((command, args))
        if command == "SEARCH":
            return "OK", [b"11 22 33"]
        return "OK", self.responses


def search(connection: FakeConnection) -> tuple[Any, ...]:
    """run the real client through the synthetic wire boundary"""
    with ImapClient(settings(), connection_factory=lambda *_: connection) as client:
        return client.search_headers(
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


def test_search_batches_uids_and_restores_order_and_flags() -> None:
    """catch per-message fetches, response-order assumptions and lost trailing metadata"""
    connection = BatchConnection()
    headers = search(connection)
    assert [(h.uid, h.raw_headers, h.is_unread, h.uidvalidity) for h in headers] == [
        (33, b"new", True, 101),
        (22, b"mid", False, 101),
        (11, b"old", False, 101),
    ]
    assert connection.uid_calls == [
        ("SEARCH", (None, "ALL")),
        (
            "FETCH",
            (
                "33,22,11",
                "(UID FLAGS BODY.PEEK[HEADER.FIELDS "
                "(FROM TO CC SUBJECT DATE MESSAGE-ID)]<0.65537>)",
            ),
        ),
    ]
    assert connection.selected == [('"INBOX"', True)]


def test_missing_requested_header_fails_instead_of_ending_pagination() -> None:
    """catch silently incomplete pages when messages disappear during a search"""
    connection = BatchConnection()
    connection.responses = BatchConnection.responses[:2]
    with pytest.raises(MessageNotFoundError):
        search(connection)


@pytest.mark.parametrize("metadata", [b"3 (FLAGS ()", b"3 (UID 33", b"3 (UID nope FLAGS ()"])
def test_malformed_metadata_does_not_produce_a_search_result(metadata: bytes) -> None:
    """catch guessing identity or unread state from malformed FETCH metadata"""
    connection = BatchConnection()
    connection.responses = [(metadata, b"header"), b")"]
    with pytest.raises(ImapConnectionError):
        search(connection)


def test_unrequested_headers_are_not_returned() -> None:
    """catch unsolicited FETCH records leaking into the requested result page"""
    connection = BatchConnection()
    connection.responses = [
        *BatchConnection.responses,
        (b"4 (UID 44 FLAGS () BODY[HEADER] {5}", b"extra"),
        b")",
    ]
    assert [header.uid for header in search(connection)] == [33, 22, 11]


def test_unsolicited_flags_do_not_change_the_previous_messages_unread_state() -> None:
    """catch attaching an unrelated flags-only response to a prior header literal"""
    connection = BatchConnection()
    connection.responses = [
        *BatchConnection.responses[:2], b"4 (UID 44 FLAGS ())",
        *BatchConnection.responses[2:],
    ]
    assert [(h.uid, h.is_unread) for h in search(connection)] == [
        (33, True), (22, False), (11, False),
    ]


def test_duplicate_uid_does_not_overwrite_another_header() -> None:
    """catch conflicting duplicate FETCH records silently replacing a result"""
    connection = BatchConnection()
    connection.responses = [*BatchConnection.responses, *BatchConnection.responses[:2]]
    with pytest.raises(ImapConnectionError, match="duplicate"):
        search(connection)


def test_no_matches_does_not_issue_fetch() -> None:
    """catch an empty UID set becoming an invalid or overly broad fetch"""

    class EmptyConnection(BatchConnection):
        def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
            self.uid_calls.append((command, args))
            return "OK", [b""]

    connection = EmptyConnection()
    assert search(connection) == ()
    assert connection.uid_calls == [("SEARCH", (None, "ALL"))]


@pytest.mark.parametrize("connection_type", [LimitedIMAP4, LimitedIMAP4SSL])
def test_aggregate_literal_budget_stops_read_before_allocation(connection_type: Any) -> None:
    """catch batching allowing many individually valid literals past the total budget"""
    connection = connection_type.__new__(connection_type)
    connection.maximum = 10
    connection.remaining = 6
    connection.file = io.BytesIO(b"abcdefmore")
    assert connection.read(4) == b"abcd"
    with pytest.raises(OSError, match="aggregate"):
        connection.read(3)
    assert connection.file.tell() == 4
