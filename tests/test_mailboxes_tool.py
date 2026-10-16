"""verify mailbox tool output keeps stable identifiers from the configured allowlist
use a fake session to check context handling without contacting an IMAP server
"""

from __future__ import annotations

from imap_mcp.config import Settings, load_settings
from imap_mcp.tools.mailboxes import make_list_mailboxes


class FakeImapClient:
    """stand in for ImapClient and expose a fixed mailbox inventory"""

    def __init__(self, settings: Settings) -> None:
        """retain settings and track whether the context is active"""
        self.settings = settings
        self.entered = False

    def __enter__(self) -> FakeImapClient:
        """mark the fake session as open"""
        self.entered = True
        return self

    def __exit__(self, *_: object) -> None:
        """mark the fake session as closed"""
        self.entered = False

    def list_mailboxes(self) -> tuple[str, ...]:
        """return the fixture inventory for allowlist filtering"""
        return ("INBOX", "Archive")


def settings() -> Settings:
    """build settings that allow both fixture mailboxes"""
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX, Archive",
        }
    )


def test_list_mailboxes_returns_stable_mailbox_identifiers() -> None:
    """check the result uses mailbox names as stable IDs"""
    tool = make_list_mailboxes(settings(), client_factory=FakeImapClient)

    assert tool() == {"mailboxes": [{"id": "INBOX"}, {"id": "Archive"}]}
