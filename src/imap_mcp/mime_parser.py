"""normalize email messages into safe metadata and readable body text
keep MIME limits and attachment policy in one place before data reaches tools
"""

from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import Any

from .limits import LimitExceededError, enforce_byte_limit

ALLOWED_ATTACHMENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "text/csv",
        "text/plain",
    }
)


@dataclass(frozen=True, slots=True)
class Attachment:
    """describe an attachment while keeping its bytes out of message results"""

    index: int
    filename: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """collect the normalized headers, safe body text, and attachment inventory"""

    subject: str
    sender: str
    recipients: tuple[str, ...]
    date: str
    message_id: str
    body: str
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True, slots=True)
class ParsedHeaders:
    """collect compact normalized metadata for search results"""

    subject: str
    sender: str
    recipients: tuple[str, ...]
    date: str
    message_id: str


class MimeParseError(ValueError):
    """report a message that cannot be parsed within the safety limits"""


def _bounded_parse(raw: bytes) -> Message:
    # bound raw structure first because parsing builds the tree used by every later step
    if raw.count(b"\n") > 250_000:
        raise MimeParseError("message exceeds physical line limit")
    start = 0
    while start < len(raw):
        end = raw.find(b"\n", start)
        if end == -1:
            end = len(raw)
        if end - start > 1_048_576:
            raise MimeParseError("message exceeds physical line limit")
        start = end + 1
    parts = 0

    def factory(*args: Any, **kwargs: Any) -> EmailMessage:
        # count each part as the parser creates it so oversized MIME trees stop early
        nonlocal parts
        parts += 1
        if parts > 256:
            raise MimeParseError("message exceeds MIME part limit")
        return EmailMessage(*args, **kwargs)

    return BytesParser(_class=factory, policy=policy.default).parsebytes(raw)


def parse_message(raw_message: bytes, *, max_body_bytes: int) -> ParsedMessage:
    """build a safe message result by connecting headers, body text, and attachment metadata"""
    message = _bounded_parse(raw_message)
    body = _body_text(message, max_body_bytes)
    attachments = _attachments(message)
    return ParsedMessage(
        subject=_decode_header(message.get("Subject")),
        sender=_decode_header(message.get("From")),
        recipients=_recipient_values(message),
        date=_decode_header(message.get("Date")),
        message_id=_decode_header(message.get("Message-ID")),
        body=body,
        attachments=attachments,
    )


def parse_headers(raw_message: bytes) -> ParsedHeaders:
    """reuse bounded parsing while extracting only the fields needed for search"""
    message = _bounded_parse(raw_message)
    return ParsedHeaders(
        subject=_decode_header(message.get("Subject")),
        sender=_decode_header(message.get("From")),
        recipients=_recipient_values(message),
        date=_decode_header(message.get("Date")),
        message_id=_decode_header(message.get("Message-ID")),
    )


def attachment_content(
    raw_message: bytes, *, attachment_index: int, max_attachment_bytes: int
) -> tuple[Attachment, bytes]:
    """resolve one indexed part, enforce its type and size, then return its bytes"""
    if attachment_index < 0:
        raise MimeParseError("attachment was not found")
    message = _bounded_parse(raw_message)
    attachments = list(_attachment_parts(message))
    if attachment_index >= len(attachments):
        raise MimeParseError("attachment was not found")

    part = attachments[attachment_index]
    content_type = part.get_content_type().lower()
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise MimeParseError("attachment type is not allowed")
    payload = _decoded_payload(part)
    try:
        enforce_byte_limit(payload, max_attachment_bytes, field="attachment")
    except LimitExceededError as exc:
        raise MimeParseError("attachment exceeds the configured size limit") from exc
    return _attachment_metadata(attachment_index, part, payload), payload


