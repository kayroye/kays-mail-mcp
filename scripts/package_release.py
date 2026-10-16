#!/usr/bin/env python3
"""Package committed source plus a digest-pinned image manifest; never private state."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

from setup import read_release_images


def package(output: Path, images: Path | None) -> Path:
    manifest = None
    if images is not None:
        read_release_images(images.parent)
        manifest = images.read_bytes()
    # Package exactly the Git revision, excluding ignored/untracked credentials and build output.
    source = subprocess.check_output(["git", "archive", "--format=tar", "HEAD"])
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "kays-mail-mcp.tar.gz"
    with (
        tarfile.open(fileobj=io.BytesIO(source)) as original,
        tarfile.open(archive, "w:gz") as target,
    ):
        for member in original.getmembers():
            member.name = "kays-mail-mcp/" + member.name
            payload = original.extractfile(member) if member.isfile() else None
            target.addfile(member, payload)
        if manifest is not None:
            entry = tarfile.TarInfo("kays-mail-mcp/release-images.json")
            entry.mode = 0o644
            entry.size = len(manifest)
            target.addfile(entry, io.BytesIO(manifest))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(digest + "  " + archive.name + "\n")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--images", type=Path)
    args = parser.parse_args()
    # Require the canonical manifest name so validation checks the exact bytes we ship.
    if args.images is not None and args.images.name != "release-images.json":
        raise SystemExit("Image manifest must be named release-images.json")
    if args.images is not None:
        json.loads(args.images.read_text())
    package(args.output, args.images)


if __name__ == "__main__":
    main()
