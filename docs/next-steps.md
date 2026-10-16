# Next steps

The existing hosted service is working and reachable through the connected MCP.
The priorities below improve its speed and usability, then make that installation
experience repeatable for someone else.

## 1. Roll out bounded reads

Deployed on this machine on 2026-10-16. Container health, hosted search and message
reads passed. Explicit 32- and 128-character truncated reads passed through an
in-process MCP client using the installed server package and live mailbox.

The existing connected client's cached schema still omits `body_limit`; calls
through that connection discard the new argument. Refresh its tool discovery or
reconnect it, then verify an explicit limited read through the hosted connection.
See [reader-only upgrades](operations.md#reader-only-source-updates).

## 2. Measure and improve speed

The first optimization is deployed: one batched UID FETCH replaces per-message
header fetching, with byte limits, identities, ordering and flags preserved.
Three-sample in-container median for a 25-result search fell from 3.66 to 1.12
seconds. Hosted searches after deployment took 2.47–3.21 seconds.
See [measurements and remaining work](performance.md).

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
- Evaluate production connection pooling next. Every tool call currently
  connects, authenticates and logs out; three same-session 25-result searches had
  a 356 ms median after session setup. Introduce bounded reuse as a separate change
  with exclusive ownership, stale-session recovery, mailbox-version checks and
  the existing operation cap. This has not been deployed yet.
- Investigate server-side search cost on large folders, especially UTF-8 searches
  that currently issue extra searches. Use narrower dates and sender/subject
  filters when appropriate; do not silently change matching semantics.

Accept performance changes only after comparing the same workload before and
after, with read-only behavior and response bounds preserved. Body previews reduce
response size but do not reduce the current full-message IMAP download.

## 3. Make setup diagnose the complete connection

Extend diagnostics beyond prerequisites/container readiness. Clearly distinguish
public endpoint reachability, OAuth configuration and a read-only mailbox login.
Give one actionable recovery instruction per failed check. Keep credentials out
of diagnostics. The existing health tool intentionally does not contact IMAP.

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
