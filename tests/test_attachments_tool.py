"""verify explicit attachment retrieval returns JSON-safe base64 content
use a fake IMAP client to isolate tool formatting from transport behavior
"""

from __future__ import annotations

from email.message import EmailMessage

from imap_mcp.config import Settings, load_settings
from imap_mcp.tools.attachments import make_get_attachment


class FakeAttachmentClient:
    """provide one fixture message containing an allowed PDF attachment"""

    def __init__(self, settings: Settings) -> None:
        """retain the settings passed through the tool factory"""
        self.settings = settings

    def __enter__(self) -> FakeAttachmentClient:
        """provide the fake as a context-managed session"""
        return self

    def __exit__(self, *_: object) -> None:
        """finish the fake session without external cleanup"""
        return None

    def fetch_rfc822(self, mailbox: str, uid: int, uidvalidity: int) -> bytes:
        """check the requested mailbox identity and build the fixture message"""
        assert (mailbox, uid, uidvalidity) == ("INBOX", 7, 101)
        message = EmailMessage()
        message.set_content("body")
        message.add_attachment(
            b"wrong attachment", maintype="text", subtype="plain", filename="first.txt"
        )
        message.add_attachment(
            b"pdf bytes", maintype="application", subtype="pdf", filename="report.pdf"
        )
        return message.as_bytes()


def settings() -> Settings:
    """build minimal valid settings for attachment retrieval"""
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX",
        }
    )


def test_attachment_selection_returns_requested_bytes_and_identity() -> None:
    """catch always selecting the first attachment or losing the source identity"""
    tool = make_get_attachment(settings(), client_factory=FakeAttachmentClient)

    result = tool("INBOX", 7, 1, 101)

    assert result == {
        "mailbox": "INBOX",
        "uid": 7,
        "uidvalidity": 101,
        "index": 1,
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "content_base64": "cGRmIGJ5dGVz",
    }
