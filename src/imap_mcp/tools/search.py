"""validate search filters and shape bounded message metadata pages
use ImapClient for server search and mime_parser for normalized header values
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Protocol, TypedDict

from pydantic import Field

from ..config import Settings
from ..imap_client import ImapClient, MessageHeader
from ..mime_parser import parse_headers


class SearchMessage(TypedDict):
    """describe one compact result keyed by mailbox and UID"""

    uid: int
    uidvalidity: int
    subject: str
    sender: str
    recipients: list[str]
    date: str
    is_unread: bool


class SearchMessagesResult(TypedDict):
    """describe one bounded result page and its optional older-results cursor"""

    messages: list[SearchMessage]
    next_before_uid: int | None


class SearchSession(Protocol):
    """describe the session behavior needed for a bounded header search"""

    def __enter__(self) -> SearchSession:
        """open the search session"""
        ...

    def __exit__(self, *_: object) -> None:
        """close the search session after collecting its page"""
        ...

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
    ) -> tuple[MessageHeader, ...]:
        """search the selected mailbox and return bounded raw headers"""
        ...


SearchClientFactory = Callable[[Settings], SearchSession]


def make_search_messages(
    settings: Settings, client_factory: SearchClientFactory = ImapClient
) -> Callable[..., SearchMessagesResult]:
    """create a search tool whose caller input cannot raise configured limits"""

    def search_messages(
        mailbox: Annotated[
            str,
            Field(
                description="Allowed folder name, e.g. INBOX; discover others with list_mailboxes."
            ),
        ],
        query: Annotated[
            str | None,
            Field(
                description="Literal text searched in headers and body; not Gmail or IMAP syntax."
            ),
        ] = None,
        sender: Annotated[
            str | None, Field(description="Text to match in the From header.")
        ] = None,
        subject: Annotated[
            str | None, Field(description="Text to match in the Subject header.")
        ] = None,
        after_date: Annotated[
            str | None,
            Field(description="Inclusive start of internal mail date range, YYYY-MM-DD."),
        ] = None,
        before_date: Annotated[
            str | None,
            Field(description="Exclusive end of internal mail date range, YYYY-MM-DD."),
        ] = None,
        unread_only: Annotated[
            bool,
            Field(description="Only unseen messages when true; searches do not mark mail read."),
        ] = False,
        limit: Annotated[
            int,
            Field(description="Page size, default 25; clamped to 1 through the server result cap."),
        ] = 25,
        before_uid: Annotated[
            int | None,
            Field(
                description=(
                    "Use next_before_uid from the last page; "
                    "keep the same mailbox and filters."
                )
            ),
        ] = None,
    ) -> SearchMessagesResult:
        """search one allowed mailbox and return compact metadata newest first"""
        clean_query = _bounded_text(query, settings.limits.max_query_length, "query")
        clean_sender = _bounded_text(sender, settings.limits.max_query_length, "sender")
        clean_subject = _bounded_text(subject, settings.limits.max_query_length, "subject")
        if before_uid is not None and before_uid < 2:
            raise ValueError("before_uid must be at least 2")
        # parse dates before opening a session so invalid ranges never reach IMAP
        parsed_after_date = _parse_date(after_date, "after_date")
        parsed_before_date = _parse_date(before_date, "before_date")
        if (
            parsed_after_date is not None
            and parsed_before_date is not None
            and parsed_after_date >= parsed_before_date
        ):
            raise ValueError("after_date must be earlier than before_date")
        # clamp caller paging to the server cap before asking ImapClient for results
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
            # a full page may have older results, so its last UID becomes the next cursor
            next_before_uid = headers[-1].uid if len(headers) == maximum else None
            return {"messages": messages, "next_before_uid": next_before_uid}

    return search_messages


def _bounded_text(value: str | None, maximum: int, name: str) -> str | None:
    """trim optional search text and enforce the configured query length"""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds the configured query length limit")
    return value


def _parse_date(value: str | None, name: str) -> date | None:
    """parse an ISO date or return no filter when the caller omitted it"""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD format") from exc


def _summary(header: MessageHeader) -> SearchMessage:
    """normalize one fetched header through mime_parser and retain its UID metadata"""
    parsed = parse_headers(header.raw_headers)
    return {
        "uid": header.uid,
        "uidvalidity": header.uidvalidity,
        "subject": parsed.subject,
        "sender": parsed.sender,
        "recipients": list(parsed.recipients),
        "date": parsed.date,
        "is_unread": header.is_unread,
    }
