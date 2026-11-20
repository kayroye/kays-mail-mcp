# Operations

Use your setup configuration directory:

```bash
config_dir="$HOME/.config/kays-mail-mcp"
docker compose --env-file "$config_dir/compose.env" -f "$config_dir/compose.yaml" ps
```

Use the same `--env-file` and `-f` arguments for other Compose commands. Never
source these files into your shell or publish `compose config` output: it contains
private identifiers. Credential files are outside Git.

## Stop, restart and uninstall

`restart mail` restarts the reader; `stop` stops services. `down` removes containers
and networks, preserving the database volume and private files. Include
`--profile public` when managing the enabled connector. Uninstall preserves data
by default; `down -v` destroys identity state and is not a normal upgrade step.
This project does not mirror your mailbox, but identity/OAuth state is sensitive.

## Health and logs

Run `./setup.sh --doctor` from the checkout. For another installation, add
`--config-dir /absolute/private/path`. This checks service readiness, an anonymous
MCP initialization returning 401, public MCP and login discovery with the expected
issuers, and read-only access to at least one allowed mailbox. Each failed check
prints a recovery instruction. It does not restart services or print mail,
credentials, raw container configuration or provider errors. Client OAuth consent
and actual search/read still require a connected-client check. `--check` remains
a prerequisites-only check.

The reader reuses authenticated IMAP connections for up to 30 idle seconds, with
one caller per connection and at most the configured operation count. A read-only
NOOP probe checks each reused session; stale sessions are replaced before the
operation. Every search/read still reselects its mailbox read-only and retrieval
still checks UIDVALIDITY. Failed operations discard their sessions. Idle timers
close retained connections even when there are no subsequent calls.

Set `IMAP_CONNECTION_IDLE_SECONDS=0` in private `mail.env` to disable reuse, or
choose an idle lifetime from 1 through 300 seconds. Recreate the mail container
after changing environment configuration. Connections are isolated by the full
validated configuration, including credentials.

Container health checks prove process/database readiness, not a successful iCloud
login. Test real mail through an authenticated read-only folder listing. Logs
rotate and HTTP access logging is disabled to keep OAuth codes out of logs. Avoid
debug logs when connected to real mail. The gateway uses conservative global
request budgets for this single-owner service. Unauthenticated traffic can
temporarily rate-limit the owner; these controls do not guarantee DoS resistance.

## Backup and restore

Back up the entire private directory plus a consistent PostgreSQL dump, using
your encrypted backup tool. Stop reader, gateway, connector and Keycloak first,
then use `exec -T db pg_dump -U keycloak keycloak` in your encrypted backup
pipeline. Check its failure status; a failed dump is not a backup. Keep encryption
keys/passwords separately, and test restoration.

Restore into a fresh empty database using `exec -T db psql -U keycloak keycloak`,
restore matching private files with owner-only permissions, and start the same
software version before upgrading. The database holds password hashes and
identity state; private files include live credentials, signing keys and encrypted
OAuth state. Backups need encryption as a whole because the OAuth encryption key
is included. Never attach backups to issues.

## Revocation and rotation

For immediate containment, stop the reader and tunnel. Revoke the Apple
app-specific password if exposed. Store its replacement in the owner-only
`secrets/imap_password` file and restart the reader.

Signed Keycloak access tokens are verified locally until expiry. Disabling an
identity may take up to five minutes to invalidate existing access; stopping the
reader takes effect immediately. Disconnecting in a client UI is not guaranteed
server-side revocation.

To invalidate all MCP grants, stop the reader, rotate its random signing key,
back up and remove its old encrypted OAuth state, then restart. Clients must
re-register/login. Coordinate OIDC client-secret rotation with Keycloak. Change
owner passwords/disable users through local identity administration. Public routes
block administration. The generated bootstrap administrator password is in
`secrets/admin_password`; never put it in command arguments or a URL.

## Connection lifetime

