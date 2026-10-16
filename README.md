# kays-mail-mcp

Self-hosted, read-only email access for MCP-compatible agents.

**In development:** the current code is the upstream IMAP foundation. The one-script installer, email/password login, and public hosting integration are planned and are not ready yet. Do not expose the current unauthenticated MCP endpoint directly to the Internet.

Based on [ares952/MCPGenericIMAP](https://github.com/ares952/MCPGenericIMAP), used under the MIT License. See [UPSTREAM.md](UPSTREAM.md) for attribution.

## Upstream development instructions

# IMAP MCP Server

A production-minded, strictly read-only IMAP server for the Model Context Protocol
(MCP). It exposes Streamable HTTP at `/mcp` and supports exactly these tools:

- `health_check`
- `list_mailboxes`
- `search_messages`
- `get_message`
- `get_attachment`

Messages are identified by mailbox plus IMAP UID. Mailboxes are always selected with
`readonly=True`; the server has no send, flag, move, delete, or raw-command tool.

## Remote SSH development

Clone the repository on the Docker host and open that directory with VS Code Remote -
SSH. Python 3.11 or newer is required for development. Docker and the Compose plugin
are required for container verification.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
pytest
ruff check .
mypy
```

Automated tests use fakes and generated MIME messages; they do not access a mailbox.

## Configuration and secrets

Copy `.env.example` to the ignored `.env` file and set the host, port, username,
mailbox allowlist, and safety limits. TLS certificate verification cannot be disabled.
Supported TLS modes are `implicit_tls` and `starttls`.

Compose expects the password in an ignored file:

```bash
mkdir -p secrets
chmod 700 secrets
printf '%s' 'replace-with-the-real-password' > secrets/imap_password
sudo chown 10001:10001 secrets/imap_password
sudo chmod 600 secrets/imap_password
cp .env.example .env
```

The container runs as the non-root user and group `10001:10001`. File-backed Compose
secrets are bind-mounted with their host ownership and permissions, so a secret owned
by `root:root` with mode `0600` cannot be read by the application. The commands above
make the password readable only by the container's application identity.

To keep `root` as the owner instead, grant read access to the application group:

```bash
sudo chown root:10001 secrets/imap_password
sudo chmod 640 secrets/imap_password
```

Do not use mode `0644` and do not run the container as root merely to access the
secret. After changing ownership or permissions, recreate the service and verify its
health:

```bash
docker compose up -d --force-recreate mcp-server
docker compose ps
docker compose logs --tail=30 mcp-server
```

Do not add the password directly to `.env` when using Compose: the service injects
`IMAP_PASSWORD_FILE=/run/secrets/imap_password`. For a non-Compose launch, set exactly
one of `IMAP_PASSWORD` or `IMAP_PASSWORD_FILE` in the protected process environment.

The limits for results, body bytes, attachment bytes, query length, and socket timeout
are server configuration. Tool callers can request a smaller search page but cannot
raise these limits. Attachments are restricted to PDF, JPEG, PNG, CSV, and plain text;
accepted attachment bytes are returned as `content_base64`.

## Build and startup

```bash
docker compose build
docker compose up -d mcp-server
docker compose ps
docker compose logs --tail=100 mcp-server
```

The published endpoint is `http://127.0.0.1:8700/mcp` by default. Configure the
production and development ports centrally with `MCP_PORT` and `MCP_DEV_PORT` in
`.env`; Compose uses each value for the application listener, localhost publication,
and health check. The endpoint is not reachable from another host. The image runs as
UID 10001, uses a read-only filesystem, and keeps no persistent mailbox data.

The optional development profile mounts only `src/` read-only and uses port 8701:

```bash
docker compose --profile dev up mcp-server-dev
```

## Verification

Run the complete checks inside the image:

```bash
docker build --target test -t imap-mcp:test .
docker run --rm imap-mcp:test
```

Run the opt-in smoke test only against a disposable account configured through the
same IMAP environment variables:

```bash
IMAP_INTEGRATION_TEST=1 pytest -q tests/test_real_imap_opt_in.py
```

That smoke test lists mailboxes only. Broader real-account validation should verify
all tools using non-sensitive fixture mail while independently checking that no flags
or mailbox state change.

To inspect the running Streamable HTTP endpoint, use MCP Inspector 2 from a machine
that can reach the localhost-bound port. In web mode, pass the transport and server
URL explicitly:

```bash
npx @modelcontextprotocol/inspector \
  --web \
  --transport http \
  --server-url http://127.0.0.1:8700/mcp
```

Replace `8700` with the configured `MCP_PORT`. The Inspector web UI listens on remote
port `6274` by default. When working through VS Code Remote SSH, forward remote port
`6274` to local port `6274`. If local port `6274` is already occupied, VS Code may
silently choose `6275`; the resulting browser origin is then rejected by Inspector's
DNS-rebinding protection.

Prefer stopping the stale local process or port forward and restoring the
`6274 -> 6274` mapping. If a different local port is intentional, allow its exact
browser origin when starting Inspector. For example, for a browser URL beginning with
`http://127.0.0.1:6275`:

```bash
ALLOWED_ORIGINS=http://127.0.0.1:6275 \
npx @modelcontextprotocol/inspector \
  --web \
  --transport http \
  --server-url http://127.0.0.1:8700/mcp
```

`ALLOWED_ORIGINS` must contain the browser origin (`scheme://host:port`), not the MCP
server URL or port. Do not include a path, query string, or token, and do not disable
Inspector authentication or DNS-rebinding protection. Inspector does not accept a
wildcard localhost port, so a dynamically remapped port must be allowed explicitly.

For a non-browser discovery check, use CLI mode:

```bash
npx @modelcontextprotocol/inspector \
  --cli \
  --transport http \
  --server-url http://127.0.0.1:8700/mcp \
  --method tools/list
```

Confirm discovery of exactly the five tools listed above and that every tool has the
read-only annotation.

## Troubleshooting

- Configuration errors name the invalid variable but never print secret values.
- A TLS error normally means the hostname, port, trust store, or server certificate is
  wrong. Certificate verification is intentionally mandatory.
- An authentication error is deliberately generic. Verify the username and secret
  file permissions without printing the password.
- A missing mailbox may mean its exact IMAP name differs from the configured allowlist.
- Missing UID errors can occur after mailbox retention or deletion by another client;
  sequence numbers are never used as identifiers.
- Oversized bodies and attachments are rejected rather than truncated. Unsupported
  attachment types are rejected by default.
- Inspector web errors containing `Invalid origin` come from Inspector itself, not
  from this MCP endpoint. Check whether Remote SSH changed local port `6274` and set
  `ALLOWED_ORIGINS` to the exact origin shown in the browser address bar if needed.
- The Docker health check proves that the MCP TCP listener accepts connections; it does
  not authenticate to IMAP.

The Secure MCP Tunnel, ChatGPT Work configuration, and scheduled analysis are deferred
until this local milestone has passed container, Inspector, and disposable-account
verification.


## MCP connection to chatgpt

- Open https://platform.openai.com/settings/organization/api-keys
- new API key is needed:
  - create secrets/control_plane_api_key
  - copy there a new key from the openai website
  - restrict permissions to 600 and 65532:65532 not to be available to anyone
- Open https://platform.openai.com/settings/organization/tunnels
- it is needed to:
  - create a new tunnel
  - assign it to the personal organization
  - assign it to workspace, where it will be used
  - get tunnel ID, copy it to CONTROL_PLANE_TUNNEL_ID into .env file
  - create runtime API for tunnel client
  - do not share API key, do not put it to docker compose.yaml
- Open https://platform.openai.com/settings/organization/tunnels
  - click on Download tunnel-client and select the version you need (e.g. v0.0.10 for linux-amd64)
  - extract and store the file to tunnel-client folder
- build docker and check logs:
 ```
 docker compose logs --tail=100 tunnel-client
 ```
- verify tunnel_id
- verify health and conenctions:
```
curl -i http://127.0.0.1:8702/healthz
curl -i http://127.0.0.1:8702/readyz
```
- you should get e.g.:
```
HTTP/1.1 200 OK
Content-Type: text/plain; charset=utf-8
Date: Wed, 05 Aug 2026 14:04:16 GMT
Content-Length: 4

live
```
- go to Chatgpt Settings->Securitty and login
- enable Developer mode
- open ChatGPT Plugins (or browse for plugins)
- klick to + and enter e.g.:
  - change connection to Tunnel and select your tunnel
  - Name: My IMAP
  - Description: Read-only access to my IMAP mailbox
  - choose no authentication (tunnel is used)
  - agree with the risk
  - create plugin
  - and then connect
