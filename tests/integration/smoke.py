"""run disposable Keycloak, OAuth, and TLS containers with synthetic credentials
exercise the complete deployment flow without using a real mail account
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import importlib.util
import io
import json
import socket
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_ALPHA = "v0.1.0-alpha.1"


def load_setup(source: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("mail_setup", source / "scripts/setup.py")
    assert spec and spec.loader
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    return setup


def check_release_upgrade(
    setup: ModuleType, config: Path, command: list[str], original_alpha_image: str
) -> None:
    """offer a broken release and the current source bundle through the download boundary"""
    def container(service: str) -> str:
        return subprocess.check_output([*command, "ps", "-q", service], text=True).strip()

    def resume_session() -> None:
        subprocess.run(
            [*command, "exec", "-T", "mail", "python", "/fixtures/oauth_client.py", "--resume"],
            check=True,
        )

    def bundle(dockerfile: bytes | None = None) -> bytes:
        output = io.BytesIO()
        snapshot = subprocess.check_output(["git", "archive", "HEAD"], cwd=ROOT)
        with (
            tarfile.open(fileobj=io.BytesIO(snapshot)) as source,
            tarfile.open(fileobj=output, mode="w:gz") as target,
        ):
            for member in source:
                payload = source.extractfile(member) if member.isfile() else None
                if member.name == "Dockerfile" and dockerfile is not None:
                    member.size = len(dockerfile)
                    payload = io.BytesIO(dockerfile)
                member.name = "kays-mail-mcp/" + member.name
                target.addfile(member, payload)
        return output.getvalue()

    baseline = {name: container(name) for name in ("keycloak", "db", "gateway")}
    reader = container("mail")
    previous_id = subprocess.check_output(
        ["docker", "inspect", "--format", "{{.Image}}", reader], text=True
    )
    private_files = [
        *config.glob("*.env"), *config.glob("*.yaml"), *config.glob("*.json"),
        *config.glob("secrets/*"),
    ]
    before = {path: path.read_bytes() for path in private_files}
    broken = (
        f"FROM {original_alpha_image}\n"
        'CMD ["python", "-m", "http.server", "8700"]\n'
    ).encode()
    for tag, archive, expected_status in (
        ("v0.1.0-alpha.2-broken", bundle(broken), 1),
        ("v0.1.0-alpha.2-test", bundle(), 0),
    ):
        checksum = f"{hashlib.sha256(archive).hexdigest()}  kays-mail-mcp.tar.gz\n".encode()
        with patch.object(setup, "_download_release_asset", side_effect=[checksum, archive]):
            assert setup.main(["--config-dir", str(config), "--upgrade-release", tag]) == (
                expected_status
            )
        assert baseline == {name: container(name) for name in baseline}
        assert container("mail") != reader
        reader = container("mail")
        updated_id = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.Image}}", reader], text=True
        )
        assert (updated_id != previous_id) == (expected_status == 0)
        assert all(
            path.read_bytes() == data for path, data in before.items()
            if path.name != "compose.env" or expected_status == 1
        )
        if expected_status == 0:
            env = config / "compose.env"
            previous_settings = {line for line in before[env].splitlines()
                                 if not line.startswith(b"MAIL_IMAGE=")}
            assert previous_settings <= set(env.read_bytes().splitlines())
            assert setup.main(["--config-dir", str(config), "--upgrade"]) == 1
            assert container("mail") == reader
        resume_session()
    print("PASS: published alpha rollback and upgrade preserved private settings and OAuth login")


def main() -> None:
    """prepare temporary state, run the container smoke flow, and always tear it down"""
    setup = load_setup(ROOT)
    release_upgrade = "--release-upgrade" in sys.argv
    # keep generated secrets, certificates, and service state inside one temporary directory
    with tempfile.TemporaryDirectory(prefix="kays-mail-integration-") as directory:
        work = Path(directory)
        config = work / "config"
        install = setup
        alpha_image = ""
        if release_upgrade:
            published = work / "published"
            published.mkdir()
            alpha_image = setup._stage_release_image(PUBLISHED_ALPHA, published)
            install = load_setup(published / "kays-mail-mcp")
        install.prepare(
            config,
            {
                "mcp_url": "https://mail.example.test",
                "login_url": "https://login.example.test",
                "login_email": "owner@example.test",
                "imap_host": "imap.mail.me.com",
                "imap_username": "fixture@icloud.com",
                "mailboxes": "INBOX",
                "redirect_uris": setup.DEFAULT_REDIRECT_URIS,
            },
            "synthetic-mail-password",
            "synthetic-owner-password",
        )
        with socket.socket() as listener:
            # reserve a free loopback port for the local Keycloak administration listener
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with (config / "compose.env").open("a") as stream:
            stream.write(f"ADMIN_PORT={port}\n")
            if not release_upgrade:
                # Local smoke builds must never retag images used by a real installation.
                tag = f"integration-{uuid.uuid4().hex}"
                stream.write(f"MAIL_IMAGE=kays-mail-mcp:{tag}\n")
                stream.write(f"KEYCLOAK_IMAGE=kays-mail-mcp-keycloak:{tag}\n")
        fixtures = work / "fixtures"
        fixtures.mkdir(mode=0o700)
        # create a short-lived self-signed certificate for the two fixture hostnames
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable mail MCP fixture")])
        now = dt.datetime.now(dt.UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.DNSName("mail.example.test"), x509.DNSName("login.example.test")]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        (fixtures / "cert.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        (fixtures / "key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (fixtures / "key.pem").chmod(0o600)
        (fixtures / "oauth_client.py").write_bytes(
            (ROOT / "tests/integration/oauth_client.py").read_bytes()
        )
        nginx = (
            (config / "nginx.conf")
            .read_text()
            .replace(
                "  access_log off;",
                "  access_log off;\n  ssl_certificate /fixtures/cert.pem;\n"
                "  ssl_certificate_key /fixtures/key.pem;",
            )
        )
        # Several back-to-back login/replay probes need more burst capacity in this fixture.
        nginx = nginx.replace("zone=oauth burst=10", "zone=oauth burst=40")
        nginx = nginx.replace(
            "listen 8080 default_server;",
            "listen 8080 default_server; listen 443 ssl default_server;",
        )
        nginx = nginx.replace("listen 8080;", "listen 8080; listen 443 ssl;")
        (config / "nginx.conf").write_text(nginx)
        override = {
            "services": {
                "mail": {
                    "environment": {
                        "SSL_CERT_FILE": "/fixtures/cert.pem",
                        "FASTMCP_LOG_LEVEL": "ERROR",
                    },
                    "volumes": [str(fixtures) + ":/fixtures:ro"],
                },
                "gateway": {
                    "volumes": [str(fixtures) + ":/fixtures:ro"],
                    "networks": {
                        "ingress": {"aliases": ["mail.example.test", "login.example.test"]}
                    },
                },
            }
        }
        # setup's management commands must use the same test-only deployment overlay.
        overlay = config / "compose.security.yaml"
        overlay.write_text(json.dumps(override))
        overlay.chmod(0o600)
        # reuse the generated Compose files and layer test-only TLS aliases over them
        command = [
            "docker",
            "compose",
            "--env-file",
            str(config / "compose.env"),
            "-f",
            str(config / "compose.yaml"),
            "-f",
            str(overlay),
        ]
        try:
            subprocess.run(
                [
                    *command, "up", "-d", "--no-build" if release_upgrade else "--build",
                    "--wait", "--wait-timeout", "240",
                ],
                check=True,
            )
            (config / "bootstrap/mail-realm.json").unlink(missing_ok=True)
            if release_upgrade:
                subprocess.run(
                    [*command, "exec", "-T", "mail", "python", "/fixtures/oauth_client.py",
                     "--idle-days", "1"],
                    check=True,
                )
                check_release_upgrade(setup, config, command, alpha_image)
                return
            subprocess.run(
                [*command, "exec", "-T", "mail", "python", "/fixtures/oauth_client.py"], check=True
            )
            # Exercise the same local administrator migration used on existing installations.
            setup.configure_sessions(config, "120", "60")
            subprocess.run(
                [
                    *command,
                    "exec",
                    "-T",
                    "mail",
                    "python",
                    "-c",
                    "from pathlib import Path; Path('/state/integration-session.json').unlink()",
                ],
                check=True,
            )
            subprocess.run(
                [
                    *command,
                    "exec",
                    "-T",
                    "mail",
                    "python",
                    "/fixtures/oauth_client.py",
                    "--idle-days",
                    "60",
                ],
                check=True,
            )
            # verify state survives restarting the same service without rebuilding or reprovisioning
            subprocess.run([*command, "restart", "mail"], check=True)
            subprocess.run([*command, "up", "-d", "--wait", "--wait-timeout", "60"], check=True)
            subprocess.run(
                [*command, "exec", "-T", "mail", "python", "/fixtures/oauth_client.py", "--resume"],
                check=True,
            )
        except subprocess.CalledProcessError:
            subprocess.run([*command, "logs", "--tail", "150", "mail"], check=False)
            raise
        finally:
            subprocess.run(
                [*command, "down", "-v", "--remove-orphans"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main()
