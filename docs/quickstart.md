# Setup

Use a Linux x86-64 server with Docker Engine, Compose v2, Bash and Python 3.11+.
Allow about 2 GiB RAM and several GiB of disk for images and identity state.
Other architectures are not advertised as supported yet. Docker access grants
administrative capabilities; use a non-root server account you trust. Setup
refuses root so application containers do not accidentally run as root.

Choose two HTTPS hostnames, one for MCP and one for login. Existing mail delivery,
MX records and Thunderbird configuration do not need changes. For iCloud, use
your underlying Apple-assigned mailbox address and a dedicated Apple app-specific
password, not your primary Apple Account password.

## Install

Clone this repository or extract a verified release archive, then run:

```bash
./setup.sh
```

The script asks for hostnames, mailbox settings, allowed folders, login email and
a separate login password of at least 12 characters. Password prompts are hidden.
Private configuration defaults to `~/.config/kays-mail-mcp`. Select another
location with `--config-dir /absolute/private/path`.

```bash
./setup.sh --check       # prerequisites only; no changes
./setup.sh --no-start    # prepare settings without starting containers
```

Reruns preserve identities, secrets and state. A failed, incomplete configuration
is not silently overwritten. Inspect it locally; never paste it into an issue.
The initial realm import contains your new login password until Keycloak imports
and hashes it. Setup then removes that file. The database retains the password hash.

Services are the mail reader, Keycloak, PostgreSQL and an HTTP gateway. Identity
administration is available only through a loopback-bound port, default 8870.
No MCP/database port is published. Before configuring public connectivity, MCP is
reachable only inside its Docker network.

## Public HTTPS with Cloudflare Tunnel

1. Create a remotely managed tunnel in Cloudflare for your domain.
2. Add published application routes for both hostnames. Set both service URLs to
   `http://gateway:8080`. The connector and gateway share a Docker network.
3. Configure the two DNS names to use the tunnel. Preserve existing mail records.
4. Run `./setup.sh --public` and enter the tunnel token in its hidden prompt.
   Paste only the token, not the dashboard's entire Docker command.
5. Check that the MCP URL returns HTTP 401 anonymously, and that the login host's
   `/admin/` and `/realms/master/` paths return 404.

The connector dials out; router forwarding is unnecessary. FastMCP and Keycloak
handle OAuth. Do not add a separate Cloudflare Access browser-login wall in front
of MCP unless you deliberately integrate the two authentication layers.

The generated `tunnel.yml` is a route reference, not an uploaded remote tunnel
configuration. Other operators do not need the `cf` CLI or a Cloudflare API token.
If you use another reverse proxy, attach it to the installation's private ingress
network and forward the two hostnames to `gateway:8080`, with public TLS. Always
route through the gateway. A TLS-terminating proxy can read proxied traffic.

## Connect a client

Add `https://your-mail-host/mcp` as a remote HTTP MCP server and authenticate in
the browser with your setup email/password. Do not use your iCloud password here.

Default callback rules permit local Codex loopback callbacks and ChatGPT web’s
stable callback, `https://chatgpt.com/connector_platform_oauth_redirect`. Other
callbacks need their documented exact URL added to `MCP_ALLOWED_REDIRECT_URIS` in your
private `mail.env`, separated by commas. Restart the reader after changes. Do not
allow arbitrary callback origins or take callback URLs from untrusted pages.

For ChatGPT web, create a remote MCP connection in its connection settings, choose
OAuth, and enter your MCP URL. Use dynamic client registration (DCR) if asked.
Copy the exact redirect URI shown by ChatGPT; if it differs from the default, add
that exact URI to your allowlist before authenticating. See OpenAI’s
[authentication documentation](https://developers.openai.com/plugins/build/auth#redirect-url)
for callback behavior. Hosted client availability depends on your plan/workspace.

Codex CLI:

```bash
codex mcp add mail --url https://your-mail-host/mcp
codex mcp login mail
```

Claude Code:

```bash
claude mcp add --transport http mail https://your-mail-host/mcp
```

Authenticate through `/mcp`. Hosted clients have their own connection settings,
availability and callback URLs. No OpenAI or Anthropic API key is required.

## Release archives

Verify release SHA-256 checksums before extracting. Keep each extracted version's
source directory: Compose uses it for the identity entrypoint and source-build
fallback. Releases with `release-images.json` use digest-pinned prebuilt images whose public
download was checked during release. Without that manifest, setup builds locally
from the included source.
See [operations](operations.md) before upgrading or deleting files.
