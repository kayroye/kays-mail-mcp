"""MCP server wiring for the strictly read-only tool surface."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.tools import Tool
from mcp.types import ToolAnnotations

from .config import Settings
from .tools.attachments import make_get_attachment
from .tools.health import health_check
from .tools.mailboxes import make_list_mailboxes
from .tools.messages import make_get_message
from .tools.search import make_search_messages


def create_server(settings: Settings, *, auth: AuthProvider) -> FastMCP:
    """Create the private Streamable HTTP MCP server with read-only tools only."""
    server = FastMCP(
        name="kays-mail-mcp",
        auth=auth,
        mask_error_details=True,
        instructions="Provides strictly read-only, safety-limited IMAP access.",
    )
    server.add_tool(
        Tool.from_function(
            health_check,
            name="health_check",
            description=(
                "Check service availability without exposing IMAP configuration or mailbox data."
            ),
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
    )
    server.add_tool(
        Tool.from_function(
            make_list_mailboxes(settings),
            name="list_mailboxes",
            description="List only existing mailboxes from the server-configured allowlist.",
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
    )
    server.add_tool(
        Tool.from_function(
            make_search_messages(settings),
            name="search_messages",
            description="Search one allowed mailbox and return a bounded page of compact metadata.",
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
    )
    server.add_tool(
        Tool.from_function(
            make_get_message(settings),
            name="get_message",
            description=("Retrieve one message with safe plain text and attachment metadata."),
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
    )
    server.add_tool(
        Tool.from_function(
            make_get_attachment(settings),
            name="get_attachment",
            description=(
                "Retrieve one allowed attachment by mailbox, UID, and attachment index as base64."
            ),
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
    )
    return server
