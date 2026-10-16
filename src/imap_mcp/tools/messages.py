"""retrieve one message and convert it to a stable safe response
coordinate ImapClient fetching with the bounded parsing in mime_parser
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol, TypedDict

from pydantic import Field

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
    body_truncated: bool
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
) -> Callable[..., GetMessageResult]:
    """create a message preview tool with server-controlled parsing limits"""

    def get_message(
        mailbox: Annotated[str, Field(description="Mailbox used in search_messages, e.g. INBOX.")],
        uid: Annotated[int, Field(description="Message UID returned by search_messages.")],
        uidvalidity: Annotated[
            int,
            Field(description="Mailbox version returned with this search result; never invent it."),
        ],
        body_limit: Annotated[
            int,
            Field(
                description=(
                    "Maximum body characters to return, not tokens. Defaults to 4000. "
                    "If body_truncated is true, repeat with a larger limit to read more. "
                    "Server message and decoded body byte limits still apply."
                ),
                ge=1,
            ),
        ] = 4000,
    ) -> GetMessageResult:
        """retrieve safe text up to body_limit characters plus attachment metadata"""
        if uid < 1:
            raise ValueError("uid must be a positive IMAP UID")
        if body_limit < 1:
            raise ValueError("body_limit must be a positive character count")
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
                "body": parsed.body[:body_limit],
                "body_truncated": len(parsed.body) > body_limit,
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
