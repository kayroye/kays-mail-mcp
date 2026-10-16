"""provide a local service health response without contacting IMAP
keep diagnostics free of configuration and mailbox details
"""

from __future__ import annotations

from typing import Literal, TypedDict


class HealthCheckResult(TypedDict):
    """describe the small response returned by the health tool"""

    status: Literal["ok"]
    service: str
    version: str


def health_check() -> HealthCheckResult:
    """return service availability without opening an IMAP session"""
    return {"status": "ok", "service": "imap-mcp", "version": "0.1.0"}
