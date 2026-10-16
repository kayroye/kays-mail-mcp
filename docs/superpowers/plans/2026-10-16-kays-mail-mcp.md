# kays-mail-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Ship a reusable, read-only IMAP MCP service with email/password sign-in and one setup command.

**Architecture:** Reuse the imported MCPGenericIMAP mail tools. Use maintained FastMCP OIDCProxy with Keycloak, PostgreSQL and an optional Cloudflare Tunnel container. Publish code with fresh history and retain MIT attribution.

**Tech Stack:** Python, FastMCP, Keycloak, PostgreSQL, Docker Compose, Bash, GitHub Actions/GHCR.

**Spec:** [Design](../../design.md)

## Global Constraints

- Read-only IMAP; verified TLS; exact mailbox allowlists; BODY.PEEK reads.
- Raw messages: 25 MiB default, 50 MiB ceiling; two concurrent IMAP operations; 20-second default timeout.
- Linux, Bash, Python 3.11+, Docker and Compose v2 for setup.
- No custom password/OAuth implementation; owner authorization uses an immutable Keycloak subject.
- No personal configuration, credentials or generated state in the public repository.
- Preserve MIT attribution; use fresh Git history.

## Review Focus

- Oversized or falsely declared messages must not exhaust download memory (Task 1).
- Mailbox UIDVALIDITY changes must not return a different message (Task 1).
- Valid tokens for a non-owner must not grant mailbox access (Task 2).
- Installer reruns and failures must preserve working credentials and state (Task 4).
- A public hostname must not bypass auth or expose identity administration (Task 3).

## File structure

Keep mail behavior under `src/imap_mcp/` and tests under `tests/`. Add `src/imap_mcp/auth.py` for maintained-library auth configuration. Add `scripts/setup.py`, root `setup.sh`, `deploy/compose.yaml`, deployment templates and `docs/operations.md`. CI/release workflows live under `.github/workflows/`.

### Task 1: Verify and harden the existing mail core

**Files:** modify `src/imap_mcp/config.py`, `imap_client.py`, mail tool modules and their existing tests; add `tests/test_message_identity.py`.

**Interfaces:** retain existing tools while adding mandatory UIDVALIDITY to message/attachment retrieval. Add `fetch_rfc822(mailbox: str, uid: int, uidvalidity: int) -> bytes`; search results carry `uidvalidity`. Extend `SafetyLimits` with `max_message_bytes` and `max_concurrent_operations`.

- [ ] Run the unchanged upstream checks in a disposable Python environment/container and record the baseline.
- [ ] Add tests asserting declared oversize prevents body fetch, falsified size cannot cause an unbounded fetch, stale UIDVALIDITY rejects retrieval, and Unicode search cannot inject IMAP commands.
- [ ] Run the targeted tests and confirm the expected failures.
- [ ] Implement bounded fetches, UIDVALIDITY checking, Unicode IMAP literal/charset handling and a shared bounded operation semaphore. Preserve read-only selection and PEEK.
- [ ] Run `ruff check .`, `mypy` and `pytest`; commit only after they pass.

### Task 2: Add maintained authentication and owner authorization

**Files:** create `src/imap_mcp/auth.py`, `tests/test_auth.py`; modify `server.py`, `config.py`, `pyproject.toml`; generate a reproducible dependency lock.

**Interfaces:** `create_auth(settings: AuthSettings) -> OIDCProxy`; `AuthSettings` contains public URL, discovery URL, OIDC client ID/secret, owner subject and signing-key file. Register the existing tool factories on FastMCP. Public mode requires complete auth configuration and fails closed.

- [ ] Pin a compatible maintained FastMCP release after inspecting its exact APIs and dependency advisories.
- [ ] Add tests for missing settings, wrong issuer/audience, expired tokens, non-owner subject, consent/PKCE failures, callback rejection and secret-redacted errors. Assert owner access reaches the mail adapter and denied access never does.
- [ ] Run those tests to verify failures before implementation.
- [ ] Configure OIDCProxy with explicit signing material and encrypted persisted state; use its documented authorization hooks to enforce the owner subject on every tool.
- [ ] Verify discovery/refresh/restart/revocation behavior with a disposable identity fixture; run all checks and commit.

