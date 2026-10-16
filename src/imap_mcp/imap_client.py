"""provide a bounded read-only IMAP transport for mailbox and message tools
use validated settings and return raw message data for normalization by mime_parser
"""

from __future__ import annotations

import base64
import imaplib
import re
import shlex
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from threading import BoundedSemaphore
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
    """describe the small command surface used by the read-only client"""

    literal: Any
    maximum: int

    def response(self, code: str) -> tuple[str, Any]:
        """read one server response value such as UIDVALIDITY"""
        ...

    def login(self, user: str, password: str) -> tuple[str, Any]:
        """authenticate the current connection"""
        ...

    def logout(self) -> tuple[str, Any]:
        """close the authenticated connection"""
        ...

    def list(self) -> tuple[str, Any]:
        """list server mailboxes before applying the configured allowlist"""
        ...

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, Any]:
        """select a mailbox with the caller's requested read-only mode"""
        ...

    def uid(self, command: str, *args: Any) -> tuple[str, Any]:
        """issue one UID-scoped search or fetch command"""
        ...


ConnectionFactory = Callable[[Settings, ssl.SSLContext], ImapConnection]


@dataclass(frozen=True, slots=True)
class MessageHeader:
    """hold one search result header and the mailbox version used to fetch it"""

    uid: int
    raw_headers: bytes
    is_unread: bool
    uidvalidity: int = 0


