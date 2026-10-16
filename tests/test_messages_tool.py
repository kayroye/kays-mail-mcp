from __future__ import annotations

from email.message import EmailMessage

import pytest

from imap_mcp.config import Settings, load_settings
from imap_mcp.tools.messages import make_get_message


class FakeMessageClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def __enter__(self) -> FakeMessageClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def fetch_rfc822(self, mailbox: str, uid: int) -> bytes:
        assert (mailbox, uid) == ("INBOX", 9)
        message = EmailMessage()
        message["Subject"] = "Fixture"
        message["From"] = "sender@example.test"
        message.set_content("Safe text")
        message.add_attachment(
            b"test pdf", maintype="application", subtype="pdf", filename="report.pdf"
        )
        return message.as_bytes()


def settings() -> Settings:
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX",
        }
    )


def test_get_message_returns_safe_content_and_attachment_inventory() -> None:
    result = make_get_message(settings(), client_factory=FakeMessageClient)("INBOX", 9)

    assert result["mailbox"] == "INBOX"
    assert result["uid"] == 9
    assert result["body"] == "Safe text"
    assert result["attachments"] == [
        {"index": 0, "filename": "report.pdf", "content_type": "application/pdf", "size_bytes": 8}
    ]


def test_get_message_rejects_invalid_uid_before_connection() -> None:
    tool = make_get_message(settings(), client_factory=FakeMessageClient)

    with pytest.raises(ValueError, match="positive IMAP UID"):
        tool("INBOX", 0)
