"""OIDC configuration and single-owner authorization; OAuth is delegated to FastMCP."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier

from .config import SettingsError


@dataclass(frozen=True)
class AuthSettings:
    public_url: str
    issuer: str
    discovery_url: str
    client_id: str
    client_secret: str = field(repr=False)
    signing_key: str = field(repr=False)
    owner_subject: str
    redirect_uris: tuple[str, ...]


def read_secret(path: str, name: str) -> str:
    """Read small, regular, owner-only secret files without following symlinks."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise SettingsError(f"{name} must be an owner-only regular file")
            value = stream.read(4097).strip()
    except (OSError, UnicodeError):
        raise SettingsError(f"{name} could not be read") from None
    if not value or len(value) > 4096:
        raise SettingsError(f"{name} is empty or too large")
    return value


def https_url(value: str, name: str, *, origin_only: bool = False) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (origin_only and parsed.path not in ("", "/"))
    ):
        raise SettingsError(f"{name} must be a valid HTTPS URL")
    return value.rstrip("/")


def load_auth_settings(environ: Mapping[str, str] | None = None) -> AuthSettings:
    env = os.environ if environ is None else environ

    def required(name: str) -> str:
        value = env.get(name, "").strip()
        if not value or any(ord(c) < 32 for c in value):
            raise SettingsError(f"{name} is required and must not contain control characters")
        return value

    public_url = https_url(required("MCP_PUBLIC_URL"), "MCP_PUBLIC_URL", origin_only=True)
    issuer = https_url(required("OIDC_ISSUER"), "OIDC_ISSUER")
    signing_key = read_secret(required("MCP_SIGNING_KEY_FILE"), "MCP_SIGNING_KEY_FILE")
    if len(signing_key) < 32:
        raise SettingsError("MCP signing key requires at least 32 random characters")
    redirects = tuple(uri.strip() for uri in required("MCP_ALLOWED_REDIRECT_URIS").split(","))
    for uri in redirects:
        parsed = urlsplit(uri)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or "*"
            in parsed.netloc.replace("127.0.0.1:*", "127.0.0.1:1").replace(
                "localhost:*", "localhost:1"
            )
            or parsed.scheme not in ("https", "http")
            or (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost"))
        ):
            raise SettingsError("client redirect must be HTTPS or a loopback HTTP URL")
    discovery = env.get("OIDC_DISCOVERY_URL", issuer + "/.well-known/openid-configuration")
    if discovery != "http://keycloak:8080/realms/mail/.well-known/openid-configuration":
        https_url(discovery, "OIDC_DISCOVERY_URL")
    return AuthSettings(
        public_url,
        issuer,
        discovery,
        required("OIDC_CLIENT_ID"),
        read_secret(required("OIDC_CLIENT_SECRET_FILE"), "OIDC_CLIENT_SECRET_FILE"),
        signing_key,
        required("MCP_OWNER_SUBJECT"),
        redirects,
    )


class OwnerJWTVerifier(JWTVerifier):
    """Require a verified, expiring upstream token for the exact owner subject."""

    def __init__(self, *, owner_subject: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.owner_subject = owner_subject

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await super().verify_token(token)
        if (
            verified is None
            or verified.expires_at is None
            or verified.claims.get("sub") != self.owner_subject
        ):
            return None
        return verified


def create_auth(settings: AuthSettings) -> OIDCProxy:
    verifier = OwnerJWTVerifier(
        owner_subject=settings.owner_subject,
        jwks_uri=settings.issuer + "/protocol/openid-connect/certs",
        issuer=settings.issuer,
        audience=settings.client_id,
        algorithm="RS256",
        required_scopes=["openid"],
    )
    provider = OIDCProxy(
        config_url=settings.discovery_url,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        base_url=settings.public_url,
        token_verifier=verifier,
        jwt_signing_key=settings.signing_key.encode(),
        allowed_client_redirect_uris=list(settings.redirect_uris),
        require_authorization_consent=True,
        valid_scopes=["openid", "email", "profile"],
        forward_resource=False,
        fastmcp_access_token_expiry_seconds=300,
        fallback_access_token_expiry_seconds=300,
        fallback_refresh_token_expiry_seconds=86400,
        enable_cimd=False,
    )
    if str(provider.oidc_config.issuer).rstrip("/") != settings.issuer:
        raise SettingsError("OIDC discovery issuer does not match the configured issuer")
    return provider
