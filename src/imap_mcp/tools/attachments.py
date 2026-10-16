"""retrieve one explicitly selected attachment after MIME and size checks
keep attachment bytes out of message results until a caller requests an index
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Protocol, TypedDict

from ..config import Settings
from ..imap_client import ImapClient
from ..mime_parser import attachment_content


class AttachmentResult(TypedDict):
    """describe the attachment response including its encoded content"""

    mailbox: str
    uid: int
    uidvalidity: int
    index: int
    filename: str
    content_type: str
    content_base64: str


class AttachmentSession(Protocol):
    """describe the session behavior needed for explicit attachment retrieval"""

    def __enter__(self) -> AttachmentSession:
        """open a session for one attachment request"""
        ...

    def __exit__(self, *_: object) -> None:
        """close the session after retrieving attachment bytes"""
        ...

    def fetch_rfc822(self, mailbox: str, uid: int, uidvalidity: int) -> bytes:
        """fetch the source message while checking its mailbox version"""
        ...


AttachmentClientFactory = Callable[[Settings], AttachmentSession]


def make_get_attachment(
    settings: Settings, client_factory: AttachmentClientFactory = ImapClient
) -> Callable[[str, int, int, int], AttachmentResult]:
    """create an attachment tool with server-controlled MIME and size limits"""

    def get_attachment(mailbox: str, uid: int, index: int, uidvalidity: int) -> AttachmentResult:
        """retrieve one explicitly selected attachment allowed by mime_parser"""
        if uid < 1 or index < 0:
            raise ValueError("uid and index must be non-negative valid identifiers")
        with client_factory(settings) as client:
            raw_message = client.fetch_rfc822(mailbox, uid, uidvalidity)
            # reuse the parser policy shared with message metadata, then encode bytes for JSON
            attachment, content = attachment_content(
                raw_message,
                attachment_index=index,
                max_attachment_bytes=settings.limits.max_attachment_bytes,
            )
            return {
                "mailbox": mailbox,
                "uid": uid,
                "uidvalidity": uidvalidity,
                "index": index,
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "content_base64": base64.b64encode(content).decode("ascii"),
            }

    return get_attachment
