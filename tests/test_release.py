from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


@pytest.mark.parametrize("prebuilt", [True, False])
def test_release_archive_contains_setup_and_attribution_but_no_private_state(
    tmp_path: Path,
    prebuilt: bool,
) -> None:
    manifest = tmp_path / "release-images.json"
    manifest.write_text(
        json.dumps(
            {
                "mail": "ghcr.io/example/mail@sha256:" + "a" * 64,
                "keycloak": "ghcr.io/example/login@sha256:" + "b" * 64,
            }
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/package_release.py",
            "--output",
            str(tmp_path / "out"),
            *(["--images", str(manifest)] if prebuilt else []),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    archive = tmp_path / "out/kays-mail-mcp.tar.gz"
    with tarfile.open(archive) as contents:
        names = contents.getnames()
        assert "kays-mail-mcp/setup.sh" in names
        assert "kays-mail-mcp/LICENSE" in names
        assert "kays-mail-mcp/UPSTREAM.md" in names
        assert ("kays-mail-mcp/release-images.json" in names) is prebuilt
        assert not any(
            "/.git/" in name
            or "/secrets/" in name
            or "/.venv/" in name
            or "/.superpowers/" in name
            or name.endswith("/.env")
            for name in names
        )
    assert (tmp_path / "out/SHA256SUMS").read_text() == (
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  kays-mail-mcp.tar.gz\n"
    )
