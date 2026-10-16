"""define safe domain errors shared by transport and MCP tools
keep failure categories useful without exposing mailbox content or credentials
"""

from __future__ import annotations


class ImapMcpError(RuntimeError):
    """provide the common base for safe IMAP service failures"""


class ImapConnectionError(ImapMcpError):
    """report an unavailable or unverified IMAP connection"""


class ImapAuthenticationError(ImapMcpError):
    """report rejected IMAP credentials"""


class MailboxNotAllowedError(ImapMcpError):
    """report a mailbox outside the configured allowlist"""


class MailboxNotFoundError(ImapMcpError):
    """report an allowlisted mailbox that the server could not select"""


class MessageNotFoundError(ImapMcpError):
    """report a missing message UID in the selected mailbox"""
