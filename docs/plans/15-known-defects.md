# 15. Fix known defects

## Goal

The problems found while reviewing the code are fixed: only authorized callers can add documents or run a source, scheduled sources run on time, declared filters find the documents they should, and failures and changed records are no longer ignored.

## Why

These are faults in features the product already offers, not missing features. Most of them are silent: nothing fails visibly, and users or the operator simply do not get what they expect. Several other plans add larger capabilities around the same code. The fixes here are small and should not wait for them.

## Current state

Found by reading the code. The scheduler default was also checked in the source of APScheduler 3. None has been reproduced on a running system.

| Defect | Effect | Where |
|---|---|---|
| A. `POST /v1/documentos` and `POST /v1/fuentes/{clave}/ejecutar` require no authentication. | Anyone who can reach the backend can add documents, which are matched and can send email to subscribers, or make it fetch from a source. | `backend/src/api/ingest.py`, `backend/src/api/fuentes.py` |
| B. Jobs use `IntervalTrigger` with no start time, so the first run is one full interval after startup. | A daily source on a backend restarted every day may never run. The 30-day tender source needs 30 days of uptime. | `backend/src/scheduler/__init__.py` |
| C. The Córdoba gazette connector writes `jurisdiccion` and `seccion`, while the installation filters on `provincia` and `municipio`. | Filtering a search or a subscription by either excludes every document it collects. | `backend/src/connectors/boletin_cba/connector.py`, `config/installation.yaml` |
| D. A document in `estado="error"` counts as already ingested. | It is never retried, so it is never searchable or matched. | `backend/src/ingestor/contract.py` |
| E. A run in which every item failed is marked `completada`. | A broken source looks healthy in the run history. | `backend/src/connectors/runner.py` |
| F. The tender connector does not keep the CSV's opening date (`Fecha_de_Apertura`). | The date a user most needs is lost. | `backend/src/connectors/comprar_gob_ar/connector.py` |
| G. A record that arrives again with the same identifier and different content is ignored. | Changes to a tender never reach the system, and nothing says so. | `backend/src/ingestor/contract.py` |

## Design

Each fix is the smallest one that removes the defect. The larger capability stays in its own plan.

**A. Authentication for write endpoints**

- Both endpoints require a secret token sent in a header, set by an environment variable and compared in constant time.
- With no token configured, both endpoints reject every request. The scheduler and the seed call the code directly and are not affected.
- The token is never logged. The compose file, the example environment files and the README show how to set it.
- The operator role of plan 14 can later be accepted in addition to the token.

**B. First run of scheduled sources**

- At startup, a source whose last successful run is older than its interval, or that has none, runs soon after. Others are scheduled for when they become due.
- The due time comes from `ejecuciones_fuente`, so restarts do not reset it.
- Startup does not wait for these runs.
- Fetching days that were missed is plan 13.

**C. Declared filters**

- A source can set fixed metadata in its configuration, such as `provincia`, which is added to every document it produces. The value matches the one the sample data already uses.
- A migration adds the value to documents already collected.
- `municipio` cannot be filled from a whole section, and the tender installation's `organismo` and `monto` cannot be filled from gazette text. Those need plans 7 and 8, and the README says so until then.

**D. Retry of failed documents**

- Ingesting a document that exists in `estado="error"` processes it again from the stored row, through the single ingestion path, and matches it once on success.
- Retries with backoff and limits are plan 13.

**E. Run states**

- A new state records partial failure. A run with items discovered and none ingested or already present is `fallida`.
- A migration updates the check constraint.

**F. Opening date**

- The connector keeps the opening date in the document metadata. Rows with an empty or unreadable date are still ingested.
- Since stored records are skipped, existing documents get the new field when their row is read again with unchanged text.
- Events, reminders and the calendar are plan 11.

**G. Changed records**

- Ingestion compares the incoming text and metadata with the stored ones. A difference is counted as changed in the run and logged with the identifier.
- The stored document is not overwritten, apart from adding metadata keys it did not have.
- Keeping versions, showing the differences and alerting followers is plan 11.

## The hard parts

- **Retrying safely.** A retry must not duplicate fragments or send an alert twice.
- **A burst at startup.** Many overdue sources must not all run at once and slow the service while it starts.
- **Breaking callers.** Requiring a token breaks any script that posts documents today. The tests and the README call both endpoints without one.
- **False changes.** Differences in key order or number format must not be reported as a change.

