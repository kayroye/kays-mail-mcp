"""load and validate runtime settings from environment values
keep safety limits and secret handling consistent for the server and IMAP client
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SettingsError(ValueError):
    """report invalid or missing server configuration"""


class TlsMode(StrEnum):
    """name the supported TLS connection modes"""

    IMPLICIT_TLS = "implicit_tls"
    STARTTLS = "starttls"


@dataclass(frozen=True, slots=True)
class SafetyLimits:
    """collect server-side limits that tool inputs cannot raise"""

    max_results: int
    max_message_bytes: int
    max_concurrent_operations: int
    max_body_bytes: int
    max_attachment_bytes: int
    max_query_length: int
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class HttpSettings:
    """hold the MCP service listener address"""

    host: str
    port: int


@dataclass(frozen=True, slots=True)
class Settings:
    """hold validated settings shared by authentication, server, and IMAP modules"""

    host: str
    port: int
    username: str
    password: str = field(repr=False)
    tls_mode: TlsMode
    allowed_mailboxes: tuple[str, ...]
    limits: SafetyLimits
    http: HttpSettings
    connection_idle_seconds: int = 30


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """build validated settings while keeping password values out of errors"""
    if environ is None:
        import os

        environ = os.environ

    host = _required(environ, "IMAP_HOST")
    username = _required(environ, "IMAP_USERNAME")
    password = _load_password(environ)
    mailboxes = _parse_mailboxes(_required(environ, "IMAP_ALLOWED_MAILBOXES"))

    tls_value = environ.get("IMAP_TLS_MODE", TlsMode.IMPLICIT_TLS.value).strip().lower()
    # convert the configured name once so later connection setup uses a known mode
    try:
        tls_mode = TlsMode(tls_value)
    except ValueError as exc:
        raise SettingsError("IMAP_TLS_MODE must be implicit_tls or starttls") from exc

    return Settings(
        host=host,
        port=_positive_int(environ, "IMAP_PORT", 993, maximum=65535),
        username=username,
        password=password,
        tls_mode=tls_mode,
        allowed_mailboxes=mailboxes,
        limits=SafetyLimits(
            max_message_bytes=_positive_int(
                environ, "IMAP_MAX_MESSAGE_BYTES", 26_214_400, maximum=52_428_800
            ),
            max_concurrent_operations=_positive_int(
                environ, "IMAP_MAX_CONCURRENT_OPERATIONS", 2, maximum=8
            ),
            max_results=_positive_int(environ, "IMAP_MAX_RESULTS", 25, maximum=100),
            max_body_bytes=_positive_int(environ, "IMAP_MAX_BODY_BYTES", 65_536, maximum=1_048_576),
            max_attachment_bytes=_positive_int(
                environ, "IMAP_MAX_ATTACHMENT_BYTES", 5_242_880, maximum=26_214_400
            ),
            max_query_length=_positive_int(environ, "IMAP_MAX_QUERY_LENGTH", 256, maximum=1_024),
            timeout_seconds=_positive_int(environ, "IMAP_TIMEOUT_SECONDS", 20, maximum=120),
        ),
        http=HttpSettings(
            host=environ.get("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_positive_int(environ, "MCP_PORT", 8700, maximum=65535),
        ),
        connection_idle_seconds=_positive_int(
            environ, "IMAP_CONNECTION_IDLE_SECONDS", 30, maximum=300, minimum=0
        ),
    )


def _required(environ: Mapping[str, str], name: str) -> str:
    """read one required value and reject whitespace-only input"""
    value = environ.get(name, "").strip()
    if not value:
        raise SettingsError(f"{name} is required")
    return value


def _load_password(environ: Mapping[str, str]) -> str:
    """read exactly one password source and keep filesystem details out of errors"""
    password = environ.get("IMAP_PASSWORD", "")
    password_file = environ.get("IMAP_PASSWORD_FILE", "").strip()
    if bool(password) == bool(password_file):
        raise SettingsError("set exactly one of IMAP_PASSWORD or IMAP_PASSWORD_FILE")
    if password:
        return password

    # read a mounted secret file only after the mutually exclusive source check
    try:
        value = Path(password_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SettingsError("IMAP_PASSWORD_FILE could not be read") from exc
    if not value:
        raise SettingsError("IMAP_PASSWORD_FILE is empty")
    return value


def _parse_mailboxes(value: str) -> tuple[str, ...]:
    """trim, deduplicate, and validate the allowlist used by ImapClient"""
    mailboxes = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if not mailboxes:
        raise SettingsError("IMAP_ALLOWED_MAILBOXES must contain at least one mailbox")
    if any(any(ord(c) < 32 or ord(c) == 127 for c in mailbox) for mailbox in mailboxes):
        raise SettingsError("mailboxes must not contain control characters")
    return mailboxes


def _positive_int(
    environ: Mapping[str, str], name: str, default: int, *, maximum: int, minimum: int = 1
) -> int:
    """parse one positive bounded integer for server-side settings"""
    raw_value = environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise SettingsError(f"{name} must be between {minimum} and {maximum}")
    return value
