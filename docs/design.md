# kays-mail-mcp design

## Goal

Give compatible desktop and web-hosted agents read-only access to an IMAP mailbox through a self-hosted MCP endpoint. Reuse MCPGenericIMAP under MIT, starting with fresh Git history. Support iCloud with an app-specific password and keep the provider configurable. Provide one setup entry point for Linux Docker hosts.

## Architecture

Use the existing Python mail tools, with a maintained FastMCP OIDCProxy authentication layer, Keycloak for email/password login, a dedicated PostgreSQL identity database, and optional Cloudflare Tunnel for public HTTPS. Do not implement password hashing or an OAuth authorization server ourselves. Disable public registration and authorize one configured immutable Keycloak subject. Use explicit consent, PKCE, bounded token lifetimes and persistent encrypted OAuth state.

Cloudflare Access Managed OAuth is a possible future alternative. It is not required for the initial release; the initial authentication path stays independent of Cloudflare account features and uses the already selected Keycloak architecture.

The MCP service and identity database expose no public host ports. The tunnel reaches only intended MCP/OAuth and realm login routes over private Docker networking. Keep Keycloak administration local. iCloud traffic uses certificate-verified TLS. Do not add sending, flagging, deletion, moves or arbitrary IMAP commands.

## Safety and compatibility

Retain exact mailbox allowlists, read-only selection and BODY.PEEK fetches. Limit raw messages to 25 MiB by default, with a 50 MiB configuration ceiling; enforce declared size before download and bound fetched bytes. Add a two-operation IMAP concurrency limit, a 20-second default timeout, Unicode search and UIDVALIDITY in message identities. Reject stale identities instead of returning a different message.

Keep existing body/attachment/result caps. Treat all message content as untrusted data; never fetch remote message resources or execute attachments. Read-only mail access does not prevent an agent from disclosing content through another tool. Retrieved mail is sent to the client's model provider.

## Setup and releases

Provide a release archive and prebuilt GHCR image. After extracting the archive, the operator runs `./setup.sh`. Linux, Bash, Python 3.11+, Docker and Compose v2 are prerequisites; detect missing tools and provide actionable instructions. The script prompts for mailbox settings, domain, login email and credentials, generates independent secrets and renders configuration. Hidden password input must not echo secrets. Store configuration under an operator-selected directory outside the checkout, defaulting to the user's XDG config location. Use restrictive directory/file permissions and Docker-compatible secret ownership. Make reruns preserve existing credentials and persistent data.

Cloudflare installation accepts a tunnel token through hidden input/file setup; do not require the cf CLI for other users. Explain how to obtain a token and configure the two public hostnames. The setup command prepares private services before asking the operator to enable publication. Never claim domain/credential onboarding can happen without operator input.

Use persistent state, restricted containers, rotated logs, pinned dependencies and release images. Provide upgrade/rollback/uninstall and encrypted backup/restore instructions; preserve data on uninstall unless explicitly requested. Keep real domains, personal mail addresses, account IDs and credentials out of the public configuration.

## Verification

Run fixture-based mail tests, auth denial/PKCE/callback/owner-identity tests, installer rerun and secret-redaction checks, and container health/restart tests before release. Validate Codex and one web-hosted client against a deployed endpoint before claiming support. Never claim an independent audit. Keep the README clear about incomplete features until checks pass.
