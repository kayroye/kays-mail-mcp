Self-hosted, read-only IMAP MCP with guided setup, email/password login through
Keycloak, OAuth through FastMCP, and optional Cloudflare Tunnel.

Download the archive and SHA256SUMS, verify the checksum, extract, then run
`./setup.sh`. Linux x86-64, Docker Engine, Compose v2 and Python 3.11+ are required.
Domain/tunnel authorization and mailbox credentials still require your input.

This is a pre-release and has not been independently audited. Fixture/container
checks are automated; real mailbox and hosted-client compatibility must be
verified for your installation. See README.md, SECURITY.md and docs/quickstart.md.
