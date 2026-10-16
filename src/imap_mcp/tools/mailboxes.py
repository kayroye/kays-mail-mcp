"""expose configured mailbox names through a read-only MCP tool
use ImapClient to filter the server inventory by the allowlist in Settings
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypedDict

from ..config import Settings
from ..imap_client import ImapClient


class Mailbox(TypedDict):
    """hold the mailbox identifier shared with later read-only tool calls"""

    id: str


class ListMailboxesResult(TypedDict):
    """describe the mailbox-only inventory response"""

    mailboxes: list[Mailbox]


class MailboxSession(Protocol):
    """describe the session calls needed by this tool"""

    def __enter__(self) -> MailboxSession:
        """open a session for the duration of one tool call"""
        ...

    def __exit__(self, *_: object) -> None:
        """close the session after listing mailboxes"""
        ...

    def list_mailboxes(self) -> tuple[str, ...]:
        """return existing mailbox names that pass the server allowlist"""
        ...


ImapClientFactory = Callable[[Settings], MailboxSession]


def make_list_mailboxes(
    settings: Settings, client_factory: ImapClientFactory = ImapClient
) -> Callable[[], ListMailboxesResult]:
    """create a zero-input tool bound to server configuration and client factory"""

    def list_mailboxes() -> ListMailboxesResult:
        """return configured mailboxes that currently exist on the IMAP server"""
        with client_factory(settings) as client:
            return {"mailboxes": [{"id": mailbox} for mailbox in client.list_mailboxes()]}

    return list_mailboxes