class ImapClient:
    """manage one authenticated session with only list, readonly select, and UID fetch"""

    def __init__(
        self, settings: Settings, connection_factory: ConnectionFactory | None = None
    ) -> None:
        """bind validated settings and a testable connection factory to this session"""
        self._settings = settings
        self._connection_factory = connection_factory or _open_connection
        self._connection: ImapConnection | None = None
        self._uidvalidity = 0
        self._gate = _operation_gate(settings.limits.max_concurrent_operations)
        self._acquired = False

    def __enter__(self) -> ImapClient:
        """acquire a shared operation slot before opening and authenticating a session"""
        context = ssl.create_default_context()
        if not self._gate.acquire(timeout=self._settings.limits.timeout_seconds):
            raise ImapConnectionError("IMAP operation limit reached; retry later")
        self._acquired = True
        connection: ImapConnection | None = None
        try:
            # keep a partial connection available for cleanup if login fails
            connection = self._connection_factory(self._settings, context)
            connection.login(self._settings.username, self._settings.password)
        except BaseException as exc:
            if connection is not None:
                try:
                    connection.logout()
                except (OSError, imaplib.IMAP4.error):
                    pass
            self._release()
            if isinstance(exc, imaplib.IMAP4.error):
                raise ImapAuthenticationError("IMAP authentication failed") from None
            if isinstance(exc, OSError):
                raise ImapConnectionError("verified IMAP TLS connection failed") from None
            raise
        self._connection = connection
        return self

    def __exit__(self, *_: object) -> None:
        """close the session and release its shared operation slot on every exit"""
        if self._connection is None:
            return
        try:
            self._connection.logout()
        except (OSError, imaplib.IMAP4.error):
            pass
        finally:
            self._connection = None
            self._release()

    def list_mailboxes(self) -> tuple[str, ...]:
        """return only allowlisted mailboxes that the server reports as existing"""
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

    def _release(self) -> None:
        """release the semaphore once even when setup and cleanup both reach this path"""
        if self._acquired:
            self._acquired = False
            self._gate.release()

    def fetch_rfc822(self, mailbox: str, uid: int, uidvalidity: int) -> bytes:
        """fetch one size-checked message by UID from a read-only mailbox selection"""
        if uid < 1:
            raise MessageNotFoundError("message UID was not found")
        self._select_readonly(mailbox)
        # a changed UIDVALIDITY makes search results unsafe to reuse for retrieval
        if uidvalidity != self._uidvalidity or uidvalidity < 1:
            raise ValueError("mailbox changed; search again before retrieving this message")
        connection = self._require_connection()
        maximum = self._settings.limits.max_message_bytes
        # ask imaplib to reject oversized literals before accepting the payload
        connection.maximum = maximum + 1
        try:
            size_status, sizes = connection.uid("FETCH", str(uid), "(RFC822.SIZE)")
            size_data = b" ".join(item for item in sizes if isinstance(item, bytes))
            match = re.search(rb"RFC822.SIZE (\d+)", size_data)
            if size_status != "OK" or match is None:
                raise MessageNotFoundError("message size was not available")
            if int(match[1]) > maximum:
                raise ValueError("message exceeds the configured size limit")
            status, responses = connection.uid("FETCH", str(uid), f"(BODY.PEEK[]<0.{maximum + 1}>)")
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to retrieve IMAP message") from None
        if status != "OK":
            raise MessageNotFoundError("message UID was not found")

        for response in responses:
            if isinstance(response, tuple) and len(response) > 1 and isinstance(response[1], bytes):
                if len(response[1]) > maximum:
                    raise ValueError("message exceeds the configured size limit")
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
        """search by UID and fetch bounded headers for the newest matching results"""
        self._select_readonly(mailbox)
        # use server-side ASCII criteria first, then intersect UTF-8 matches when needed
        unicode_search = any(value and not value.isascii() for value in (query, sender, subject))
        criteria = _search_criteria(
            None if unicode_search else query,
            None if unicode_search else sender,
            None if unicode_search else subject,
            after_date,
            before_date,
            unread_only,
            before_uid,
        )
        connection = self._require_connection()
        try:
            status, responses = connection.uid("SEARCH", None, *criteria)
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to search IMAP mailbox") from None
        if status != "OK":
            raise ImapConnectionError("unable to search IMAP mailbox")
        uids = _uids_from_search(responses)
        if unicode_search:
            for field, value in (("TEXT", query), ("FROM", sender), ("SUBJECT", subject)):
                if value:
                    _quote_search_value(value)
                    connection.literal = value.encode("utf-8")
                    try:
                        extra_status, extra = connection.uid("SEARCH", "CHARSET", "UTF-8", field)
                    except (OSError, imaplib.IMAP4.error):
                        raise ImapConnectionError("UTF-8 search failed") from None
                    if extra_status != "OK":
                        raise ImapConnectionError("mail provider did not accept UTF-8 search")
                    matching = set(_uids_from_search(extra))
                    uids = tuple(uid for uid in uids if uid in matching)
        headers = []
        total_bytes = 0
        # fetch newest UIDs first while enforcing an aggregate cap across all headers
        for uid in reversed(uids[-maximum:]):
            header = self._fetch_header(uid)
            total_bytes += len(header.raw_headers)
            if total_bytes > 4_194_304:
                raise ValueError("search headers exceed aggregate size limit; reduce result count")
            headers.append(header)
        return tuple(headers)

    def _fetch_header(self, uid: int) -> MessageHeader:
        """fetch the fixed header allowlist and attach current mailbox version metadata"""
        connection = self._require_connection()
        connection.maximum = 65_537
        try:
            status, responses = connection.uid(
                "FETCH",
                str(uid),
                "(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)]<0.65537> FLAGS)",
            )
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to retrieve IMAP message headers") from None
        if status != "OK":
            raise MessageNotFoundError("message UID was not found")
        for response in responses:
            if isinstance(response, tuple) and len(response) > 1 and isinstance(response[1], bytes):
                if len(response[1]) > 65_536:
                    raise ValueError("message header exceeds size limit")
                flags = response[0] if isinstance(response[0], bytes) else b""
                return MessageHeader(uid, response[1], b"\\Seen" not in flags, self._uidvalidity)
        raise MessageNotFoundError("message UID was not found")

    def _select_readonly(self, mailbox: str) -> None:
        """enforce the configured allowlist and refresh UIDVALIDITY on read-only selection"""
        if mailbox not in self._settings.allowed_mailboxes:
            raise MailboxNotAllowedError("mailbox is not allowed")
        connection = self._require_connection()
        try:
            status, _ = connection.select(
                _quote_search_value(_encode_mailbox(mailbox)), readonly=True
            )
        except (OSError, imaplib.IMAP4.error):
            raise ImapConnectionError("unable to select IMAP mailbox") from None
        if status != "OK":
            raise MailboxNotFoundError("mailbox was not found")
        _, validity = connection.response("UIDVALIDITY")
        if not validity or not isinstance(validity[0], bytes) or not validity[0].isdigit():
            raise ImapConnectionError("mailbox did not provide a valid UIDVALIDITY")
        self._uidvalidity = int(validity[0])
        if self._uidvalidity < 1:
            raise ImapConnectionError("mailbox did not provide a valid UIDVALIDITY")

    def _require_connection(self) -> ImapConnection:
        """return the active connection or fail before issuing an IMAP command"""
        if self._connection is None:
            raise ImapConnectionError("IMAP session is not connected")
        return self._connection


