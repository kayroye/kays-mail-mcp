"""Read-only retrieval of one complete, safely normalized message."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypedDict

from ..config import Settings
from ..imap_client import ImapClient
from ..mime_parser import parse_message


class MessageAttachment(TypedDict):
    """Attachment metadata used to select a later explicit attachment request."""

    index: int
    filename: str
    content_type: str
    size_bytes: int


class GetMessageResult(TypedDict):
    """One stable mailbox-plus-UID message identity and safe normalized content."""

    mailbox: str
    uid: int
    subject: str
    sender: str
    recipients: list[str]
    date: str
    message_id: str
    body: str
    attachments: list[MessageAttachment]


class MessageSession(Protocol):
    """Read-only IMAP behavior required by the complete-message tool."""

    def __enter__(self) -> MessageSession: ...

    def __exit__(self, *_: object) -> None: ...

    def fetch_rfc822(self, mailbox: str, uid: int) -> bytes: ...


MessageClientFactory = Callable[[Settings], MessageSession]


def make_get_message(
    settings: Settings, client_factory: MessageClientFactory = ImapClient
) -> Callable[[str, int], GetMessageResult]:
    """Create a complete-message tool with a non-client-overridable body limit."""

    def get_message(mailbox: str, uid: int) -> GetMessageResult:
        """Retrieve one mailbox-plus-UID message as safe plain text and metadata."""
        if uid < 1:
            raise ValueError("uid must be a positive IMAP UID")
        with client_factory(settings) as client:
            raw_message = client.fetch_rfc822(mailbox, uid)
        parsed = parse_message(raw_message, max_body_bytes=settings.limits.max_body_bytes)
        return {
            "mailbox": mailbox,
            "uid": uid,
            "subject": parsed.subject,
            "sender": parsed.sender,
            "recipients": list(parsed.recipients),
            "date": parsed.date,
            "message_id": parsed.message_id,
            "body": parsed.body,
            "attachments": [
                {
                    "index": attachment.index,
                    "filename": attachment.filename,
                    "content_type": attachment.content_type,
                    "size_bytes": attachment.size_bytes,
                }
                for attachment in parsed.attachments
            ],
        }

    return get_message
