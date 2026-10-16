"""MCP server wiring for the strictly read-only tool surface."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import Settings
from .tools.attachments import make_get_attachment
from .tools.health import health_check
from .tools.mailboxes import make_list_mailboxes
from .tools.messages import make_get_message
from .tools.search import make_search_messages


def create_server(settings: Settings) -> FastMCP:
    """Create the private Streamable HTTP MCP server with read-only tools only."""
    server = FastMCP(
        name="IMAP MCP Server",
        instructions="Provides strictly read-only, safety-limited IMAP access.",
        host=settings.http.host,
        port=settings.http.port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )
    server.add_tool(
        health_check,
        name="health_check",
        description=(
            "Check service availability without exposing IMAP configuration or mailbox data."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    server.add_tool(
        make_list_mailboxes(settings),
        name="list_mailboxes",
        description="List only existing mailboxes from the server-configured allowlist.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    server.add_tool(
        make_search_messages(settings),
        name="search_messages",
        description="Search one allowed mailbox and return a bounded page of compact metadata.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    server.add_tool(
        make_get_message(settings),
        name="get_message",
        description=(
            "Retrieve one mailbox-plus-UID message with safe plain text and attachment metadata."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    server.add_tool(
        make_get_attachment(settings),
        name="get_attachment",
        description=(
            "Retrieve one allowed attachment by mailbox, UID, and attachment index as base64."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    return server
