"""Safe domain errors that never include mailbox content or credentials."""

from __future__ import annotations


class ImapMcpError(RuntimeError):
    """Base error for predictable, safe IMAP server failures."""


class ImapConnectionError(ImapMcpError):
    """The server could not establish a verified TLS connection."""


class ImapAuthenticationError(ImapMcpError):
    """The IMAP server rejected authentication."""


class MailboxNotAllowedError(ImapMcpError):
    """The requested mailbox is not in the configured allowlist."""


class MailboxNotFoundError(ImapMcpError):
    """The allowed mailbox could not be selected."""


class MessageNotFoundError(ImapMcpError):
    """No message exists for the requested UID in the selected mailbox."""
