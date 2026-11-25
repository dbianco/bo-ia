# 10. Explained alerts, digests and reliable delivery

## Goal

Every alert shows what matched and why, users choose between immediate delivery and a daily or weekly digest, and an email that fails is retried instead of lost.

## Why

- An alert that names only a document forces the user to open it and search for the reason.
- One email per match is unusable once an issue produces many documents (plan 7).
- A temporary mail server failure currently loses the email for good.
- Tender monitoring tools advertise scheduled digests and, in some cases, a written reason for each match.

## Current state

- The email body is the subscription text, the document title and the source URL (`backend/src/notifications/dispatcher.py`).
- `GET /v1/notificaciones` returns identifiers, channel, state and attempt time: no title, text, score or link.
- `EvaluacionMatch` stores the score and the filters applied, but not which fragment matched.
- `Suscripcion.frecuencia_notificacion` exists in the database. No code reads it and the API does not accept it.
- Email is sent during ingestion, with a 10 second timeout per SMTP attempt. A failure is marked `fallida`, and `reintentos` is never incremented.
- The web interface has no login, subscription or inbox screens.

## Design

**Explanation**

- Matching records the best fragment of each match.
- An alert shows that fragment as an excerpt, the notice title, number, date and page where known, the score and the filters that were met.
- Words shared with the subscription are highlighted. When there are none, the alert says the match is by meaning, without inventing a reason.

**Outbox**

- Matching only writes delivery rows, in the same transaction as the match. It sends nothing.
- A worker claims pending rows, sends them and records the result.
- Failures that can be retried use exponential backoff up to a maximum, then become `fallida`. Permanent failures, such as a rejected address, are not retried.
- Each email carries a stable message identifier built from its deliveries.

**Digests**

- Each subscription is immediate, daily or weekly.
- A digest is one email per user and period that groups matches by subscription. An empty period sends nothing.
- Periods use the installation's time zone.

**Control and inbox**

- Every email has a link to pause the subscription without signing in, using a signed token limited to that action.
- Inbox entries can be marked as read.
- The web interface gains sign-in, subscription management and the inbox.

## The hard parts

- **Exactly once is not available.** If the process dies after the mail server accepts a message and before the result is saved, it will be sent again. The design has to keep that window small and say that it exists.
- **Concurrent workers.** Two workers, or a restart during a send, must not claim the same row.
- **Digest boundaries.** A match that arrives while a digest is being built belongs to that one or the next, never both and never neither.
- **Untrusted text.** Excerpts come from external PDFs and must be escaped in HTML email and in the web pages.

## Milestones

1. Best fragment stored with each match; excerpt, title, score and link in the inbox API.
2. Outbox and worker with retries; sending removed from ingestion.
3. Explained email.
4. Daily and weekly digests.
5. Pause link and read state.
6. Web screens for sign-in, subscriptions and the inbox.

## Success criteria

Tested against a local fake SMTP server, with a controllable clock:

- With the mail server down, ingestion time does not change and no delivery is lost; once it is back, all are sent.
- With workers killed at injected points, every delivery is sent at least once, and duplicates occur only in the window described above.
- Over a long random sequence of matches and digest runs, each match appears in exactly one digest.
- Every alert for a text subscription carries an excerpt that is part of the matched document.
- Text containing HTML appears as text in the email and in the web pages.

## Open decisions

- Whether the worker is a thread in the backend, like the scheduler, or a separate process.
- Channels besides email and inbox, such as a webhook or Telegram.
- Whether a digest orders matches by score or by date.
- Whether the web screens are better as a plan of their own.