New installations use a 180-day maximum OAuth session and expire after 90 days
without a successful refresh. Refresh activity resets the inactivity timer, never
the absolute maximum. A client's background refreshes count as activity even when
you have not opened ChatGPT. Five-minute access tokens, refresh-token rotation,
PKCE, callback restrictions and owner/audience verification remain enabled.
Longer refresh lifetimes allow a stolen refresh credential to remain useful longer
unless revoked; protect OAuth state and use the revocation procedure above.

For an existing installation (including installations with the old seven-day
maximum and one-day inactivity limits), explicitly apply the new policy:

```bash
./setup.sh --configure-sessions --session-max-days 180 --session-idle-days 90
./setup.sh --doctor
```

Use `--config-dir` for a nondefault installation. Omitted day options use the
180/90 defaults, so provide both when setting a custom policy. Values must be whole
days with `1 <= idle <= maximum <= 365`; zero/unlimited sessions are rejected.
Running setup again or `--upgrade` preserves the current policy. Editing a realm
bootstrap JSON does not update an already imported realm.

This command uses Keycloak's loopback administration port and the existing
`bootstrap-admin` credential file. If Docker suppresses port publication because
all attached networks are internal, it resolves the running Keycloak container
and uses its private identity-network address after verifying the network is
internal. Neither path exposes administration publicly. It disables HTTP proxies and redirects for
administration, captures credentials privately, updates only the realm's SSO and
inherited client session limits, verifies readback and saves the chosen values in
private `settings.json`. It does not restart services or rotate keys. If you have
replaced the bootstrap administrator, manage these limits with your replacement
administrator locally instead. Per-client session overrides, if added manually in
Keycloak, can shorten the realm limits and must be reviewed separately.

Before the first change, original realm limits are retained in owner-only
`session-policy-backup.json` in the private configuration directory. Failed
readback or local persistence triggers an attempt to restore the prior live
limits; if identity administration is unavailable, inspect the limits locally
before retrying. To restore the original generated policy, use
`--configure-sessions --session-max-days 7 --session-idle-days 1`.

**Reconnect existing clients once** to obtain tokens with the longer lifetime.
Already issued refresh tokens retain their encoded expiry; this change cannot
revive expired grants. You may still be asked to authenticate after revocation,
key/state loss, or a client-side credential loss.

