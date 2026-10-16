"""Bounded, read-only message search MCP tool."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Protocol, TypedDict

from ..config import Settings
from ..imap_client import ImapClient, MessageHeader
from ..mime_parser import parse_headers


class SearchMessage(TypedDict):
    """Compact message metadata keyed by the stable mailbox plus UID identity."""

    uid: int
    subject: str
    sender: str
    recipients: list[str]
    date: str
    is_unread: bool


class SearchMessagesResult(TypedDict):
    """Bounded page of metadata and a cursor for older results."""

    messages: list[SearchMessage]
    next_before_uid: int | None


class SearchSession(Protocol):
    """Read-only IMAP behavior needed to implement bounded search."""

    def __enter__(self) -> SearchSession: ...

    def __exit__(self, *_: object) -> None: ...

    def search_headers(
        self,
        mailbox: str,
        *,
        query: str | None,
        sender: str | None,
        subject: str | None,
        after_date: date | None,
        before_date: date | None,
        unread_only: bool,
        before_uid: int | None,
        maximum: int,
    ) -> tuple[MessageHeader, ...]: ...


SearchClientFactory = Callable[[Settings], SearchSession]


def make_search_messages(
    settings: Settings, client_factory: SearchClientFactory = ImapClient
) -> Callable[..., SearchMessagesResult]:
    """Create a search tool whose caller input cannot override configured limits."""

    def search_messages(
        mailbox: str,
        query: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        after_date: str | None = None,
        before_date: str | None = None,
        unread_only: bool = False,
        limit: int = 25,
        before_uid: int | None = None,
    ) -> SearchMessagesResult:
        """Search one allowed mailbox and return compact metadata only, newest first."""
        clean_query = _bounded_text(query, settings.limits.max_query_length, "query")
        clean_sender = _bounded_text(sender, settings.limits.max_query_length, "sender")
        clean_subject = _bounded_text(subject, settings.limits.max_query_length, "subject")
        if before_uid is not None and before_uid < 2:
            raise ValueError("before_uid must be at least 2")
        parsed_after_date = _parse_date(after_date, "after_date")
        parsed_before_date = _parse_date(before_date, "before_date")
        if (
            parsed_after_date is not None
            and parsed_before_date is not None
            and parsed_after_date >= parsed_before_date
        ):
            raise ValueError("after_date must be earlier than before_date")
        maximum = min(max(limit, 1), settings.limits.max_results)
        with client_factory(settings) as client:
            headers = client.search_headers(
                mailbox,
                query=clean_query,
                sender=clean_sender,
                subject=clean_subject,
                after_date=parsed_after_date,
                before_date=parsed_before_date,
                unread_only=unread_only,
                before_uid=before_uid,
                maximum=maximum,
            )
        messages = [_summary(header) for header in headers]
        next_before_uid = headers[-1].uid if len(headers) == maximum else None
        return {"messages": messages, "next_before_uid": next_before_uid}

    return search_messages


def _bounded_text(value: str | None, maximum: int, name: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds the configured query length limit")
    return value


def _parse_date(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD format") from exc


def _summary(header: MessageHeader) -> SearchMessage:
    parsed = parse_headers(header.raw_headers)
    return {
        "uid": header.uid,
        "subject": parsed.subject,
        "sender": parsed.sender,
        "recipients": list(parsed.recipients),
        "date": parsed.date,
        "is_unread": header.is_unread,
    }
