"""run disposable Keycloak, OAuth, and TLS containers with synthetic credentials
exercise the complete deployment flow without using a real mail account
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import socket
import subprocess
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    """prepare temporary state, run the container smoke flow, and always tear it down"""
    spec = importlib.util.spec_from_file_location("mail_setup", ROOT / "scripts/setup.py")
    assert spec and spec.loader
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    # keep generated secrets, certificates, and service state inside one temporary directory
    with tempfile.TemporaryDirectory(prefix="kays-mail-integration-") as directory:
        work = Path(directory)
        config = work / "config"
        setup.prepare(
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
        overlay = work / "test-compose.json"
        overlay.write_text(json.dumps(override))
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
                [*command, "up", "-d", "--build", "--wait", "--wait-timeout", "240"], check=True
            )
            subprocess.run(
                [*command, "exec", "-T", "mail", "python", "/fixtures/oauth_client.py"], check=True
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