def _body_text(message: Message, max_body_bytes: int) -> str:
    # prefer plain text and fall back to HTML only when no plain alternative exists
    candidates = list(_body_parts(message, "text/plain")) or list(_body_parts(message, "text/html"))
    if not candidates:
        return ""
    payload = _decoded_payload(candidates[0])
    try:
        enforce_byte_limit(payload, max_body_bytes, field="body")
    except LimitExceededError as exc:
        raise MimeParseError("body exceeds the configured size limit") from exc
    charset = candidates[0].get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="replace")
    # convert HTML to inert text before returning it, then normalize both body formats
    if candidates[0].get_content_type().lower() == "text/html":
        return html_to_text(text)
    return _normalise_text(text)


def _body_parts(message: Message, content_type: str) -> list[Message]:
    # exclude named or explicitly attached parts so files never become message bodies
    return [
        part
        for part in message.walk()
        if part.get_content_type().lower() == content_type
        and part.get_content_disposition() != "attachment"
        and not part.get_filename()
    ]


def _attachments(message: Message) -> tuple[Attachment, ...]:
    # keep inventory ordering aligned with attachment_content index lookup
    items: list[Attachment] = []
    for index, part in enumerate(_attachment_parts(message)):
        payload = _decoded_payload(part)
        items.append(_attachment_metadata(index, part, payload))
    return tuple(items)


def _attachment_parts(message: Message) -> list[Message]:
    # treat either an attachment disposition or a filename as an attachment marker
    return [
        part
        for part in message.walk()
        if part.get_content_disposition() == "attachment" or part.get_filename() is not None
    ]


def _attachment_metadata(index: int, part: Message, payload: bytes) -> Attachment:
    # use a stable fallback name so attachment results remain readable without a filename
    filename = _decode_header(part.get_filename()) or f"attachment-{index + 1}"
    return Attachment(
        index=index,
        filename=filename,
        content_type=part.get_content_type().lower(),
        size_bytes=len(payload),
    )


def _decoded_payload(part: Message) -> bytes:
    # centralize decoding so bodies and attachments handle malformed payloads consistently
    payload = part.get_payload(decode=True)
    if payload is None:
        return b""
    if not isinstance(payload, bytes):
        raise MimeParseError("message part has an unsupported payload")
    return payload


def _decode_header(value: str | None) -> str:
    # decode encoded words before applying the shared whitespace cleanup
    if not value:
        return ""
    return _normalise_text(str(make_header(decode_header(value))))


def _recipient_values(message: Message) -> tuple[str, ...]:
    # preserve To and Cc as separate display values for the normalized result
    values: list[str] = []
    for header in ("To", "Cc"):
        value = _decode_header(message.get(header))
        if value:
            values.append(value)
    return tuple(values)


class _PlainTextHtmlParser(HTMLParser):
    """collect visible text while skipping script-like regions and HTML attributes"""

    _ignored_elements = frozenset({"script", "style", "noscript", "template"})
    _block_elements = frozenset({"br", "div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        # track ignored nesting so script-like content stays suppressed until it closes
        super().__init__(convert_charrefs=True)
        self._text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # ignore attributes entirely and retain only safe text and block boundaries
        del attrs
        if tag in self._ignored_elements:
            self._ignored_depth += 1
        elif tag in self._block_elements:
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        # close ignored regions and separate block text for the final normalization pass
        if tag in self._ignored_elements and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in self._block_elements:
            self._text.append("\n")

    def handle_data(self, data: str) -> None:
        # HTMLParser decodes character references before this data reaches the output
        if not self._ignored_depth:
            self._text.append(data)

    def text(self) -> str:
        # join collected fragments once markup has been removed
        return _normalise_text("".join(self._text))


def html_to_text(value: str) -> str:
    """turn an HTML body into normalized text without exposing its markup"""
    parser = _PlainTextHtmlParser()
    parser.feed(value)
    parser.close()
    return parser.text()


def _normalise_text(value: str) -> str:
    # collapse runs of whitespace while preserving meaningful line boundaries
    return "\n".join(" ".join(line.split()) for line in value.splitlines() if line.split()).strip()
