from __future__ import annotations

from pathlib import Path

import pytest

from imap_mcp.config import SettingsError, TlsMode, load_settings


def environment(**overrides: str) -> dict[str, str]:
    values = {
        "IMAP_HOST": "imap.example.com",
        "IMAP_USERNAME": "mailbox@example.com",
        "IMAP_PASSWORD": "test-secret",
        "IMAP_ALLOWED_MAILBOXES": "INBOX, Archive",
    }
    values.update(overrides)
    return values


def test_load_settings_uses_safe_defaults() -> None:
    settings = load_settings(environment())

    assert settings.host == "imap.example.com"
    assert settings.tls_mode is TlsMode.IMPLICIT_TLS
    assert settings.allowed_mailboxes == ("INBOX", "Archive")
    assert settings.limits.max_results == 25
    assert settings.http.port == 8700


def test_load_settings_accepts_password_file(tmp_path: Path) -> None:
    password_file = tmp_path / "password"
    password_file.write_text("file-secret\n", encoding="utf-8")

    settings = load_settings(
        environment(
            IMAP_PASSWORD="", IMAP_PASSWORD_FILE=str(password_file), IMAP_TLS_MODE="starttls"
        )
    )

    assert settings.password == "file-secret"
    assert settings.tls_mode is TlsMode.STARTTLS


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"IMAP_HOST": ""}, "IMAP_HOST is required"),
        ({"IMAP_PASSWORD_FILE": "/not/readable"}, "set exactly one"),
        ({"IMAP_PASSWORD": "", "IMAP_PASSWORD_FILE": ""}, "set exactly one"),
        ({"IMAP_TLS_MODE": "plain"}, "IMAP_TLS_MODE"),
        ({"IMAP_MAX_RESULTS": "101"}, "IMAP_MAX_RESULTS"),
    ],
)
def test_load_settings_rejects_unsafe_configuration(
    overrides: dict[str, str], message: str
) -> None:
    with pytest.raises(SettingsError, match=message):
        load_settings(environment(**overrides))


def test_password_is_not_disclosed_by_errors() -> None:
    with pytest.raises(SettingsError) as error:
        load_settings(environment(IMAP_PASSWORD="a-secret-value", IMAP_PORT="invalid"))

    assert "a-secret-value" not in str(error.value)
