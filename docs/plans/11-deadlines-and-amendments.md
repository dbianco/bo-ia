# 11. Deadlines and amendments

## Goal

A tender's key dates are stored as dates, followers are reminded before they arrive, and a later notice or a changed record that amends, postpones or cancels the tender is linked to it and announced.

## Why

- A tender is useful only until it closes. Knowing it was published is not enough.
- Amendments change dates and conditions after the first alert. A user who misses one acts on old information.
- Tender monitoring tools advertise tracking of deadlines and amendments.

## Current state

- The national tender CSV has the columns `Fecha_de_Apertura` (opening date), `Etapa`, `Tipo_de_Procedimiento` and `Modalidad`. `comprar-gob-ar-csv` keeps none of them.
- Ingestion skips any record whose `(source, external identifier)` already exists, even if its content has changed, so an updated row never reaches the system.
- Gazette notices state dates only inside their text.
- Documents are not related to each other, and there is no notion of a tender as something that lasts over time.

## Design

**Events**

- A structured event: kind (opening, submission deadline, question deadline, award), date and time, time zone, and the text or column it came from.
- Structured sources fill events from their columns. For gazette text, rule-based extractors read them, using the interface from plan 8.

**Versions**

- A record that arrives again with different content becomes a new version of the same document. Earlier versions are kept.
- The changes between two versions are computed field by field.

**Linking**

- A *process* groups the notices and versions of one tender.
- Links are made from the process number and the issuing body. A notice that cannot be linked with confidence stays on its own and is never guessed.
- Notices that extend, correct, cancel or award a tender are typed as such.

**Alerts and calendar**

- A user follows a process from a result or an alert.
- Followers are told of changes, and reminded a chosen number of days before a deadline, through the outbox from plan 10.
- A moved or cancelled deadline cancels or moves its pending reminders.
- A per-user calendar feed (iCalendar) lists followed deadlines, protected by a token that can be revoked.

## The hard parts

- **Wrong dates are worse than none.** A reminder built on a misread date misleads. The alert shows the source text next to the date.
- **Dates in text.** Notices carry many dates: signature, publication, opening, deadlines. They are written in several forms, and some are relative ("ten business days after the last publication"), which depends on a holiday calendar.
- **Inconsistent identifiers.** The same process number is written differently across notices, and different bodies reuse numbers.
- **What counts as a change.** Reformatting a record must not alert anyone.

## Milestones

1. Keep the opening date and procedure fields from the national CSV and store them as events.
2. Versions for changed records, with a field-level comparison.
3. Following a process, with reminders and change alerts.
4. Date extraction from gazette notices.
5. Linking of amendments, cancellations and awards.
6. Calendar feed.

## Success criteria

Measured on the tender profile of plan 1, extended with known events, amendments and cancellations:

- Dates extracted from text: precision of at least 0.99, with coverage reported next to it.
- Linking: precision of at least 0.99, with recall reported.
- With a controllable clock, every followed deadline produces one reminder, and a moved or cancelled one produces none for the old date.
- Ingesting the same version twice, or one that differs only in spacing, creates no new version and no alert.
- The calendar feed passes an iCalendar parser, and its times are correct in the installation's time zone.

## Open decisions

- Whether relative dates are computed or only shown as text. Computing them needs an official holiday calendar.
- Whether versions are rows in `documentos` or a separate table, which affects search, matching and the content-hash rule.
- How to cover the national dataset, which is updated every six months according to the connector and is too slow for live deadlines.
- Whether this applies only to the tender installation.
