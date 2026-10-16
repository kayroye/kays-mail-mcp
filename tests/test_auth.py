"""verify owner-only authorization, OIDC validation, and callback policy
use generated signing keys and a local discovery endpoint instead of external identity services
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient
from test_server import settings

from imap_mcp.auth import OwnerJWTVerifier, load_auth_settings
from imap_mcp.config import SettingsError
from imap_mcp.server import create_server


def test_auth_configuration_fails_closed_without_secrets() -> None:
    """check missing OIDC settings stop startup"""
    with pytest.raises(SettingsError):
        load_auth_settings({})


def test_auth_configuration_rejects_http_and_short_signing_key(tmp_path: Path) -> None:
    """check public URLs require HTTPS and signing keys meet the minimum length"""
    secret = tmp_path / "secret"
    secret.write_text("x" * 40)
    secret.chmod(0o600)
    env = {
        "MCP_PUBLIC_URL": "http://mail.example.test",
        "OIDC_ISSUER": "https://login.example.test/realms/mail",
        "OIDC_CLIENT_ID": "mail-mcp",
        "OIDC_CLIENT_SECRET_FILE": str(secret),
        "MCP_SIGNING_KEY_FILE": str(secret),
        "MCP_OWNER_SUBJECT": "owner",
        "MCP_ALLOWED_REDIRECT_URIS": "http://127.0.0.1:*/callback/*",
    }
    with pytest.raises(SettingsError, match="HTTPS"):
        load_auth_settings(env)
    env["MCP_PUBLIC_URL"] = "https://mail.example.test"
    secret.write_text("short")
    with pytest.raises(SettingsError, match="32"):
        load_auth_settings(env)


def make_verifier() -> tuple[OwnerJWTVerifier, rsa.RSAPrivateKey]:
    """build an owner verifier and its matching test signing key"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return OwnerJWTVerifier(
        owner_subject="owner-uuid",
        public_key=public.decode(),
        issuer="https://login.example.test/realms/mail",
        audience="mail-mcp",
        algorithm="RS256",
    ), key


def token(key: rsa.RSAPrivateKey, **changes: object) -> str:
    """sign a valid owner token with optional claim overrides"""
    claims = {
        "iss": "https://login.example.test/realms/mail",
        "aud": "mail-mcp",
        "sub": "owner-uuid",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
    }
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "someone-else"},
        {"iss": "https://attacker.test"},
        {"aud": "another-app"},
        {"exp": 1},
        {"exp": None},
        {"sub": ""},
    ],
)
def test_wrong_identity_or_invalid_token_cannot_access_mail(claims: dict[str, object]) -> None:
    """check subject, issuer, audience, and expiry validation reject the token"""
    verifier, key = make_verifier()
    assert asyncio.run(verifier.verify_token(token(key, **claims))) is None


def test_http_transport_rejects_anonymous_and_nonowner_before_tool_dispatch() -> None:
    """check unauthenticated and nonowner requests fail before MCP initialization"""
    verifier, key = make_verifier()
    server = create_server(settings(), auth=verifier)
    with TestClient(server.http_app(stateless_http=True, json_response=True)) as client:
        assert client.post("/mcp", json={}).status_code == 401
        assert (
            client.post(
                "/mcp",
                json={},
                headers={"Authorization": "Bearer " + token(key, sub="someone-else")},
            ).status_code
            == 401
        )
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "fixture", "version": "1"},
            },
        }
        response = client.post(
            "/mcp",
            json=payload,
            headers={
                "Authorization": "Bearer " + token(key),
                "Accept": "application/json, text/event-stream",
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "kays-mail-mcp"


def test_oauth_discovery_and_client_registration_enforce_our_callback_policy() -> None:
    """check discovery, PKCE metadata, and dynamic callback registration restrictions"""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from imap_mcp.auth import AuthSettings, create_auth

    issuer = "https://login.example.test/realms/mail"

    class Discovery(BaseHTTPRequestHandler):
        """serve only the OIDC discovery document needed by the local proxy fixture"""

        def do_GET(self) -> None:
            """return issuer and endpoint metadata for the test OIDC client"""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "issuer": issuer,
                        "authorization_endpoint": issuer + "/protocol/openid-connect/auth",
                        "token_endpoint": issuer + "/protocol/openid-connect/token",
                        "jwks_uri": issuer + "/protocol/openid-connect/certs",
                        "response_types_supported": ["code"],
                        "subject_types_supported": ["public"],
                        "id_token_signing_alg_values_supported": ["RS256"],
                    }
                ).encode()
            )

        def log_message(self, *_: object) -> None:
            """silence the local HTTP server request log"""
            pass

    discovery = HTTPServer(("127.0.0.1", 0), Discovery)
    thread = threading.Thread(target=discovery.serve_forever, daemon=True)
    thread.start()
    try:
        auth = create_auth(
            AuthSettings(
                "https://mail.example.test",
                issuer,
                f"http://127.0.0.1:{discovery.server_port}/discovery",
                "mail-mcp",
                "synthetic-client-secret",
                "x" * 40,
                "owner-uuid",
                ("http://127.0.0.1:*/callback",),
            )
        )
        server = create_server(settings(), auth=auth)
        with TestClient(server.http_app(stateless_http=True)) as client:
            metadata = client.get("/.well-known/oauth-authorization-server").json()
            assert metadata["code_challenge_methods_supported"] == ["S256"]
            assert metadata["authorization_response_iss_parameter_supported"] is True
            bad = client.post(
                "/register",
                json={
                    "redirect_uris": ["https://attacker.test/callback"],
                    "token_endpoint_auth_method": "none",
                },
            )
            assert bad.status_code == 400
            good = client.post(
                "/register",
                json={
                    "redirect_uris": ["http://127.0.0.1:42123/callback"],
                    "token_endpoint_auth_method": "none",
                    "scope": "openid",
                },
            )
            assert good.status_code == 201
            denied = client.get(
                "/authorize",
                params={
                    "client_id": good.json()["client_id"],
                    "redirect_uri": "http://127.0.0.1:42123/callback",
                    "response_type": "code",
                    "scope": "openid",
                },
                follow_redirects=False,
            )
            assert denied.status_code in (400, 302)
            if denied.status_code == 302:
                assert "error=invalid_request" in denied.headers["location"]
                assert "code=" not in denied.headers["location"]
    finally:
        discovery.shutdown()
        discovery.server_close()
        thread.join()
