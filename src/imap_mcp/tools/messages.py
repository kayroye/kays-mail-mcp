"""retrieve one message and convert it to a stable safe response
coordinate ImapClient fetching with the bounded parsing in mime_parser
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypedDict

from ..config import Settings
from ..imap_client import ImapClient
from ..mime_parser import parse_message


class MessageAttachment(TypedDict):
    """describe an attachment that can be requested separately by index"""

    index: int
    filename: str
    content_type: str
    size_bytes: int


class GetMessageResult(TypedDict):
    """describe the normalized message response and its stable mailbox identity"""

    mailbox: str
    uid: int
    uidvalidity: int
    subject: str
    sender: str
    recipients: list[str]
    date: str
    message_id: str
    body: str
    attachments: list[MessageAttachment]


class MessageSession(Protocol):
    """describe the session behavior needed to fetch one full message"""

    def __enter__(self) -> MessageSession:
        """open a session for one message retrieval"""
        ...

    def __exit__(self, *_: object) -> None:
        """close the IMAP session after retrieval"""
        ...

    def fetch_rfc822(self, mailbox: str, uid: int, uidvalidity: int) -> bytes:
        """fetch one message only when its mailbox version still matches"""
        ...


MessageClientFactory = Callable[[Settings], MessageSession]


def make_get_message(
    settings: Settings, client_factory: MessageClientFactory = ImapClient
) -> Callable[[str, int, int], GetMessageResult]:
    """create a complete-message tool with a server-controlled body limit"""

    def get_message(mailbox: str, uid: int, uidvalidity: int) -> GetMessageResult:
        """retrieve one mailbox-plus-UID message as safe text and metadata"""
        if uid < 1:
            raise ValueError("uid must be a positive IMAP UID")
        with client_factory(settings) as client:
            raw_message = client.fetch_rfc822(mailbox, uid, uidvalidity)
            # pass raw bytes to mime_parser for shared body and attachment handling
            parsed = parse_message(raw_message, max_body_bytes=settings.limits.max_body_bytes)
            return {
                "mailbox": mailbox,
                "uid": uid,
                "uidvalidity": uidvalidity,
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
