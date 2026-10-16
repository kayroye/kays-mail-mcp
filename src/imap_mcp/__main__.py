"""Command-line entry point for the Streamable HTTP MCP server."""

from __future__ import annotations

from .config import load_settings
from .server import create_server


def main() -> None:
    """Load validated settings and serve the MCP endpoint."""
    create_server(load_settings()).run(transport="streamable-http")


if __name__ == "__main__":
    main()
