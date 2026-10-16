from __future__ import annotations

from imap_mcp.config import Settings, load_settings
from imap_mcp.tools.mailboxes import make_list_mailboxes


class FakeImapClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.entered = False

    def __enter__(self) -> FakeImapClient:
        self.entered = True
        return self

    def __exit__(self, *_: object) -> None:
        self.entered = False

    def list_mailboxes(self) -> tuple[str, ...]:
        return ("INBOX", "Archive")


def settings() -> Settings:
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX, Archive",
        }
    )


def test_list_mailboxes_returns_stable_mailbox_identifiers() -> None:
    tool = make_list_mailboxes(settings(), client_factory=FakeImapClient)

    assert tool() == {"mailboxes": [{"id": "INBOX"}, {"id": "Archive"}]}