### Task 3: Package private services and public routing

**Files:** create `deploy/compose.yaml`, `deploy/keycloak-realm.json.template`, `deploy/tunnel.yml.template`, `tests/deployment/`; update `Dockerfile`.

**Interfaces:** deployment reads private files from `CONFIG_DIR`; exports only loopback bootstrap/admin access. Public addresses are operator-supplied `MCP_PUBLIC_URL` and `LOGIN_PUBLIC_URL`. Cloudflare uses token-file input, never a token in command arguments.

- [ ] Add deployment checks asserting no public origin/database/admin ports, required authentication settings, no Docker socket, restricted capabilities, resource/log limits and explicit unmatched-route denial.
- [ ] Verify the checks fail against the upstream deployment.
- [ ] Pin verified image versions/digests; configure production Keycloak/PostgreSQL, owner-only realm, exact callback URL, encrypted auth state and an opt-in tunnel profile. Exclude admin and management routes from public routing.
- [ ] Verify startup, private health, owner/non-owner behavior, auth failures and restart persistence on disposable credentials. Ensure an unconfigured tunnel cannot expose mail.
- [ ] Run deployment and existing checks; commit.

### Task 4: Provide one safe setup entry point

**Files:** create `setup.sh`, `scripts/setup.py`, `tests/test_setup.py`, `docs/quickstart.md`.

**Interfaces:** `setup.sh` executes Python setup; `main(argv: list[str] | None = None) -> int` supports `--config-dir`, `--check` and `--no-start`. Use Python `getpass` for secrets and subprocess argument arrays without a shell. Persistent configuration is outside the checkout.

- [ ] Add tests for missing prerequisites, synthetic iCloud settings, malicious newline input, hidden secret input, restrictive file permissions, failed bootstrap and a second run preserving existing secrets/state.
- [ ] Confirm the tests fail before implementing the script.
- [ ] Implement validated prompts, prerequisite detection, independent secret generation, atomic configuration writes and Docker-compatible secret ownership. Configure the local owner identity and discover/persist its immutable subject without printing passwords.
- [ ] Require explicit publication configuration; show exact tunnel dashboard steps. Do not require a Cloudflare API token or cf CLI. Avoid duplicate DNS/tunnel creation on rerun.
- [ ] Test installation and rerun from an extracted release in a clean disposable environment; run checks and commit.

### Task 5: Release artifacts and operator documentation

**Files:** create `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `SECURITY.md`, `docs/operations.md`; update README and upstream attribution as needed.

**Interfaces:** a version tag produces a source/setup archive with SHA-256 checksums and a pinned GHCR image; the release deployment references that image's digest. Release automation uses minimal GitHub permissions and no personal secrets.

- [ ] Add artifact validation checking installer/templates are present, image references are pinned, attribution is preserved and synthetic install configuration works.
- [ ] Add CI for lint/types/tests and container builds. Release images for verified architectures only; verify each before advertising support.
- [ ] Document setup prerequisites, iCloud app passwords, domain setup, auth/client setup, untrusted email, backups, restore, revocation delay, rotation, upgrade, rollback and data-preserving uninstall.
- [ ] Test the release artifact on a clean environment. Verify Codex and one hosted MCP client end to end with consent, read-only reads and token refresh before marking the release ready.
- [ ] Run final checks, review the diff for secrets and accurate security claims, commit and publish a release only after its checks pass.

## Execution

Recommended: native execution in this session, one task at a time. Reusing a small existing core keeps task interfaces closely related and avoids repeated agent context costs. The plan requires user review before implementation starts. Initial repository publication is separately authorized and contains the imported foundation and planning documents, not a finished release.
