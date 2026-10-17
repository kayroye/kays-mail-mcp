"""exercise reader upgrades, rollback and diagnostics at process/network boundaries"""

from __future__ import annotations

import io
import json
import subprocess
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from test_setup import answers, setup


@pytest.fixture
def private_config(tmp_path: Path) -> Path:
    config = tmp_path / "private"
    setup.prepare(config, answers(), "synthetic-mail-secret", "long-login-password")
    return config


def docker_fixture(
    monkeypatch: pytest.MonkeyPatch, *, fail_start: bool = False, wrong_source: bool = False
) -> list[list[str]]:
    """replace Docker processes, preserving command arguments and exit status semantics"""
    commands: list[list[str]] = []
    failed = False

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal failed
        commands.append(command)
        output = ""
        status = 0
        if "config" in command:
            output = json.dumps(
                {
                    "services": {
                        "mail": {
                            "image": "kays-mail-mcp:local",
                            "build": {
                                "context": "/wrong/checkout" if wrong_source else str(setup.ROOT)
                            },
                            "environment": {"PRIVATE": "never-print-this"},
                        }
                    }
                }
            )
        elif "inspect" in command:
            output = "sha256:" + "a" * 64
        elif "ps" in command:
            if "--format" in command:
                output = "\n".join(
                    json.dumps({"Service": name, "State": "running", "Health": "healthy"})
                    for name in ("mail", "gateway", "keycloak", "db")
                )
            else:
                output = "fixture-container"
        elif "up" in command and fail_start and not failed:
            failed = True
            status = 1
        return subprocess.CompletedProcess(command, status, output, "private-provider-error")

    monkeypatch.setattr(setup.subprocess, "run", run)
    return commands


def test_upgrade_only_replaces_reader_and_preserves_private_files(
    private_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands = docker_fixture(monkeypatch)
    before = {
        p.relative_to(private_config): p.read_bytes()
        for p in private_config.rglob("*")
        if p.is_file()
    }
    setup.upgrade(private_config)
    actions = [c[c.index("-f") + 2 :] for c in commands if "compose" in c]
    assert ["build", "mail"] in actions
    assert ["up", "-d", "--no-deps", "--wait", "--wait-timeout", "60", "mail"] in actions
    assert ["exec", "-T", "gateway", "nginx", "-s", "reload"] in actions
    assert not any("keycloak" in action or "db" in action or "down" in action for action in actions)
    assert any(c[:2] == ["docker", "tag"] and c[2].startswith("sha256:") for c in commands)
    assert before == {
        p.relative_to(private_config): p.read_bytes()
        for p in private_config.rglob("*")
        if p.is_file()
    }
    assert "never-print-this" not in capsys.readouterr().out


def test_failed_update_restores_previous_image_and_reports_rollback(
    private_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = docker_fixture(monkeypatch, fail_start=True)
    with pytest.raises(ValueError, match="rolled back"):
        setup.upgrade(private_config)
    assert ["docker", "tag", "kays-mail-mcp:reader-rollback", "kays-mail-mcp:local"] in commands
    assert sum("up" in c for c in commands) == 2


def test_wrong_checkout_is_rejected_before_build_or_restart(
    private_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = docker_fixture(monkeypatch, wrong_source=True)
    with pytest.raises(ValueError, match="SOURCE_DIR"):
        setup.upgrade(private_config)
    assert not any("build" in c or "up" in c or "tag" in c for c in commands)


def test_doctor_distinguishes_services_public_auth_and_mailbox(
    private_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands = docker_fixture(monkeypatch)
    checked: list[tuple[str, int, str | None]] = []

    def probe(url: str, expected_status: int, issuer: str | None = None) -> bool:
        checked.append((url, expected_status, issuer))
        return expected_status != 401  # simulate the public MCP being incorrectly unauthenticated

    monkeypatch.setattr(setup, "_http_probe", probe)
    assert setup.doctor(private_config) is False
    output = capsys.readouterr().out
    assert "PASS Services" in output
    assert "FAIL Public MCP authentication" in output
    assert "PASS Mailbox access" in output
    assert any(url.endswith("/mcp") and status == 401 for url, status, _ in checked)
    assert any(issuer == "https://login.example.test/realms/mail" for _, _, issuer in checked)
    assert any("exec" in c and "mail" in c and "python" in c for c in commands)
    assert "synthetic-mail-secret" not in output


def test_anonymous_auth_probe_uses_a_valid_mcp_post(monkeypatch: pytest.MonkeyPatch) -> None:
    """catch GET returning 405 before authentication is exercised on a stateless server"""
    requests: list[Request] = []

    def urlopen(request: Request, **kwargs: Any) -> Any:
        requests.append(request)
        raise HTTPError(request.full_url, 401, "Unauthorized", Message(), io.BytesIO())

    monkeypatch.setattr(setup, "urlopen", urlopen)
    assert setup._http_probe("https://mail.example.test/mcp", 401)
    assert requests[0].get_method() == "POST"
    data = requests[0].data
    assert isinstance(data, bytes)
    assert json.loads(data)["method"] == "initialize"
    assert requests[0].get_header("Content-type") == "application/json"


def test_doctor_cli_reports_success_without_restarting_services(
    private_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = docker_fixture(monkeypatch)
    monkeypatch.setattr(setup, "prerequisites", lambda: None)
    monkeypatch.setattr(setup, "_http_probe", lambda *args: True)
    assert setup.main(["--doctor", "--config-dir", str(private_config)]) == 0
    assert not any("up" in c or "build" in c or "tag" in c for c in commands)
