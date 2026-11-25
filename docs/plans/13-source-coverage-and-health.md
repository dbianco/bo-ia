# 13. Source coverage and health

## Goal

Every publication a source released is either ingested or listed as missing with a reason, missed ones are recovered automatically, and a broken source is reported without anyone reading logs.

## Why

A monitoring product that silently misses a day is worse than none: users read the absence of alerts as "nothing was published".

## Current state

- `boletin-cba-pdf-diario` fetches only today's date, unless a fixed date is set in its configuration. A day on which the backend was down is never fetched.
- Scheduled jobs use an interval trigger with no start time, so the first run happens one full interval after startup. A daily source in a backend restarted every day may never run, and the 30-day tender source needs 30 days of uptime.
- A document that failed to process stays in `estado="error"`. Later runs count it as existing and do not retry it.
- A run in which every item failed is still marked `completada`. Only an error from the connector as a whole marks it `fallida`.
- A day with no publication looks like a failed download.
- `comprar-gob-ar-csv` keeps no position. With `limite_filas` set, it reads the same first rows on every run.
- `ejecuciones_fuente` records each run, but no endpoint returns it and nothing raises an alert.

## Design

**Coverage ledger**

- Each source declares what it expects: publication days and the units per day, such as sections.
- A ledger holds one entry per expected unit with its state: pending, ingested, not published, or failed with a reason and an attempt count.

**Scheduling**

- The schedule is derived from the ledger, which is stored in the database, and not from the uptime of the process. At startup, whatever is due runs.
- Backfill requests pending and failed units within a configured window, oldest first, with a rate limit towards the source.

**Retries**

- Failed units and documents in error are retried with backoff up to a limit, then reported.
- A retried document goes through the single ingestion path and is matched once.

**Cursors**

- A connector may save a position between runs. The CSV connector continues from it and handles a file that has been replaced.

**Health**

- A source is healthy, degraded or broken, from rules over the ledger and the recent runs: overdue publications, repeated failures, or a sharp fall in the number or size of documents.
- An endpoint and a page show health and coverage. A change of state notifies the operator.

## The hard parts

- **Telling "nothing published" from "failed".** Weekends, holidays and extra editions break fixed rules, and a missing file and a blocked request can look alike.
- **Old alerts.** Backfilled notices match subscriptions. Sending them as new would confuse users; dropping them would hide relevant ones.
- **Being a good client.** Backfill after a long outage must not flood the source or get the client blocked.
- **Quiet breakage.** A layout change can leave downloads working while the extracted text is wrong.

## Milestones

1. Run history endpoint, and run states that distinguish success, partial failure and failure.
2. Coverage ledger and expected publication calendar.
3. Persistent scheduling and backfill with a rate limit.
4. Retry of failed units and of documents in error.
5. Connector cursors.
6. Health rules, operator notification and the status page.

## Success criteria

Tested with a simulated source and a controllable clock:

- After an outage of several days, every published unit is ingested without manual action, each exactly once.
- A backend restarted more often than a source's interval still runs that source on schedule.
- Every expected unit within the window is in exactly one ledger state.
- Each injected fault (outage, blocked requests, empty file, layout change that shortens the text) moves the source out of healthy within a stated number of runs, and a normal non-publication day does not.
- With a row limit, repeated runs over the CSV reach every matching row.

## Open decisions

- How far back to backfill, and how backfilled matches are delivered. A marked digest (plan 10) is one option.
- Where the holiday calendar comes from.
- Who the operator is and how they are notified.
- How this builds on the minimal fixes of plan 15 for first runs, retries and run states.
