"""Read-only mailbox inventory MCP tool."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypedDict

from ..config import Settings
from ..imap_client import ImapClient


class Mailbox(TypedDict):
    """Stable IMAP mailbox identifier exposed to subsequent read-only tools."""

    id: str


class ListMailboxesResult(TypedDict):
    """Bounded mailbox inventory containing no message metadata."""

    mailboxes: list[Mailbox]


class MailboxSession(Protocol):
    """Read-only IMAP session behavior required by this tool."""

    def __enter__(self) -> MailboxSession: ...

    def __exit__(self, *_: object) -> None: ...

    def list_mailboxes(self) -> tuple[str, ...]: ...


ImapClientFactory = Callable[[Settings], MailboxSession]


def make_list_mailboxes(
    settings: Settings, client_factory: ImapClientFactory = ImapClient
) -> Callable[[], ListMailboxesResult]:
    """Create a zero-input MCP tool bound to validated server configuration."""

    def list_mailboxes() -> ListMailboxesResult:
        """List configured mailboxes that currently exist on the IMAP server."""
        with client_factory(settings) as client:
            return {"mailboxes": [{"id": mailbox} for mailbox in client.list_mailboxes()]}

    return list_mailboxes
