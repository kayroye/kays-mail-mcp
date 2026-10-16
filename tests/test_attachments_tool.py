from __future__ import annotations

import base64
from email.message import EmailMessage

from imap_mcp.config import Settings, load_settings
from imap_mcp.tools.attachments import make_get_attachment


class FakeAttachmentClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def __enter__(self) -> FakeAttachmentClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def fetch_rfc822(self, mailbox: str, uid: int) -> bytes:
        assert (mailbox, uid) == ("INBOX", 7)
        message = EmailMessage()
        message.set_content("body")
        message.add_attachment(
            b"pdf bytes", maintype="application", subtype="pdf", filename="report.pdf"
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


def test_get_attachment_returns_json_safe_base64_content() -> None:
    tool = make_get_attachment(settings(), client_factory=FakeAttachmentClient)

    result = tool("INBOX", 7, 0)

    assert result == {
        "mailbox": "INBOX",
        "uid": 7,
        "index": 0,
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "content_base64": base64.b64encode(b"pdf bytes").decode("ascii"),
    }
