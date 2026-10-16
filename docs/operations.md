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

## Upgrade and rollback

Stop and back up first. Retain the previous release source and image digests.
Extract/build the new version, read its migration notes and update `SOURCE_DIR`
and release image references in your private `compose.env`. Rerun setup from the
new source. Preserve the owner and secrets. Compare deployment templates
deliberately if a release changes them.

For rollback, stop the new version and restore the prior source/images and a
matching backup if database migration occurred. Downgrading Keycloak against a
migrated database without a matching backup is unsupported.
