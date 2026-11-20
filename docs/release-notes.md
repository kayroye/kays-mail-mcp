Self-hosted, read-only IMAP MCP with guided setup, email/password login through
Keycloak, OAuth through FastMCP, and optional Cloudflare Tunnel.

### Upgrade from v0.1.0-alpha.1

Download `kays-mail-mcp.tar.gz` and `SHA256SUMS` from this release into a new
directory. Leave the extracted alpha.1 directory in place. In the directory
with both new downloads, run:

```bash
sha256sum -c SHA256SUMS &&
  tar -xzf kays-mail-mcp.tar.gz &&
  cd kays-mail-mcp &&
  ./setup.sh --upgrade-release v0.1.0-alpha.2 &&
  ./setup.sh --doctor
```

If you used a custom configuration directory, pass `--config-dir` to both
`setup.sh` commands. The updater replaces the reader, preserves your settings
and existing login, and restores the previous reader if startup or the gateway
check fails. Test a search in your connected client after the upgrade.

For a fresh install, run `./setup.sh` after extracting. Linux x86-64,
Docker Engine, the Compose plugin and Python 3.11+ are required.

### What changed

Message retrieval now defaults to a 4,000-character body preview and returns
`body_truncated`. Clients that previously assumed `body` was complete must check
this flag and request a larger positive `body_limit` when needed. Existing server
byte limits still apply. Search and retrieval descriptions now explain filters,
pagination, identities and selective reading. Rebuild/redeploy the reader to use
these changes; clients may need to refresh their discovered tool schemas.

Search now fetches result headers in one UID batch instead of one network request
per message. Results retain newest-UID ordering, mailbox versions and unread flags.
Per-header and aggregate literal limits remain enforced, including before reading
oversized wire payloads. If a selected message disappears during retrieval, repeat
the search rather than treating an incomplete page as the end of the mailbox.

The reader now retains exclusively checked-out IMAP sessions for 30 idle seconds
by default, probes them with NOOP before reuse, discards failed sessions and closes
idle sessions automatically. `IMAP_CONNECTION_IDLE_SECONDS=0` disables reuse;
values through 300 seconds are supported. Mailbox selection and UIDVALIDITY checks
remain per operation.

`./setup.sh --upgrade` now performs source-built reader-only upgrades with a
retained rollback image and automatic recovery after startup/reload failure.
`./setup.sh --doctor` checks service readiness, public MCP authentication, MCP/login
discovery and read-only mailbox access, reporting actionable failures without
printing credentials or mail. Neither command changes identity/database state.

Fresh installs default to a 180-day maximum OAuth session and a 90-day
inactivity limit. Reader upgrades keep existing session limits. Owners can
apply the new limits separately with `./setup.sh --configure-sessions`.

This is a pre-release and has not been independently audited. Fixture/container
checks are automated; real mailbox and hosted-client compatibility must be
verified for your installation. See README.md, SECURITY.md and docs/quickstart.md.
