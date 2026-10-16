Self-hosted, read-only IMAP MCP with guided setup, email/password login through
Keycloak, OAuth through FastMCP, and optional Cloudflare Tunnel.

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

For a source-built deployment with reader-only changes, see the short
[upgrade and rollback procedure](operations.md#reader-only-source-updates).

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

Download the archive and SHA256SUMS, verify the checksum, extract, then run
`./setup.sh`. Linux x86-64, Docker Engine, Compose v2 and Python 3.11+ are required.
Domain/tunnel authorization and mailbox credentials still require your input.

This is a pre-release and has not been independently audited. Fixture/container
checks are automated; real mailbox and hosted-client compatibility must be
verified for your installation. See README.md, SECURITY.md and docs/quickstart.md.
