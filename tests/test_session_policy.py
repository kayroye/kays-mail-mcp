"""Catch unsafe realm migrations using a real loopback HTTP boundary."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest
from test_setup import answers, setup


@pytest.fixture
def identity_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Path, dict[str, Any]]]:
    config = tmp_path / "private"
    setup.prepare(config, answers(), "synthetic-mail-secret", "long-login-password")
    state: dict[str, Any] = {
        "realm": {
            "ssoSessionMaxLifespan": 604800,
            "ssoSessionIdleTimeout": 86400,
            "clientSessionMaxLifespan": 0,
            "clientSessionIdleTimeout": 0,
            "revokeRefreshToken": True,
            "accessTokenLifespan": 300,
            "users": ["existing-owner"],
        },
        "updates": [],
        "logout": False,
        "reject": False,
        "redirect": False,
        "leaks": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            if self.path.endswith("/token"):
                assert body["password"] == [(config / "secrets/admin_password").read_text()]
                if state["reject"]:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b"private-provider-error")
                    return
                if state["redirect"]:
                    self.send_response(307)
                    self.send_header("Location", "/leaked-password")
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"access_token":"admin-token","refresh_token":"admin-refresh"}')
            elif self.path.endswith("/logout"):
                assert body["refresh_token"] == ["admin-refresh"]
                state["logout"] = True
                self.send_response(204)
                self.end_headers()
            else:
                state["leaks"] += 1
                self.send_response(500)
                self.end_headers()

        def do_GET(self) -> None:
            assert self.headers["Authorization"] == "Bearer admin-token"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(state["realm"]).encode())

        def do_PUT(self) -> None:
            assert self.headers["Authorization"] == "Bearer admin-token"
            update = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["updates"].append(update)
            if not state.get("ignore_update") or len(state["updates"]) > 1:
                state["realm"].update(update)
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(setup, "_capture", lambda command: f"127.0.0.1:{server.server_port}")
    try:
        yield config, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_migration_changes_only_limits_and_preserves_keys(
    identity_api: tuple[Path, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Catch wiping identities or weakening token security while applying a lifetime policy."""
    config, state = identity_api
    key = (config / "secrets/signing_key").read_bytes()
    setup.configure_sessions(config, "180", "90")
    assert state["updates"] == [
        {
            "ssoSessionMaxLifespan": 15552000,
            "ssoSessionIdleTimeout": 7776000,
            "clientSessionMaxLifespan": 0,
            "clientSessionIdleTimeout": 0,
        }
    ]
    assert state["realm"]["users"] == ["existing-owner"]
    assert state["realm"]["revokeRefreshToken"] is True
    assert state["realm"]["accessTokenLifespan"] == 300
    assert (config / "secrets/signing_key").read_bytes() == key
    assert state["logout"]
    assert json.loads((config / "settings.json").read_text())["session_idle_days"] == "90"
    assert (
        json.loads((config / "session-policy-backup.json").read_text())["ssoSessionMaxLifespan"]
        == 604800
    )
    assert (config / "settings.json").stat().st_mode & 0o077 == 0
    output = capsys.readouterr().out
    assert "admin-token" not in output
    assert (config / "secrets/admin_password").read_text() not in output


@pytest.mark.parametrize("failure", ["reject", "redirect"])
def test_admin_failure_preserves_settings_and_never_follows_redirects(
    identity_api: tuple[Path, dict[str, Any]],
    failure: str,
) -> None:
    """Catch credential forwarding on redirects and recording a policy that was never applied."""
    config, state = identity_api
    before = (config / "settings.json").read_bytes()
    state[failure] = True
    with pytest.raises(ValueError, match="Session configuration failed") as error:
        setup.configure_sessions(config, "120", "60")
    assert state["updates"] == []
    assert state["leaks"] == 0
    assert (config / "settings.json").read_bytes() == before
    assert "private-provider-error" not in str(error.value)


def test_readback_failure_restores_previous_policy(
    identity_api: tuple[Path, dict[str, Any]],
) -> None:
    """Catch reporting success or persisting settings when the identity server ignores an update."""
    config, state = identity_api
    state["ignore_update"] = True
    before = (config / "settings.json").read_bytes()
    with pytest.raises(ValueError, match="Session configuration failed"):
        setup.configure_sessions(config, "120", "60")
    assert len(state["updates"]) == 2
    assert state["realm"]["ssoSessionMaxLifespan"] == 604800
    assert (config / "settings.json").read_bytes() == before
    assert state["logout"]


def test_nonloopback_admin_address_is_rejected_before_sending_credentials(
    identity_api: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent a changed Compose binding from sending the administrator password over a network."""
    config, state = identity_api
    monkeypatch.setattr(setup, "_capture", lambda command: "192.0.2.1:8080")
    with pytest.raises(ValueError, match="loopback"):
        setup.configure_sessions(config, "180", "90")
    assert not state["updates"]


def test_local_save_failure_restores_live_limits(
    identity_api: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent a disk error leaving the identity server and recorded policy inconsistent."""
    config, state = identity_api
    before = (config / "settings.json").read_bytes()

    def fail_replace(*args: object) -> None:
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(setup.os, "replace", fail_replace)
    with pytest.raises(ValueError, match="Session configuration failed"):
        setup.configure_sessions(config, "120", "60")
    assert state["realm"]["ssoSessionMaxLifespan"] == 604800
    assert (config / "settings.json").read_bytes() == before
    assert state["logout"]


def test_internal_docker_admin_fallback_requires_an_internal_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch using an externally routed container network when Docker omits port publication."""
    internal = False

    def capture(command: list[str]) -> str:
        if "port" in command:
            raise ValueError("not published")
        if "ps" in command:
            return "fixture-keycloak"
        if "network" in command:
            return "true" if internal else "false"
        return json.dumps(
            {"project": "fixture", "networks": {"fixture_identity": {"IPAddress": "10.0.6.3"}}}
        )

    monkeypatch.setattr(setup, "_capture", capture)
    with pytest.raises(ValueError, match="internal"):
        setup.admin_address(tmp_path)
    internal = True
    assert setup.admin_address(tmp_path) == "10.0.6.3:8080"
