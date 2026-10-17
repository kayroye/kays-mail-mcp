"""verify the MCP server exposes only the declared read-only tools
check health output and the tool annotations returned by FastMCP
"""

from __future__ import annotations

import asyncio

from imap_mcp.config import Settings, load_settings
from imap_mcp.server import create_server


def settings() -> Settings:
    """build minimal valid settings for server construction"""
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX",
        }
    )


def test_server_exposes_only_readonly_mail_tools() -> None:
    """check all registered tools carry read-only non-destructive annotations"""
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    server = create_server(settings(), auth=StaticTokenVerifier(tokens={}))
    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "health_check",
        "list_mailboxes",
        "search_messages",
        "get_message",
        "get_attachment",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
