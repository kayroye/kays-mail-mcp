from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_effective_compose_configuration_keeps_origin_and_database_private(tmp_path: Path) -> None:
    from test_setup import answers, setup

    config = tmp_path / "private"
    setup.prepare(config, answers(), "mail-secret", "owner-login-secret")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(config / "compose.env"),
            "-f",
            str(config / "compose.yaml"),
            "--profile",
            "public",
            "--profile",
            "public",
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for name in ("mail", "db", "gateway"):
        assert not services[name].get("ports")
    assert services["keycloak"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["db"]["networks"] == {"identity": None}
    assert services["mail"]["read_only"] is True
    assert services["mail"]["cap_drop"] == ["ALL"]
    assert all("docker.sock" not in str(s) for s in services.values())
    for name in ("db", "tunnel"):
        assert "@sha256:" in services[name]["image"]
    tunnel = json.loads((config / "tunnel.yml").read_text())
    assert tunnel["ingress"][-1] == {"service": "http_status:404"}
    assert all(rule.get("service") != "http://keycloak:8080" for rule in tunnel["ingress"])
