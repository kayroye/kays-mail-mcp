from __future__ import annotations

import asyncio

from imap_mcp.config import Settings, load_settings
from imap_mcp.server import create_server
from imap_mcp.tools.health import health_check


def settings() -> Settings:
    return load_settings(
        {
            "IMAP_HOST": "imap.example.test",
            "IMAP_USERNAME": "test-user",
            "IMAP_PASSWORD": "test-password",
            "IMAP_ALLOWED_MAILBOXES": "INBOX",
        }
    )


def test_health_check_returns_only_safe_service_status() -> None:
    assert health_check() == {"status": "ok", "service": "imap-mcp", "version": "0.1.0"}


def test_server_discovers_only_health_check_at_this_stage() -> None:
    server = create_server(settings())
    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "health_check",
        "list_mailboxes",
        "search_messages",
        "get_message",
        "get_attachment",
    ]
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
