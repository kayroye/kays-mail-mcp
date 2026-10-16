# Next steps

The existing hosted service is working and reachable through the connected MCP.
The priorities below improve its speed and usability, then make that installation
experience repeatable for someone else.

## 1. Roll out bounded reads

Deployed on this machine on 2026-10-16. Container health, hosted search and message
reads passed. Explicit 32- and 128-character truncated reads passed through an
in-process MCP client using the installed server package and live mailbox.

The plugin was refreshed and explicit 32- and 128-character truncated reads now
pass through the hosted connection. Refresh discovery after future schema changes.
See [reader-only upgrades](operations.md#reader-only-source-updates).

## 2. Measure and improve speed

The first optimization is deployed: one batched UID FETCH replaces per-message
header fetching, with byte limits, identities, ordering and flags preserved.
Three-sample in-container median for a 25-result search fell from 3.66 to 1.12
seconds. Hosted searches after deployment took 2.47–3.21 seconds.
See [measurements and remaining work](performance.md).

Bounded connection reuse is also deployed. Five warm in-container searches had a
618 ms median and command counters confirmed no new TLS connection or login.
After deployment, hosted searches had a 2.53-second median across three samples.
Layered HTTP measurements and temporary duration-only gateway logging put roughly
1.1–1.6 seconds of sampled health-call delay outside gateway measurements. The
temporary log and configuration change were removed after profiling.

Initial observations before batching from the connected MCP on 2026-10-16:

| Call | End-to-end elapsed time |
|---|---:|
| `health_check` | 4.3 seconds |
| `list_mailboxes` | 3.3 seconds |
| Unfiltered INBOX search, limit 1 | 2.5 seconds |
| Unfiltered INBOX search, limit 10 | 4.1 seconds |
| Unfiltered INBOX search, limit 25 | 7.6 seconds |

These are single samples, not benchmarks. Health and folder listing ran
concurrently; search samples ran sequentially. They include client/connector,
network and server time, so they cannot isolate a bottleneck. No email contents
were recorded in this document.

- Extend the three-sample baselines with cold/warm median/tail latency for health,
  folder listing, filtered/unfiltered search and message reads. Use synthetic or
  disposable mail for repeatable tests. Record response sizes too.
- Transport phase timings confirmed sequential header fetching as the main
  server-side cost. Extend profiling to MIME parsing and compare server timings
  with client-observed time to locate remaining transport overhead. Keep mail
  contents, search terms and credentials out of timing output.
- Batching and its regression tests are complete. Check other providers against
  the same bounded UID batch behavior as compatibility testing expands.
- Reuse and its tests are complete. Check idle expiry and stale-session recovery
  during longer operational runs and additional provider compatibility testing.
- Investigate whether the hosted client/connector can reuse its MCP connection or
  reduce repeated HTTP exchanges; this requires capabilities outside this server.
- Investigate server-side search cost on large folders, especially UTF-8 searches
  that currently issue extra searches. Use narrower dates and sender/subject
  filters when appropriate; do not silently change matching semantics.

Accept performance changes only after comparing the same workload before and
after, with read-only behavior and response bounds preserved. Body previews reduce
response size but do not reduce the current full-message IMAP download.

## 3. Make setup diagnose the complete connection

Complete: `./setup.sh --doctor` checks service health, anonymous MCP initialization
requiring authentication, MCP/login discovery and read-only mailbox access. Each
failure includes a recovery instruction, without printing private output. All five
checks passed on this installation. Client consent and real tool use remain a
separate verification step. The MCP health tool still does not contact IMAP.

Reader-only source upgrades are now `./setup.sh --upgrade`, with a retained image,
automatic rollback after startup/reload failure, and gateway reload. The first live
upgrade using this command succeeded. Full identity/database release upgrades
still follow the separate backup/migration procedure.

## 4. Simplify onboarding

Put server requirements and the need for two HTTPS hostnames before installation.
Provide one recommended tunnel path, with alternatives separate. Explain callback
configuration in terms of the selected client. Finish setup with the MCP URL,
connection steps and a first-search example. Clearly distinguish services started
from a verified client connection.

## 5. Verify fresh installs and upgrades

Test a clean supported Linux server through setup, public routing, browser login,
listing, search, pagination, reads and attachments. Record providers and clients
actually verified. Exercise rerunning setup and restoring/upgrading an existing
installation. The current working deployment is valuable evidence but does not
replace a reproducible fresh-install check.

## 6. Improve attachment and large-message handling

Test client support before choosing alternatives to inline base64 attachments.
Evaluate bounded text extraction for supported document types. Separately design
safe previews for bodies exceeding the current parser limit; the new output
preview does not solve that case. Keep transfer limits distinct from agent output
budgets.
