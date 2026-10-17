# kays-mail-mcp

Read-only email access for your agents, hosted on your own server.

Search mail, read messages and retrieve attachments through a standard HTTP MCP
endpoint. Works with IMAP providers, including iCloud Mail and custom domains
hosted by iCloud. Thunderbird is not required.

**Status: early pre-release.** Synthetic tests cover mail handling, setup and a
real Keycloak/OAuth container flow. Real-mailbox and hosted-client connections
still need verification for each installation. No independent security audit has
been performed.

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

## Check and upgrade an installation

```bash
./setup.sh --doctor    # services, public HTTPS/OAuth discovery and read-only IMAP access
./setup.sh --upgrade   # rebuild and replace only the source-built mail reader
```

Update your source checkout to the desired version before upgrading; the command
does not pull Git changes. It retains the running image for rollback, waits for
the replacement to become healthy, and reloads the gateway. Startup/reload failure
triggers automatic rollback. Identity/database changes use the separate full
release procedure. See [operations](docs/operations.md).

## Tools

| Tool | Purpose |
|---|---|
| `list_mailboxes` | List allowed folders |
| `search_messages` | Search a folder with bounded results |
| `get_message` | Preview plain text (4,000 characters by default) and list attachments |
| `get_attachment` | Retrieve a selected attachment |
| `health_check` | Return service status without accessing mail |

Message retrieval uses mailbox, UID and UIDVALIDITY. Search returns the identity
you need; repeat the search if the mailbox identity changes.

### Find mail without reading every message

Start with `search_messages` on `INBOX`. For example, these are tool names and
their JSON arguments (not shell commands):

```text
search_messages({"mailbox":"INBOX","query":"invoice","limit":10})
```

`query` is literal text searched in headers and bodies, not Gmail operators or
raw IMAP syntax. Optional `sender`, `subject`, `after_date`, `before_date` and
`unread_only` filters combine with AND. Dates use `YYYY-MM-DD` and filter the
server's internal mail date: `after_date` includes that day, while `before_date`
excludes it. Omit filters to browse recent mail. Other allowed folder names come
from `list_mailboxes`.

Search returns compact metadata in descending UID order. To continue, pass its
`next_before_uid` as `before_uid`, keeping the mailbox and filters unchanged.
Stop when the cursor is null. A full page can be followed by an empty page.

Read only relevant matches, using their actual `uid` and `uidvalidity` values:

```text
get_message({"mailbox":"INBOX","uid":123,"uidvalidity":456})
```

The identifiers above are examples; copy yours from search. The response contains
at most 4,000 body characters by default. If `body_truncated` is true and more text
is needed, repeat with a larger `body_limit`, for example `16000`. This is a
character limit, not a token budget. Short and empty bodies have
`body_truncated: false`. Truncation applies only to the body; metadata and the
attachment inventory remain available.

Previews reduce agent context usage, but the server still downloads and parses
the full message. Existing raw-message and decoded-body byte limits apply;
oversized messages still fail rather than bypassing those limits. Fetch an
attachment only when needed: `get_attachment` returns potentially large base64
content, using the attachment's `index` and the message's mailbox identity.

See [next steps](docs/next-steps.md) for the usability and performance backlog.

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
.venv/bin/python tests/integration/smoke.py  # disposable Docker identity/TLS test
```

Automated tests use synthetic mail and identity fixtures. Verify real-provider
connectivity with `./setup.sh --doctor` and a search/read through your connected
client; never put real credentials into tests or issues.

## Attribution

Based on [ares952/MCPGenericIMAP](https://github.com/ares952/MCPGenericIMAP),
used under the MIT License. This repository starts with fresh Git history.
See [UPSTREAM.md](UPSTREAM.md) and [LICENSE](LICENSE).
