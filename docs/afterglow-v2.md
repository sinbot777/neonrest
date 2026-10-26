# Afterglow V2 on existing hosting

Candidate for a small Sandbox pilot. Production messaging remains disabled. No hosting upgrade, public WebSocket service, protocol migration, unread projection table, permission cache, or database migration is introduced.

## Behavior

One per-page background scheduler serializes conversation updates, read receipts, presence and buddy-overview requests. Active conversation polling starts at three seconds, backs off to six seconds after thirty seconds without local activity or incoming messages, and fifteen seconds after two idle minutes. Hidden pages stop background work; visibility and back-forward restoration resume it. Separate visible windows still have separate schedulers; this version does not claim cross-tab deduplication.

Read receipts coalesce for one second, retain the earliest deadline during continuous scrolling, and retry while the page remains open. Sending retains the existing nonce-based duplicate protection and immediate foreground action. A background network request times out after twenty seconds; server failures and rate limits delay background work, including receipts. Retry-After is honored up to two minutes. Presence and buddy-overview refresh at roughly one-minute intervals while visible. Background work already in flight may finish after hiding; no new periodic work starts while hidden.

The updates endpoint accepts optional `badge=0`, returning `unread: null` instead of recomputing the account-wide unread count. All conversation, session, safety, moderation and rate-limit checks still run. Existing clients keep the original numeric unread response by default. The V2 client ignores a null count; overview and successful read responses refresh the numeric badge. Other-conversation badges may therefore lag by up to approximately one minute while healthy and visible, longer during backoff or suspension.

The profile query uses CASE to select author/target candidates before invoking the expensive visibility function. Moderation, visibility, ordering and pagination conditions remain in place.

## Validation and limits

The original messaging suite passed 141 checks on a disposable database copy; candidate-specific checks passed, including default API compatibility, identical message payloads, unauthorized/anonymous access, blocking, fifteen profile output comparisons and database integrity. Deterministic scheduler checks execute the actual browser script with mocked clock/DOM/network. Native Edge component checks render synthetic messages and exercise failed-send retry and duplicate bubbles with all messaging fetches intercepted in the test page.

In a fixture with thirteen unread conversations, three measured update requests used 120 traced SQL statements by default versus 34 with badge omitted. Profile SQL fell from 69,622 to 106 statements for the previously diagnosed empty-profile case; this is not a universal site-wide reduction.

Private two-worker-slot simulations: thirty-second cases with ten and twenty participants delivered all 15 test messages with zero request failures. A two-minute ten-participant run, including repeated sends and minute presence/overview, delivered 50/50 messages; page p95 was 452 ms and delivery p95 3.08 seconds. This is an in-process Flask/SQLite workload on a console host, not PythonAnywhere public-ingress capacity, an hour-long soak, or proof for forty or one thousand users. A cautious initial pilot of up to ten simultaneous participants is an operational recommendation, not an enforced hard concurrency cap. Multiple active windows, larger inboxes and public traffic need observation.

## Rollback

`afterglow-v1-preserved-20261025` points to `1c98d8f5a37c96fb1ff1ac7fa7d7d781eb76679e`; all four changed runtime files were compared byte-for-byte with actual deployed V1 before development. A separate private source archive and consistent SQLite snapshots were verified on the hosting account. A private four-file rollback rehearsal restored V1 hashes and then reapplied V2. Roll back these source files and reload the web app; do not restore an older database over newer messages. V1 and V2 have compatible schemas and update responses. Preserve current local changes before any rollback and refuse hash mismatches.

## Reproduce

Run `node tests/verify_afterglow_scheduler.cjs` from the repository. It writes a local scheduler-results.json report. The Python fixture check uses the existing PythonAnywhere disposable-database harness: `python3 -B tests/verify_afterglow_v2.py neonrest_sandbox /private/staged/neonrest_sandbox /private/results.json`. Never point the fixture configuration at a writable live database. Keep database copies, account configuration, credentials, message contents and operational backups outside GitHub.
