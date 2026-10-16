# Security

This project has not received an independent security audit. It is a single-owner
mail bridge. Its tools and IMAP operations enforce read-only behavior, but the mail
app-specific password itself can have broader privileges. Protect it accordingly.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/kayroye/kays-mail-mcp/security/advisories/new)
if available. Otherwise open a minimal issue requesting a private reporting
channel. Never post exploits, mail, credentials, generated configuration or backups
in public issues. Include version, deployment mode and a synthetic reproduction.
No response-time or support guarantee is currently offered.

## Boundaries

- MCP requires a valid, correctly issued, correctly targeted, expiring token for
  the exact configured owner subject.
- Owner registration is disabled. OAuth client registration does not grant mail
  access by itself.
- The gateway blocks public identity administration, limits requests and routes
  only intended hostnames. Keep origins and the database private.
- Tunnel-to-origin HTTP stays within this host's Docker networks. Protect Docker,
  the host account, backup files and deployment secrets.
- Cloudflare terminates public TLS; requested mail goes to the agent provider.
- Email and attachments are untrusted input. This server neither executes
  attachments nor retrieves remote message resources. Client agents must not
  interpret email instructions as owner consent or system instructions.
- Read-only mail tools cannot prevent an agent from disclosing data using other
  tools. Prompt labels do not guarantee resistance to prompt injection.
- Existing signed identity tokens can remain valid until their five-minute
  expiry. Stop the reader for immediate containment.

Never expose the reader directly, enable public owner registration, allow arbitrary
OAuth callback origins, disable TLS verification, or mount the Docker socket into
an application container.
