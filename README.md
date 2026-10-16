# kays-mail-mcp

Read-only email access for your agents, hosted on your own server.

Search mail, read messages and retrieve attachments through a standard HTTP MCP
endpoint. Works with IMAP providers, including iCloud Mail and custom domains
hosted by iCloud. Thunderbird is not required.

**Status: pre-release development.** The installer and authenticated deployment
are being verified. No independent security audit has been performed. Do not
expose an IMAP MCP process directly to the Internet.

## Quick start

On a Linux server with Docker Engine, Docker Compose v2 and Python 3.11+:

```bash
git clone https://github.com/kayroye/kays-mail-mcp.git
cd kays-mail-mcp
./setup.sh
```

The script asks for your mail account, two HTTPS hostnames, and a new login
email/password. It generates private configuration outside the checkout and
starts the services. Mail passwords are entered through hidden prompts.

For a public Cloudflare Tunnel connection, configure the tunnel routes described
in the [setup guide](docs/quickstart.md), then run:

```bash
./setup.sh --public
```

You still need to supply mail credentials and authorize your domain. Setup does
not change mail delivery records or require an OpenAI/Anthropic API key.

## Connect a client

In a client supporting remote HTTP MCP and OAuth, add:

```text
https://your-mail-hostname.example/mcp
```

Complete the browser login using the email/password you chose during setup.
Allow the client's OAuth callback URL in your private configuration; see
[client setup](docs/quickstart.md#connect-a-client).

For Codex CLI:

```bash
codex mcp add mail --url https://your-mail-hostname.example/mcp
codex mcp login mail
```

For Claude Code:

```bash
claude mcp add --transport http mail https://your-mail-hostname.example/mcp
```

Use Claude Code's `/mcp` menu to authenticate. Hosted clients have their own
connection settings and callback URLs; support depends on their MCP and OAuth
capabilities. This is a private server connection, not an app-store listing.

## Tools

| Tool | Purpose |
|---|---|
| `list_mailboxes` | List allowed folders |
| `search_messages` | Search a folder with bounded results |
| `get_message` | Read a message as plain text and list its attachments |
| `get_attachment` | Retrieve a selected attachment |
| `health_check` | Return service status without accessing mail |

Message retrieval uses mailbox, UID and UIDVALIDITY. Search returns the identity
you need; repeat the search if the mailbox identity changes.

## Security and data

- The tool surface has no sending, deletion, moving or flag-changing operations.
- Mailboxes are selected read-only; body fetches use `BODY.PEEK`.
- IMAP uses certificate-verified TLS and a server-controlled folder allowlist.
- Keycloak handles email/password login; FastMCP handles the OAuth bridge.
- Only the configured immutable owner identity can access mail.
- Mail and OAuth state remain on your server. Messages requested by an agent are
  transmitted to that agent's provider. Cloudflare handles proxied HTTPS traffic.
- Email content is untrusted input. Read-only mail access does not prevent an
  agent from disclosing content through another tool.

See the [security policy](SECURITY.md) and [operations guide](docs/operations.md)
for boundaries, backups, upgrades, revocation and recovery.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install --no-deps --no-build-isolation -e .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest
```

Tests use synthetic mail and identity fixtures. The real IMAP test is opt-in and
requires a disposable mailbox; never put real credentials into tests or issues.

## Attribution

Based on [ares952/MCPGenericIMAP](https://github.com/ares952/MCPGenericIMAP),
used under the MIT License. This repository starts with fresh Git history.
See [UPSTREAM.md](UPSTREAM.md) and [LICENSE](LICENSE).
