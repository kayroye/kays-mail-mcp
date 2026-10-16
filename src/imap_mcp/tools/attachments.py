"""Explicit, size-limited retrieval of one allowed attachment."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Protocol, TypedDict

from ..config import Settings
from ..imap_client import ImapClient
from ..mime_parser import attachment_content


class AttachmentResult(TypedDict):
    mailbox: str
    uid: int
    index: int
    filename: str
    content_type: str
    content_base64: str


class AttachmentSession(Protocol):
    def __enter__(self) -> AttachmentSession: ...
    def __exit__(self, *_: object) -> None: ...
    def fetch_rfc822(self, mailbox: str, uid: int) -> bytes: ...


AttachmentClientFactory = Callable[[Settings], AttachmentSession]


def make_get_attachment(
    settings: Settings, client_factory: AttachmentClientFactory = ImapClient
) -> Callable[[str, int, int], AttachmentResult]:
    """Create an attachment tool with fixed MIME and size limits."""

    def get_attachment(mailbox: str, uid: int, index: int) -> AttachmentResult:
        """Retrieve one explicitly selected allowed attachment."""
        if uid < 1 or index < 0:
            raise ValueError("uid and index must be non-negative valid identifiers")
        with client_factory(settings) as client:
            raw_message = client.fetch_rfc822(mailbox, uid)
        attachment, content = attachment_content(
            raw_message,
            attachment_index=index,
            max_attachment_bytes=settings.limits.max_attachment_bytes,
        )
        return {
            "mailbox": mailbox,
            "uid": uid,
            "index": index,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }

    return get_attachment
