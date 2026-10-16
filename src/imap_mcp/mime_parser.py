"""Safe MIME parsing that exposes normalized metadata and plain text only."""

from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.header import decode_header, make_header
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser

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
    """Safe attachment metadata; the content remains unavailable until explicitly requested."""

    index: int
    filename: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """Normalized headers, safe body text, and an attachment inventory."""

    subject: str
    sender: str
    recipients: tuple[str, ...]
    date: str
    message_id: str
    body: str
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True, slots=True)
class ParsedHeaders:
    """Normalized compact metadata suitable for search results."""

    subject: str
    sender: str
    recipients: tuple[str, ...]
    date: str
    message_id: str


class MimeParseError(ValueError):
    """The RFC822 payload could not be safely parsed within configured limits."""


def parse_message(raw_message: bytes, *, max_body_bytes: int) -> ParsedMessage:
    """Parse a message without returning active HTML or attachment contents."""
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
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
    """Parse normalized headers without reading or returning the message body."""
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
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
    """Return one allowed attachment only after applying the server size limit."""
    if attachment_index < 0:
        raise MimeParseError("attachment was not found")
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
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
    if candidates[0].get_content_type().lower() == "text/html":
        return html_to_text(text)
    return _normalise_text(text)


def _body_parts(message: Message, content_type: str) -> list[Message]:
    return [
        part
        for part in message.walk()
        if part.get_content_type().lower() == content_type
        and part.get_content_disposition() != "attachment"
        and not part.get_filename()
    ]


def _attachments(message: Message) -> tuple[Attachment, ...]:
    items: list[Attachment] = []
    for index, part in enumerate(_attachment_parts(message)):
        payload = _decoded_payload(part)
        items.append(_attachment_metadata(index, part, payload))
    return tuple(items)


def _attachment_parts(message: Message) -> list[Message]:
    return [
        part
        for part in message.walk()
        if part.get_content_disposition() == "attachment" or part.get_filename() is not None
    ]


def _attachment_metadata(index: int, part: Message, payload: bytes) -> Attachment:
    filename = _decode_header(part.get_filename()) or f"attachment-{index + 1}"
    return Attachment(
        index=index,
        filename=filename,
        content_type=part.get_content_type().lower(),
        size_bytes=len(payload),
    )


def _decoded_payload(part: Message) -> bytes:
    payload = part.get_payload(decode=True)
    if payload is None:
        return b""
    if not isinstance(payload, bytes):
        raise MimeParseError("message part has an unsupported payload")
    return payload


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    return _normalise_text(str(make_header(decode_header(value))))


def _recipient_values(message: Message) -> tuple[str, ...]:
    values: list[str] = []
    for header in ("To", "Cc"):
        value = _decode_header(message.get(header))
        if value:
            values.append(value)
    return tuple(values)


class _PlainTextHtmlParser(HTMLParser):
    _ignored_elements = frozenset({"script", "style", "noscript", "template"})
    _block_elements = frozenset({"br", "div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._ignored_elements:
            self._ignored_depth += 1
        elif tag in self._block_elements:
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ignored_elements and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in self._block_elements:
            self._text.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._text.append(data)

    def text(self) -> str:
        return _normalise_text("".join(self._text))


def html_to_text(value: str) -> str:
    """Remove markup, URLs, scripts, and remote content from HTML email bodies."""
    parser = _PlainTextHtmlParser()
    parser.feed(value)
    parser.close()
    return parser.text()


def _normalise_text(value: str) -> str:
    return "\n".join(" ".join(line.split()) for line in value.splitlines() if line.split()).strip()
