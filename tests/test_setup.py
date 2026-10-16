from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "mail_setup", Path(__file__).parents[1] / "scripts/setup.py"
)
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def answers() -> dict[str, str]:
    return {
        "mcp_url": "https://mail.example.test",
        "login_url": "https://login.example.test",
        "login_email": "owner@example.test",
        "imap_host": "imap.mail.me.com",
        "imap_username": "owner@icloud.com",
        "mailboxes": "INBOX,Archive",
        "redirect_uris": "http://127.0.0.1:*/callback/*",
    }


def test_setup_rerun_preserves_credentials_and_builds_valid_private_configuration(
    tmp_path: Path,
) -> None:
    config = tmp_path / "private"
    setup.prepare(config, answers(), "mail-secret", "owner-login-secret")
    before = (config / "secrets/signing_key").read_bytes()
    settings = json.loads((config / "settings.json").read_text())
    assert settings["owner_subject"]
    realm = json.loads((config / "bootstrap/mail-realm.json").read_text())
    assert realm["registrationAllowed"] is False
    assert realm["users"][0]["id"] == settings["owner_subject"]
    assert realm["users"][0]["credentials"][0]["value"] == "owner-login-secret"
    assert realm["clients"][0]["redirectUris"] == ["https://mail.example.test/auth/callback"]
    assert "basic" in realm["clients"][0]["defaultClientScopes"]
    assert realm["clients"][0]["directAccessGrantsEnabled"] is False
    assert stat.S_IMODE(config.stat().st_mode) == 0o700
    assert stat.S_IMODE((config / "secrets/signing_key").stat().st_mode) == 0o600
    setup.prepare(config, answers(), "replacement", "replacement")
    assert (config / "secrets/signing_key").read_bytes() == before
    assert (config / "secrets/imap_password").read_text() == "mail-secret"
    assert (
        json.loads((config / "settings.json").read_text())["owner_subject"]
        == settings["owner_subject"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("mcp_url", "http://mail.test"),
        ("imap_host", "host\nINJECT=1"),
        ("login_email", "bad\nmail@example.test"),
        ("mailboxes", "INBOX\nArchive"),
    ],
)
def test_invalid_input_does_not_write_configuration(tmp_path: Path, field: str, value: str) -> None:
    data = answers()
    data[field] = value
    with pytest.raises(ValueError):
        setup.prepare(tmp_path / "private", data, "secret", "long-login-password")
    assert not (tmp_path / "private/settings.json").exists()


def test_setup_refuses_symlink_destination(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        setup.prepare(link, answers(), "secret", "long-login-password")
    assert list(target.iterdir()) == []


def test_check_has_no_side_effect_and_missing_prerequisite_is_actionable(tmp_path: Path) -> None:
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(Path(setup.__file__ or "")),
            "--check",
            "--config-dir",
            str(tmp_path / "new"),
        ],
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Docker" in result.stdout + result.stderr
    assert not (tmp_path / "new").exists()


def test_release_requires_digest_pinned_images(tmp_path: Path) -> None:
    manifest = tmp_path / "release-images.json"
    manifest.write_text(
        json.dumps(
            {"mail": "ghcr.io/example/mail:latest", "keycloak": "ghcr.io/example/login:latest"}
        )
    )
    with pytest.raises(ValueError, match="digest"):
        setup.read_release_images(tmp_path)
    manifest.write_text(
        json.dumps(
            {
                "mail": "ghcr.io/example/mail@sha256:" + "a" * 64,
                "keycloak": "ghcr.io/example/login@sha256:" + "b" * 64,
            }
        )
    )
    assert setup.read_release_images(tmp_path)["MAIL_IMAGE"].endswith("@sha256:" + "a" * 64)


def test_root_setup_is_rejected_instead_of_running_application_containers_as_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(setup.os, "getuid", lambda: 0)
    with pytest.raises(ValueError, match="non-root"):
        setup.prepare(tmp_path / "private", answers(), "secret", "owner-login-secret")


def test_existing_configuration_rejects_symlinked_secret_directory(tmp_path: Path) -> None:
    config = tmp_path / "private"
    setup.prepare(config, answers(), "secret", "owner-login-secret")
    (config / "secrets").rename(tmp_path / "elsewhere")
    (config / "secrets").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        setup.prepare(config, answers(), "secret", "owner-login-secret")