The policy follows [OAuth refresh-token guidance (RFC 9700)](https://datatracker.ietf.org/doc/html/rfc9700/#section-4.14)
and [MCP authorization and refresh-token requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization#refresh-tokens).
Neither specifies a universal maximum duration. We use bounded online sessions;
`offline_access` is not needed. See [Keycloak session timeouts](https://www.keycloak.org/docs/latest/server_admin/#_timeouts)
for the maximum and inactivity semantics.

## Upgrade and rollback

### Reader upgrades by release tag

Run the updater from a checkout or archive that includes it. If you installed
`v0.1.0-alpha.1`, keep that extracted directory in place and run the newer
`setup.sh` against the existing private configuration:

```bash
./setup.sh --upgrade-release TAG
./setup.sh --doctor
```

Replace `TAG` with the exact tag you want from
[GitHub Releases](https://github.com/kayroye/kays-mail-mcp/releases).
Add `--config-dir /path/to/existing/config` to both commands
if you installed with a custom path. Check the target's release notes first.
Releases that require a change to Compose, nginx, Keycloak, PostgreSQL, or the
OAuth storage format need the full upgrade procedure below.

The updater verifies the download checksum and prepares the target reader image
before restarting the reader. It uses the release's pinned image when available
and builds from the verified archive otherwise. Mail settings, secrets, OAuth
state, the identity database, and the original deployment directory stay in
place. Expect a short interruption while the reader is replaced. The updater
saves the new image selection only after Docker reports it healthy and the
gateway can reach its OAuth discovery endpoint. Verify an actual search and
message read in your client afterward.

If the replacement fails, the updater restores the previous reader and reloads
nginx. If rollback cannot finish or the updater is forcibly stopped before it
saves the new version, recover the reader from the image still selected in the
existing `compose.env`. Use the same Compose files you normally use, including
any `compose.security.yaml` overlay:

```bash
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/kays-mail-mcp"
compose=(docker compose --env-file "$config_dir/compose.env" -f "$config_dir/compose.yaml")
if [ -f "$config_dir/compose.security.yaml" ]; then
  compose+=(-f "$config_dir/compose.security.yaml")
fi
"${compose[@]}" up -d --no-deps --no-build --pull never --wait mail &&
  "${compose[@]}" exec -T gateway nginx -s reload
```

Keep the original release directory and previous image until you've verified
the upgrade. Avoid running setup or other Compose changes during an upgrade.

### Reader-only source updates

After updating the checkout to the intended version, run:

```bash
./setup.sh --upgrade
./setup.sh --doctor
```

The updater validates private configuration and requires `SOURCE_DIR` to point to
that checkout. It tags the running image as `kays-mail-mcp:reader-rollback`, builds
the reader while the previous container stays available, replaces only the reader
and reloads nginx. If startup or gateway reload fails, it attempts to restore the
previous image, waits for it and reloads nginx again. Failed automatic rollback
reports the retained image and manual recovery location. It does not pull Git
changes, update identity/database services or rewrite private configuration.
Use the release tag procedure above for a reader distributed as a release.

The equivalent manual procedure is retained below for recovery and inspection.

For an installation built from a checkout, a code-only reader update needs no
package reinstall on the host. Update that checkout to the intended version first
and review its release notes. Compose builds from `SOURCE_DIR` in your private
`compose.env`, not necessarily your current shell directory. Confirm it points to
the updated checkout. This procedure assumes no identity/database migrations or
deployment-template changes and no digest-pinned `MAIL_IMAGE` release override.

```bash
config_dir="$HOME/.config/kays-mail-mcp"
# Retain the exact running image, even if its tag has already been rebuilt.
mail_container=$(docker compose --env-file "$config_dir/compose.env" -f "$config_dir/compose.yaml" ps -q mail)
mail_image=$(docker inspect --format '{{.Image}}' "$mail_container")
docker tag "$mail_image" kays-mail-mcp:reader-rollback
docker compose --env-file "$config_dir/compose.env" -f "$config_dir/compose.yaml" build mail
docker compose --env-file "$config_dir/compose.env" -f "$config_dir/compose.yaml" up -d --no-deps --wait mail
docker compose --env-file "$config_dir/compose.env" -f "$config_dir/compose.yaml" exec -T gateway nginx -s reload
```

Run the commands in order and stop if any fails. Only the reader is replaced;
nginx reloads to resolve its current container address. Identity state, login
credentials and mail settings are preserved. Expect a short reader interruption.
A plain `restart mail` does not install a rebuilt image. Refresh the client's
tool discovery if its schemas remain stale, then verify a search and message read.

To roll back this code-only update for the default `kays-mail-mcp:local` image:

```bash
docker tag kays-mail-mcp:reader-rollback kays-mail-mcp:local
docker compose --env-file "$config_dir/compose.env" -f "$config_dir/compose.yaml" up -d --no-deps --wait mail
docker compose --env-file "$config_dir/compose.env" -f "$config_dir/compose.yaml" exec -T gateway nginx -s reload
```

If your deployment uses a different image name, restore its configured tag or
digest instead. Keep rollback images until the update is verified.

### Full release upgrades

Stop and back up first. Retain the previous release source and image digests.
Extract/build the new version, read its migration notes and update `SOURCE_DIR`
and release image references in your private `compose.env`. Rerun setup from the
new source. Preserve the owner and secrets. Compare deployment templates
deliberately if a release changes them.

For rollback, stop the new version and restore the prior source/images and a
matching backup if database migration occurred. Downgrading Keycloak against a
migrated database without a matching backup is unsupported.