## Milestones

1. A failing test that reproduces each defect.
2. Token for the two write endpoints (A).
3. First-run scheduling (B).
4. Fixed source metadata and the backfill migration (C).
5. Retry of failed documents and the run states (D, E).
6. Opening date and detection of changed records (F, G).
7. README and example configuration updated.

A is first because it is the only defect that lets an outsider act on the system.

## Success criteria

- Each defect has a test that fails before its fix and passes after it.
- A request to either write endpoint with a missing or wrong token is rejected and changes nothing, including when no token is configured. The right token works as before.
- With a controllable clock, a backend restarted more often than a source's interval still runs that source when it is due, and does not run it before.
- A search and a subscription filtered by `provincia` match new and previously stored gazette documents.
- A document that failed once and is ingested again ends complete, with one set of fragments and at most one match per subscription.
- A run in which every item fails is `fallida`; a run with some failures is not `completada`.
- A tender row with an opening date stores it. The same row with a changed date is counted as changed, and the same row reformatted is not.

## Status

Implemented. Not marked as done yet: the test of the real model (`pytest -m slow`) and `pytest -m docker` have not been run, because the machine had neither the model nor Docker.

Each defect was reproduced first: its tests failed on the code before the fix.

| Criterion | Result | Test |
|---|---|---|
| Each defect has a test that fails before and passes after | Met | the files below |
| A. A missing or wrong token, or none configured, is rejected and changes nothing | Met | `tests/api/test_write_token.py` |
| B. A source runs when it is due, and not before, with a clock under control | Met, for restarts every 1 to 23 hours and intervals of 3 hours to 30 days | `tests/scheduler/test_first_run.py` |
| C. `provincia` finds new and stored documents, in searches and subscriptions | Met | `tests/config/test_metadata_backfill.py`, `tests/api/test_notices.py` |
| D. A document that failed once ends complete, with one set of fragments and one match | Met, also with two retries at the same time | `tests/ingestor/test_retry.py` |
| E. All items failed: `fallida`. Some: not `completada` | Met | `tests/connectors/test_run_states.py` |
| F, G. The opening date is stored; a changed one is counted and a reformatted row is not | Met | `tests/connectors/test_opening_date.py`, `tests/ingestor/test_changed_records.py` |

## Decisions

- **Token.** One for both endpoints, `OPERATOR_TOKEN`, as `Authorization: Bearer`. It is checked before the source and the body are looked at. With no token configured both are closed, and startup says so.
- **Other endpoints open to anonymous callers**, reviewed and left as they are, because they are part of the product: `POST /v1/valoraciones` (the web page rates results without an account; nothing reads the ratings yet, but anybody can fill the table), `POST /v1/auth/registro` (anybody can create an account, and so a subscription that sends email to the address they gave, which is not verified) and the search (each call costs an embedding). They have a limit by address since plan 10 (`src/api/rate_limit.py`), set by environment variables. A test lists every route that writes and who may call it, so that a new one is a decision.
- **Runs.** The new state is `partial`, and the new count is `changed`, a part of the existing ones. A partial run counts as done for the schedule; the failed items are retried when they arrive again. A run that discovers nothing is `completada`.
- **First runs.** Overdue sources start 5 seconds after startup, the longest overdue first and 30 seconds apart, and two runs at once at most. A job that has to wait starts late: the library's default was to skip it.
- **Stored documents and fixed metadata.** Added at startup from the configuration, and not by a migration, which does not know the values of each installation.
- **Retries** process the stored text and date. The pages of the fragments are known only if the text that arrives is the same.
- **What is a change.** The text, and the metadata keys that were stored. A key that is missing now is a change; a new key is not, and is added. Spacing, key order and the way a number is written do not count.
- **Releasing A on its own.** Possible: it is `src/auth/operator.py`, two decorators and the configuration. It was done first.

## Found meanwhile

- A document whose process is killed while it is being embedded stays `pendiente`, and is not retried: it cannot be told from one in progress. For plan 13.
- A run interrupted in the same way stays `en_curso`. It does not count as done, so the source runs again after the restart.
