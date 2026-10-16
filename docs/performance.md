# Search performance, 2026-10-16

The reader on this machine now uses one UID FETCH for all headers in a result
page. Before this change it fetched each header sequentially. In both cases,
search uses read-only mailbox selection and BODY.PEEK. Per-header limits and the
4 MiB aggregate header budget remain enforced; the transport also checks the
aggregate literal budget before reading each payload.

## Measurements

Three sequential samples per page size ran inside the mail container against the
same live INBOX. Each sample opened a fresh verified TLS connection, logged in,
selected the mailbox, searched, fetched headers and logged out. Timing wrappers
recorded phase durations and counts without recording credentials or mail text.

| Results | Before median | After median | Before maximum | After maximum |
|---|---:|---:|---:|---:|
| 1 | 686 ms | 951 ms | 833 ms | 1,225 ms |
| 10 | 2,771 ms | 857 ms | 2,778 ms | 1,172 ms |
| 25 | 3,659 ms | 1,115 ms | 4,999 ms | 1,423 ms |

For 25 results, the median fell by about 70%. The header-fetch phase median fell
from 2,911 ms to 219 ms, with 25 UID FETCH commands reduced to one. Single-result
searches had no round-trip reduction and were slower in these samples; variable
network/provider latency remains significant.

After deployment, three 25-result calls through the connected hosted MCP took
3,206, 2,468 and 2,792 ms (median 2,792 ms). The earlier pre-change hosted sample
was 7,551 ms. Three post-change health calls took 1,927, 1,771 and 1,550 ms despite
not accessing IMAP. The remaining client/connector/network overhead warrants
measurement independently of the mail provider.

These are small operational samples, not controlled benchmarks or p95 estimates.
Other verification traffic used the same running service during parts of the
measurement window. No claim is made about every provider, folder size or query.

## Connection reuse evaluation

Three 25-result searches using a single already-open IMAP session took 336, 377
and 356 ms. Fresh-session samples included roughly 0.3–0.6 seconds in combined
connection/TLS and login time. This makes bounded connection reuse a plausible
next optimization, though these samples cannot predict end-to-end savings.

Production pooling is a separate change: connections need exclusive ownership,
bounded idle lifetime, stale-session recovery, cleanup on errors, mailbox
reselection and UIDVALIDITY checks. The current deployment still opens and closes
each tool call's session. Batching delivers the main measured improvement without
introducing shared persistent session state.

## Deployment verification

Only the mail container was rebuilt/replaced. The gateway was reloaded to refresh
name resolution. Database and identity services were left running; rollback images
were retained locally. Hashes of the installed transport, server and message/search
tool modules matched the checkout after deployment.

Container health and hosted search/message reads passed. Explicit 32- and
128-character reads passed through an in-process FastMCP client against the
installed package and live mailbox. The connected client's old cached tool schema
omits the new parameter and discards it, so refresh tool discovery before relying
on explicit body limits through that connection.
