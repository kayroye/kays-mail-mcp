#!/usr/bin/env python3
"""Prepare a private, rerunnable deployment without putting secrets in Git or argv."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REDIRECT_URIS = (
    "http://127.0.0.1:*/callback,http://127.0.0.1:*/callback/*,"
    "http://localhost:*/callback,https://chatgpt.com/connector_platform_oauth_redirect"
)


def _clean(value: str, name: str) -> str:
    if not value or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name} is empty, too long or contains control characters")
    return value


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname)
    ):
        raise ValueError("Public addresses must be distinct HTTPS hostnames without a path")
    return "https://" + parsed.hostname.lower()


def _write(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)


def _env(values: dict[str, str]) -> str:
    return "".join(
        name + "='" + value.replace("'", "\\'") + "'\n" for name, value in values.items()
    )


def read_release_images(source: Path) -> dict[str, str]:
    manifest = source / "release-images.json"
    if not manifest.exists():
        return {}
    images = json.loads(manifest.read_text())
    if not isinstance(images, dict) or set(images) != {"mail", "keycloak"}:
        raise ValueError("Release manifest must contain two digest-pinned images")
    for value in images.values():
        if not isinstance(value, str) or not re.fullmatch(
            r"ghcr\.io/[a-z0-9_./-]+@sha256:[a-f0-9]{64}", value
        ):
            raise ValueError("Release images must use a GHCR sha256 digest")
    return {"MAIL_IMAGE": images["mail"], "KEYCLOAK_IMAGE": images["keycloak"]}


def prepare(config: Path, answers: dict[str, str], imap_password: str, login_password: str) -> None:
    """Write a new configuration once. Existing complete installs are never overwritten."""
    if os.getuid() == 0:
        raise ValueError("Run setup as a non-root user with Docker access")
    if config.is_symlink():
        raise ValueError("Configuration directory must not be a symlink")
    config = config.absolute()
    if config.resolve().is_relative_to(ROOT):
        raise ValueError("Choose a configuration directory outside the checkout")
    if (config / "settings.json").exists():
        validate_existing(config)
        return
    data = {name: _clean(value.strip(), name) for name, value in answers.items()}
    mcp_url, login_url = _origin(data["mcp_url"]), _origin(data["login_url"])
    if mcp_url == login_url:
        raise ValueError("MCP and login hostnames must differ")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", data["imap_host"]):
        raise ValueError("IMAP host must be a hostname")
    if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", data["login_email"]):
        raise ValueError("Login email must be a valid email address")
    for uri in data["redirect_uris"].split(","):
        parsed = urlsplit(uri.strip())
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.scheme not in ("https", "http")
            or "*" in parsed.hostname
            or (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost"))
        ):
            raise ValueError("Client callbacks must use HTTPS or loopback HTTP")
    _clean(imap_password, "IMAP password")
    _clean(login_password, "login password")
    if len(login_password) < 12:
        raise ValueError("Use at least 12 characters for the login password")
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(config.iterdir()):
        raise ValueError("Incomplete/nonempty configuration: inspect it before trying again")
    config.chmod(0o700)
    for directory in ("secrets", "bootstrap", "keycloak-data", "auth-state"):
        (config / directory).mkdir(mode=0o700)
    images = read_release_images(ROOT)
    private = {
        name: secrets.token_urlsafe(48)
        for name in ("signing_key", "oidc_client_secret", "db_password", "admin_password")
    }
    private["imap_password"] = imap_password
    for name, value in private.items():
        _write(config / "secrets" / name, value)
    subject = str(uuid.uuid4())
    realm = {
        "realm": "mail",
        "enabled": True,
        "registrationAllowed": False,
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": False,
        "bruteForceProtected": True,
        "failureFactor": 5,
        "waitIncrementSeconds": 60,
        "maxFailureWaitSeconds": 900,
        "accessTokenLifespan": 300,
        "ssoSessionIdleTimeout": 86400,
        "ssoSessionMaxLifespan": 604800,
        "revokeRefreshToken": True,
        "refreshTokenMaxReuse": 0,
        "sslRequired": "external",
        "users": [
            {
                "id": subject,
                "username": data["login_email"].lower(),
                "email": data["login_email"].lower(),
                "emailVerified": True,
                "enabled": True,
                "firstName": "Mailbox",
                "lastName": "Owner",
                "requiredActions": [],
                "credentials": [{"type": "password", "value": login_password, "temporary": False}],
            }
        ],
        "clients": [
            {
                "clientId": "mail-mcp",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "secret": private["oidc_client_secret"],
                "standardFlowEnabled": True,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False,
                "redirectUris": [mcp_url + "/auth/callback"],
                "defaultClientScopes": ["basic", "email", "profile"],
                "attributes": {"pkce.code.challenge.method": "S256"},
                "protocolMappers": [
                    {
                        "name": "mail-mcp-audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "consentRequired": False,
                        "config": {
                            "included.client.audience": "mail-mcp",
                            "access.token.claim": "true",
                            "id.token.claim": "false",
                        },
                    }
                ],
            }
        ],
    }
    _write(config / "bootstrap/mail-realm.json", json.dumps(realm))
    (config / "compose.yaml").write_bytes((ROOT / "deploy/compose.yaml").read_bytes())
    (config / "compose.yaml").chmod(0o600)
    _write(
        config / "compose.env",
        _env(
            {
                "CONFIG_DIR": str(config),
                "SOURCE_DIR": str(ROOT),
                "PUID": str(os.getuid()),
                "PGID": str(os.getgid()),
                "INSTANCE_ID": subject[:8],
                "LOGIN_PUBLIC_URL": login_url,
                "ADMIN_PORT": "8870",
                **images,
            }
        ),
    )
    _write(
        config / "mail.env",
        _env(
            {
                "IMAP_HOST": data["imap_host"],
                "IMAP_PORT": "993",
                "IMAP_USERNAME": data["imap_username"],
                "IMAP_ALLOWED_MAILBOXES": data["mailboxes"],
                "MCP_PUBLIC_URL": mcp_url,
                "OIDC_ISSUER": login_url + "/realms/mail",
                "OIDC_CLIENT_ID": "mail-mcp",
                "MCP_OWNER_SUBJECT": subject,
                "MCP_ALLOWED_REDIRECT_URIS": data["redirect_uris"],
            }
        ),
    )
    nginx = (ROOT / "deploy/nginx.conf.template").read_text()
    nginx = nginx.replace("@MCP_HOST@", urlsplit(mcp_url).hostname or "")
    nginx = nginx.replace("@LOGIN_HOST@", urlsplit(login_url).hostname or "")
    _write(config / "nginx.conf", nginx)
    _write(
        config / "tunnel.yml",
        json.dumps(
            {
                "ingress": [
                    {"hostname": urlsplit(mcp_url).hostname, "service": "http://gateway:8080"},
                    {"hostname": urlsplit(login_url).hostname, "service": "http://gateway:8080"},
                    {"service": "http_status:404"},
                ]
            },
            indent=2,
        ),
    )
    # Commit marker is last. Incomplete installs never silently replace secrets.
    _write(
        config / "settings.json",
        json.dumps(
            {**data, "mcp_url": mcp_url, "login_url": login_url, "owner_subject": subject}, indent=2
        ),
    )


def validate_existing(config: Path) -> None:
    for path in [
        config,
        config / "secrets",
        config / "bootstrap",
        config / "auth-state",
        config / "keycloak-data",
        config / "settings.json",
        config / "compose.env",
        config / "mail.env",
        config / "nginx.conf",
        config / "compose.yaml",
        *sorted((config / "secrets").glob("*")),
    ]:
        info = path.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
        ):
            raise ValueError("Configuration must contain owner-only regular files/directories")
    for name in (
        "imap_password",
        "signing_key",
        "oidc_client_secret",
        "db_password",
        "admin_password",
    ):
        if not (config / "secrets" / name).is_file():
            raise ValueError("A required secret file is missing; restore it from backup")


def prerequisites() -> None:
    if shutil.which("docker") is None:
        raise ValueError("Docker is required. Install Docker Engine and Docker Compose v2 first.")
    result = subprocess.run(
        ["docker", "compose", "version", "--short"], capture_output=True, text=True, check=False
    )
    if result.returncode or not result.stdout.strip().startswith("2."):
        raise ValueError("Docker Compose v2 is required. Install the Compose plugin first.")
    if subprocess.run(
        ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    ).returncode:
        raise ValueError("Docker is not accessible. Start Docker and check your user permissions.")


def compose(config: Path, arguments: list[str]) -> None:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(config / "compose.env"),
            "-f",
            str(config / "compose.yaml"),
            *arguments,
        ],
        check=False,
    )
    if result.returncode:
        raise ValueError(
            "Service startup failed. Inspect local container status; configuration is preserved."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kays-mail-mcp",
    )
    parser.add_argument("--check", action="store_true", help="check prerequisites without changes")
    parser.add_argument("--no-start", action="store_true", help="prepare configuration only")
    parser.add_argument(
        "--public", action="store_true", help="enable a separately configured Cloudflare Tunnel"
    )
    args = parser.parse_args(argv)
    try:
        prerequisites()
        config = args.config_dir.absolute()
        if args.check:
            if (config / "settings.json").exists():
                validate_existing(config)
            print("Prerequisites checked. No services or configuration changed.")
            return 0
        if not (config / "settings.json").exists():
            if not sys.stdin.isatty():
                raise ValueError(
                    "Initial setup needs an interactive terminal for hidden password entry"
                )
            print(
                "Private setup: passwords stay on this server. Use a dedicated mail app password."
            )
            data = {
                "mcp_url": input("MCP HTTPS URL: ").strip(),
                "login_url": input("Login HTTPS URL (different hostname): ").strip(),
                "login_email": input("Login email: ").strip(),
                "imap_host": input("IMAP host [imap.mail.me.com]: ").strip() or "imap.mail.me.com",
                "imap_username": input(
                    "IMAP username (underlying iCloud address for iCloud): "
                ).strip(),
                "mailboxes": input("Mailboxes [INBOX]: ").strip() or "INBOX",
                "redirect_uris": input(
                    "Allowed client callback URLs, comma-separated [local Codex + ChatGPT web]: "
                ).strip()
                or DEFAULT_REDIRECT_URIS,
            }
            password = getpass.getpass("Mail app-specific password: ")
            login_password = getpass.getpass("New MCP login password (12+ characters): ")
            if login_password != getpass.getpass("Confirm MCP login password: "):
                raise ValueError("Login passwords did not match")
            prepare(config, data, password, login_password)
        validate_existing(config)
        if args.no_start:
            print(f"Private configuration prepared at {config}. Services were not started.")
            return 0
        build_mode = "--no-build" if read_release_images(ROOT) else "--build"
        compose(config, ["up", "-d", build_mode, "--wait", "--wait-timeout", "240"])
        # Keycloak has imported/hashed the login credential; remove its plaintext bootstrap copy.
        (config / "bootstrap/mail-realm.json").unlink(missing_ok=True)
        if args.public:
            token_file = config / "secrets/tunnel_token"
            if not token_file.exists():
                print(
                    "First create a Cloudflare Tunnel and route BOTH hostnames to http://gateway:8080."
                )
                print("See docs/quickstart.md. The gateway blocks identity administration paths.")
                _write(
                    token_file, _clean(getpass.getpass("Cloudflare tunnel token: "), "tunnel token")
                )
            compose(config, ["--profile", "public", "up", "-d", "tunnel"])
        print("Services started. Public connectivity and client login still need verification.")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, EOFError, KeyboardInterrupt):
        print(
            "Setup could not finish. Check prerequisites and inputs; existing state is preserved.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