def _open_connection(settings: Settings, context: ssl.SSLContext) -> ImapConnection:
    """open the configured implicit TLS or verified STARTTLS connection"""
    if settings.tls_mode is TlsMode.IMPLICIT_TLS:
        return LimitedIMAP4SSL(
            settings.host,
            settings.port,
            maximum=settings.limits.max_message_bytes + 1,
            ssl_context=context,
            timeout=settings.limits.timeout_seconds,
        )

    connection = LimitedIMAP4(
        settings.host,
        settings.port,
        maximum=settings.limits.max_message_bytes + 1,
        timeout=settings.limits.timeout_seconds,
    )
    connection.starttls(ssl_context=context)
    return connection


def _encode_mailbox(value: str) -> str:
    """encode mailbox names as modified UTF-7 independently of search charset"""

    def encoded(match: re.Match[str]) -> str:
        """encode one non-ASCII run and apply modified UTF-7 substitutions"""
        payload = base64.b64encode(match[0].encode("utf-16-be")).decode().rstrip("=")
        return "&" + payload.replace("/", ",") + "-"

    return re.sub(r"[^\x20-\x7e]+", encoded, value.replace("&", "&-"))


def _mailbox_name(response: bytes | tuple[bytes, bytes]) -> str:
    """decode quoted or literal LIST names without treating their contents as commands"""
    try:
        encoded = (
            response[1].decode("ascii")
            if isinstance(response, tuple)
            else shlex.split(response.decode("ascii"))[-1]
        )

        def decoded(match: re.Match[str]) -> str:
            """decode one modified UTF-7 run from the server mailbox name"""
            payload = match[1].replace(",", "/")
            return (
                (
                    base64.b64decode(payload + "=" * (-len(payload) % 4), validate=True).decode(
                        "utf-16-be"
                    )
                )
                if payload
                else "&"
            )

        return re.sub(r"&([A-Za-z0-9+,]*)-", decoded, encoded)
    except (ValueError, UnicodeError, IndexError):
        raise ImapConnectionError("mail provider returned an invalid mailbox name") from None


def _search_criteria(
    query: str | None,
    sender: str | None,
    subject: str | None,
    after_date: date | None,
    before_date: date | None,
    unread_only: bool,
    before_uid: int | None,
) -> tuple[str, ...]:
    """build IMAP criteria from validated filters and an optional UID cursor"""
    criteria: list[str] = ["ALL"]
    if before_uid is not None:
        # exclude the cursor UID itself so each subsequent page moves backward
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
    """escape one bounded user value as a single safe IMAP quoted string"""
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise ValueError("search values must not contain control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_date(value: date) -> str:
    """format a date using the month names required by IMAP search criteria"""
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{value.day:02d}-{months[value.month - 1]}-{value.year:04d}"


def _uids_from_search(responses: list[object]) -> tuple[int, ...]:
    """collect positive numeric UIDs from search response byte strings"""
    values: list[int] = []
    for response in responses:
        if isinstance(response, bytes):
            values.extend(
                int(token) for token in response.split() if token.isdigit() and int(token) > 0
            )
    return tuple(values)


@lru_cache(maxsize=8)
def _operation_gate(maximum: int) -> BoundedSemaphore:
    """reuse one process-wide semaphore for each configured concurrency limit"""
    return BoundedSemaphore(maximum)


class LimitedIMAP4SSL(imaplib.IMAP4_SSL):
    """reject oversized server literals before imaplib allocates their payload"""

    def __init__(self, *args: Any, maximum: int, **kwargs: Any) -> None:
        """store the literal bound before initializing the standard TLS client"""
        self.maximum = maximum
        super().__init__(*args, **kwargs)

    def read(self, size: int) -> bytes:
        """enforce the configured literal bound before delegating the read"""
        if size > self.maximum:
            raise OSError("IMAP literal exceeds configured limit")
        return super().read(size)


class LimitedIMAP4(imaplib.IMAP4):
    """apply the same literal boundary to the verified STARTTLS transport"""

    def __init__(self, *args: Any, maximum: int, **kwargs: Any) -> None:
        """store the literal bound before initializing the standard IMAP client"""
        self.maximum = maximum
        super().__init__(*args, **kwargs)

    def read(self, size: int) -> bytes:
        """enforce the configured literal bound before delegating the read"""
        if size > self.maximum:
            raise OSError("IMAP literal exceeds configured limit")
        return super().read(size)
