"""Safe deployment diagnostics for the MCP service."""

from __future__ import annotations

from typing import Literal, TypedDict


class HealthCheckResult(TypedDict):
    """Structured health response that contains no IMAP configuration or data."""

    status: Literal["ok"]
    service: str
    version: str


def health_check() -> HealthCheckResult:
    """Return MCP service availability without contacting IMAP or exposing configuration."""
    return {"status": "ok", "service": "imap-mcp", "version": "0.1.0"}
