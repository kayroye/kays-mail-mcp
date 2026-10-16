"""verify message tool responses use safe MIME output and stable identifiers
replace the transport with a fixture client to keep these checks offline
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from imap_mcp.config import Settings, load_settings
from imap_mcp.tools.messages import make_get_message


class FakeMessageClient:
    """return one deterministic RFC822 message for the requested mailbox identity"""

    def __init__(self, settings: Settings) -> None:
        """retain the settings passed through the tool factory"""
        self.settings = settings

    def __enter__(self) -> FakeMessageClient:
        """provide the fake as a context-managed session"""
        return self

    def __exit__(self, *_: object) -> None:
        """finish the fake session without external cleanup"""
        return None

    def fetch_rfc822(self, mailbox: str, uid: int, uidvalidity: int) -> bytes:
        """check the requested identity and build a message with one safe attachment"""
        assert (mailbox, uid, uidvalidity) == ("INBOX", 9, 101)
        message = EmailMessage()
        message["Subject"] = "Fixture"
        message["From"] = "sender@example.test"
        message.set_content("Safe text")
        message.add_attachment(
            b"test pdf", maintype="application", subtype="pdf", filename="report.pdf"
        )
        return message.as_bytes()


def settings() -> Settings:
    """build minimal valid settings for message retrieval"""
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX",
        }
    )


def test_get_message_returns_safe_content_and_attachment_inventory() -> None:
    """check stable message identifiers, body text, and attachment metadata"""
    result = make_get_message(settings(), client_factory=FakeMessageClient)("INBOX", 9, 101)

    assert result["mailbox"] == "INBOX"
    assert result["uid"] == 9
    assert result["body"] == "Safe text"
    assert result["attachments"] == [
        {"index": 0, "filename": "report.pdf", "content_type": "application/pdf", "size_bytes": 8}
    ]


def test_get_message_rejects_invalid_uid_before_connection() -> None:
    """check invalid UIDs are rejected before the fake session is opened"""
    tool = make_get_message(settings(), client_factory=FakeMessageClient)

    with pytest.raises(ValueError, match="positive IMAP UID"):
        tool("INBOX", 0, 101)
