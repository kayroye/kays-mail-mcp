"""simulate a disposable browser OAuth flow from inside the smoke-test mail container
use synthetic credentials to verify TLS, callback policy, token exchange, and MCP access
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx2


class Form(HTMLParser):
    """collect a form action and its hidden values from an identity page"""

    def __init__(self, html: str) -> None:
        """parse one HTML page and initialize the fields used by the client flow"""
        super().__init__()
        self.action = ""
        self.values: dict[str, str] = {}
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """capture the current form action and hidden input values"""
        data = dict(attrs)
        if tag == "form":
            self.action = data.get("action") or ""
        if tag == "input" and data.get("name") and data.get("type") == "hidden":
            self.values[str(data["name"])] = data.get("value") or ""


def main() -> None:
    """run or resume the synthetic OAuth client flow and verify protected MCP calls"""
    base = "https://mail.example.test"
    if "--resume" in sys.argv:
        # check that a refreshed access token remains valid after the mail container restarts
        tokens = json.loads(Path("/state/integration-session.json").read_text())
        with httpx2.Client(timeout=20) as client:
            result = client.post(
                base + "/mcp",
                headers={
                    "Authorization": "Bearer " + tokens["access_token"],
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "health_check", "arguments": {}},
                },
            )
            assert result.status_code == 200, result.status_code
            assert not result.json()["result"].get("isError")
        print("PASS: previously issued token works after container restart")
        return
    callback = "https://chatgpt.com/connector_platform_oauth_redirect"
    # derive the PKCE challenge from a verifier kept only in this client process
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    with httpx2.Client(timeout=20, follow_redirects=False, trust_env=True) as client:
        assert client.post(base + "/mcp", json={}).status_code == 401
        metadata = client.get(base + "/.well-known/oauth-authorization-server").json()
        assert metadata["authorization_response_iss_parameter_supported"] is True
        protected = client.get(base + "/.well-known/oauth-protected-resource/mcp").json()
        assert protected["authorization_servers"] == [metadata["issuer"]]
        assert client.get("https://login.example.test/admin/").status_code == 404
        assert client.get("https://login.example.test/realms/master/").status_code == 404
        # register a public client using only the callback allowed by this integration setup
        registration = client.post(
            base + "/register",
            json={
                "client_name": "Synthetic integration fixture",
                "redirect_uris": [callback],
                "token_endpoint_auth_method": "none",
                "scope": "openid email profile",
            },
        )
        assert registration.status_code == 201, registration.status_code
        client_id = registration.json()["client_id"]
        response = client.get(
            base + "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": callback,
                "response_type": "code",
                "scope": "openid email profile",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "fixture-state",
                "resource": base + "/mcp",
            },
        )
        # follow login and consent pages until the authorization server redirects to the callback
        for _ in range(12):
            if response.status_code in (301, 302, 303, 307, 308):
                destination = urljoin(str(response.url), response.headers["location"])
                if destination.startswith(callback):
                    query = parse_qs(urlsplit(destination).query)
                    assert query.get("state") == ["fixture-state"]
                    assert query.get("iss") == [metadata["issuer"]]
                    assert "code" in query, query.get("error")
                    break
                response = client.get(destination)
            else:
                assert response.status_code == 200, response.status_code
                form = Form(response.text)
                data = form.values
                if urlsplit(str(response.url)).hostname == "mail.example.test":
                    # approve only after the proxy presents the expected consent form
                    assert "csrf_token" in data
                    data["action"] = "approve"
                else:
                    data.update(username="owner@example.test", password="synthetic-owner-password")
                response = client.post(
                    urljoin(str(response.url), form.action),
                    data=data,
                    headers={
                        "Origin": str(response.url).split("/realms/")[0].split("/consent")[0],
                        "Referer": str(response.url),
                        "Sec-Fetch-Site": "same-origin",
                    },
                )
        else:
            raise AssertionError("OAuth redirect loop did not finish")
        exchange = client.post(
            base + "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": query["code"][0],
                "redirect_uri": callback,
                "code_verifier": verifier,
                "resource": base + "/mcp",
            },
        )
        assert exchange.status_code == 200, (exchange.status_code, exchange.text[:150])
        tokens = exchange.json()
        # use the issued owner token for initialization and a harmless health tool call
        headers = {
            "Authorization": "Bearer " + tokens["access_token"],
            "Accept": "application/json, text/event-stream",
        }
        initialized = client.post(
            base + "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "fixture", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, (initialized.status_code, initialized.text[:400])
        assert initialized.json()["result"]["serverInfo"]["name"] == "kays-mail-mcp"
        result = client.post(
            base + "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "health_check", "arguments": {}},
            },
        )
        assert result.status_code == 200
        assert not result.json()["result"].get("isError")
        refreshed = client.post(
            base + "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
                "resource": base + "/mcp",
            },
        )
        assert refreshed.status_code == 200
        # persist only the refreshed token for the restart half of the smoke test
        fd = os.open("/state/integration-session.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"access_token": refreshed.json()["access_token"]}, stream)
        print(
            "PASS: TLS, route isolation, consent, password login, PKCE, owner MCP call and refresh"
        )


if __name__ == "__main__":
    main()
