"""verify release archives include project assets but exclude private workspace data
check both source-built and prebuilt-image package variants
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


@pytest.mark.parametrize("prebuilt", [True, False])
def test_release_excludes_untracked_credentials_and_preserves_integrity(
    tmp_path: Path,
    prebuilt: bool,
) -> None:
    """catch packaging untracked credentials or omitting the requested pinned manifest"""
    source = tmp_path / "checkout"
    source.mkdir()
    (source / "public.txt").write_text("committed source")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "public.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    (source / ".env").write_text("synthetic-secret-do-not-package")
    (source / "secrets").mkdir()
    (source / "secrets/imap_password").write_text("another-synthetic-secret")
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
            str(Path(__file__).parents[1] / "scripts/package_release.py"),
            "--output",
            str(tmp_path / "out"),
            *(["--images", str(manifest)] if prebuilt else []),
        ],
        capture_output=True,
        text=True,
        cwd=source,
    )
    assert result.returncode == 0, result.stderr
    archive = tmp_path / "out/kays-mail-mcp.tar.gz"
    with tarfile.open(archive) as contents:
        names = contents.getnames()
        public = contents.extractfile("kays-mail-mcp/public.txt")
        assert public is not None and public.read() == b"committed source"
        assert ("kays-mail-mcp/release-images.json" in names) is prebuilt
        if prebuilt:
            packaged_manifest = contents.extractfile("kays-mail-mcp/release-images.json")
            assert (
                packaged_manifest is not None and packaged_manifest.read() == manifest.read_bytes()
            )
        assert not any(
            "/secrets/" in name or name.endswith("/.env")
            for name in names
        )
    assert (tmp_path / "out/SHA256SUMS").read_text() == (
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  kays-mail-mcp.tar.gz\n"
    )
