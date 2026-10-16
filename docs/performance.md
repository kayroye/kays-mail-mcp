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

## Connection reuse

Three 25-result searches using a single already-open IMAP session took 336, 377
and 356 ms. Fresh-session samples included roughly 0.3–0.6 seconds in combined
connection/TLS and login time. This makes bounded connection reuse a plausible
next optimization, though these samples cannot predict end-to-end savings.

Production reuse is now deployed. Sessions have exclusive checkout, a configurable
30-second idle lifetime (0 disables reuse), automatic idle cleanup, a NOOP probe
before reuse and discard on errors. Mailbox reselection and UIDVALIDITY checks
remain per operation. Pool entries are isolated by all settings and credentials;
concurrent calls remain bounded by the existing operation cap.

Six calls through the installed search tool returned 25 results each. The first
took 1,320 ms and opened/authenticated one connection. Five subsequent calls took
589, 642, 618, 601 and 744 ms (median 618 ms). Command counters confirmed one NOOP,
one read-only selection, one search and one batch fetch per warm call, with no new
connection or login. This includes header normalization into tool results.

Three post-reuse calls through the hosted plugin took 3,115, 2,375 and 2,529 ms
(median 2,529 ms). The sample is too small for a precise end-to-end speedup claim;
remote overhead still dominates many calls.

## Connector and network latency

Three public metadata requests per layer measured these medians:

| Layer | Median |
|---|---:|
| Reader loopback | 1 ms |
| Internal gateway | 1 ms |
| Public HTTPS from the service container | 156 ms |
| Connected plugin health, separate samples | 1,636 ms |

Metadata GETs and authenticated health tool calls are different workloads. To
measure real server/authentication time, a temporary nginx log recorded only
method, HTTP status, request duration and upstream duration during three health
calls. It recorded no URLs, headers, tokens, query terms or mail. The original
logging configuration was restored and the temporary timing file removed.

Those three connected calls took 1,489, 1,574 and 1,860 ms. During the calls, nginx
observed nine successful POSTs in three groups of three. Total gateway durations
per group were 352, 354 and 302 ms; individual upstream durations ranged from
16 to 319 ms. The remaining roughly 1.1–1.6 seconds occurred outside the gateway
measurements. This points to client/connector/remote-network overhead and multiple
HTTP exchanges, without distinguishing their individual contributions.

## Deployment verification

Only the mail container was rebuilt/replaced. The gateway was reloaded to refresh
name resolution. Database and identity services were left running; rollback images
were retained locally. Hashes of the installed transport, server and message/search
tool modules matched the checkout after deployment.

Container health and hosted search/message reads passed. After refreshing the
plugin, explicit 32- and 128-character truncated reads passed through the hosted
connection; a 32-character read was repeated successfully after deploying reuse.
`./setup.sh --upgrade` deployed the reuse release successfully, and
`./setup.sh --doctor` passed all five checks afterward.
