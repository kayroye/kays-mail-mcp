"""Small, strictly read-only IMAP transport layer."""

from __future__ import annotations

import imaplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from .config import Settings, TlsMode
from .errors import (
    ImapAuthenticationError,
    ImapConnectionError,
    MailboxNotAllowedError,
    MailboxNotFoundError,
    MessageNotFoundError,
)


class ImapConnection(Protocol):
    """Subset of IMAP commands allowed by this read-only transport."""

    def login(self, user: str, password: str) -> tuple[str, Any]: ...

    def logout(self) -> tuple[str, Any]: ...

    def list(self) -> tuple[str, Any]: ...

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, Any]: ...

    def uid(self, command: str, *args: Any) -> tuple[str, Any]: ...


ConnectionFactory = Callable[[Settings, ssl.SSLContext], ImapConnection]


@dataclass(frozen=True, slots=True)
class MessageHeader:
    """A UID and RFC822 header block returned by a read-only search."""

    uid: int
    raw_headers: bytes
    is_unread: bool


class ImapClient:
    """Authenticated IMAP session limited to list, readonly select, and UID fetch."""

    def __init__(
        self, settings: Settings, connection_factory: ConnectionFactory | None = None
    ) -> None:
        self._settings = settings
        self._connection_factory = connection_factory or _open_connection
        self._connection: ImapConnection | None = None

    def __enter__(self) -> ImapClient:
        context = ssl.create_default_context()
        try:
            connection = self._connection_factory(self._settings, context)
            connection.login(self._settings.username, self._settings.password)
        except imaplib.IMAP4.error:
            raise ImapAuthenticationError("IMAP authentication failed") from None
        except (OSError, ssl.SSLError):
            raise ImapConnectionError("verified IMAP TLS connection failed") from None
        self._connection = connection
        return self

    def __exit__(self, *_: object) -> None:
        if self._connection is None:
            return
        try:
            self._connection.logout()
        except (OSError, imaplib.IMAP4.error):
            pass
        finally:
            self._connection = None

    def list_mailboxes(self) -> tuple[str, ...]:
        """List only configured, existing mailboxes using their IMAP names as stable IDs."""
        connection = self._require_connection()
        try:
            status, responses = connection.list()
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to list IMAP mailboxes") from None
        if status != "OK":
            raise ImapConnectionError("unable to list IMAP mailboxes")

        available = {_mailbox_name(response) for response in responses if response is not None}
        return tuple(
            mailbox for mailbox in self._settings.allowed_mailboxes if mailbox in available
        )

    def fetch_rfc822(self, mailbox: str, uid: int) -> bytes:
        """Fetch one message by UID after selecting its mailbox read-only."""
        if uid < 1:
            raise MessageNotFoundError("message UID was not found")
        self._select_readonly(mailbox)
        connection = self._require_connection()
        try:
            status, responses = connection.uid("FETCH", str(uid), "(BODY.PEEK[])")
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to retrieve IMAP message") from None
        if status != "OK":
            raise MessageNotFoundError("message UID was not found")

        for response in responses:
            if isinstance(response, tuple) and len(response) > 1 and isinstance(response[1], bytes):
                return response[1]
        raise MessageNotFoundError("message UID was not found")

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
        """Search by UID and retrieve only compact headers for a server-bounded result set."""
        self._select_readonly(mailbox)
        criteria = _search_criteria(
            query, sender, subject, after_date, before_date, unread_only, before_uid
        )
        connection = self._require_connection()
        try:
            status, responses = connection.uid("SEARCH", None, *criteria)
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to search IMAP mailbox") from None
        if status != "OK":
            raise ImapConnectionError("unable to search IMAP mailbox")
        uids = _uids_from_search(responses)
        return tuple(self._fetch_header(uid) for uid in reversed(uids[-maximum:]))

    def _fetch_header(self, uid: int) -> MessageHeader:
        connection = self._require_connection()
        try:
            status, responses = connection.uid(
                "FETCH",
                str(uid),
                "(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)] FLAGS)",
            )
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to retrieve IMAP message headers") from None
        if status != "OK":
            raise MessageNotFoundError("message UID was not found")
        for response in responses:
            if isinstance(response, tuple) and len(response) > 1 and isinstance(response[1], bytes):
                flags = response[0] if isinstance(response[0], bytes) else b""
                return MessageHeader(uid, response[1], b"\\Seen" not in flags)
        raise MessageNotFoundError("message UID was not found")

    def _select_readonly(self, mailbox: str) -> None:
        if mailbox not in self._settings.allowed_mailboxes:
            raise MailboxNotAllowedError("mailbox is not allowed")
        connection = self._require_connection()
        try:
            status, _ = connection.select(mailbox, readonly=True)
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to select IMAP mailbox") from None
        if status != "OK":
            raise MailboxNotFoundError("mailbox was not found")

    def _require_connection(self) -> ImapConnection:
        if self._connection is None:
            raise ImapConnectionError("IMAP session is not connected")
        return self._connection


def _open_connection(settings: Settings, context: ssl.SSLContext) -> ImapConnection:
    if settings.tls_mode is TlsMode.IMPLICIT_TLS:
        return imaplib.IMAP4_SSL(
            settings.host,
            settings.port,
            ssl_context=context,
            timeout=settings.limits.timeout_seconds,
        )

    connection = imaplib.IMAP4(
        settings.host, settings.port, timeout=settings.limits.timeout_seconds
    )
    connection.starttls(ssl_context=context)
    return connection


def _mailbox_name(response: bytes) -> str:
    """Extract the mailbox token from an IMAP LIST response without executing it."""
    decoded = response.decode("utf-8", errors="replace").rstrip()
    if '"' in decoded:
        return decoded.rsplit('"', maxsplit=2)[-2]
    return decoded.rsplit(" ", maxsplit=1)[-1]


def _search_criteria(
    query: str | None,
    sender: str | None,
    subject: str | None,
    after_date: date | None,
    before_date: date | None,
    unread_only: bool,
    before_uid: int | None,
) -> tuple[str, ...]:
    criteria: list[str] = ["ALL"]
    if before_uid is not None:
        criteria.extend(("UID", f"1:{before_uid - 1}"))
    if unread_only:
        criteria.append("UNSEEN")
    if query:
        criteria.extend(("TEXT", _quote_search_value(query)))
    if sender:
        criteria.extend(("FROM", _quote_search_value(sender)))
    if subject:
        criteria.extend(("SUBJECT", _quote_search_value(subject)))
    if after_date:
        criteria.extend(("SINCE", _imap_date(after_date)))
    if before_date:
        criteria.extend(("BEFORE", _imap_date(before_date)))
    return tuple(criteria)


def _quote_search_value(value: str) -> str:
    """Encode one bounded user value as a single safe IMAP quoted string."""
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise ValueError("search values must not contain control characters")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("search values currently support ASCII characters only") from exc
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def _uids_from_search(responses: list[object]) -> tuple[int, ...]:
    values: list[int] = []
    for response in responses:
        if isinstance(response, bytes):
            values.extend(
                int(token) for token in response.split() if token.isdigit() and int(token) > 0
            )
    return tuple(values)
