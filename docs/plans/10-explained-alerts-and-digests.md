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

## Status

Implemented. Not marked as done yet: the test of the real model (`pytest -m slow`) and `pytest -m docker` have not been run, because the machine had neither the model nor Docker.

| Criterion | Result | Test |
|---|---|---|
| With the mail server down ingestion takes the same, nothing is lost, and then all are sent | Met | `tests/notifications/test_outbox.py::test_ingestion_takes_the_same_with_the_mail_server_down`, `::test_with_the_server_down_nothing_is_lost_and_then_all_are_sent` |
| With workers killed, at least once, and duplicates only in the window | Met: killed after claiming, before sending, after the server accepted and after recording; only the third sends twice, with the same Message-ID | `::test_a_worker_that_dies_loses_nothing`, `::test_random_deaths_send_everything_at_least_once`, `::test_many_workers_at_once_send_each_email_once` |
| Each match in exactly one digest | Met, over random sequences of matches, digests and failures | `tests/notifications/test_digests.py::test_each_match_is_in_exactly_one_digest`, `::test_a_match_that_arrives_while_the_digest_is_built`, `::test_two_workers_build_one_digest` |
| Every alert has an excerpt that is part of the document | Met | `tests/notifications/test_email_content.py::test_every_alert_carries_an_excerpt_that_is_part_of_the_document`, `tests/api/test_inbox.py` |
| HTML appears as text in the email and the web | Met | `test_email_content.py::test_text_with_html_appears_as_text`, `::test_the_excerpt_is_escaped_wherever_the_shared_words_are`, and the same in `tests/web/test_web.py` |

## Decisions

- **Worker.** A thread of the backend, like the scheduler and the matching. Rows are claimed with a lease and `SKIP LOCKED`, so several may run.
- **The window for a duplicate** is from the answer of the mail server to one commit.
- **Channels.** Only the inbox and email. Others can be added as a value of `canal` with its own way to send.
- **Order in a digest.** By score, and then by date. All the matches are in it; the first 20 of each subscription with an excerpt.
- **Digests.** At `DIGEST_HOUR`, local time of the installation; the weekly ones on Mondays. After days without running there is one with everything. The frequency is the one of the subscription when it matched: changing it does not move what is waiting. Pausing does not take back what was found before.
- **Retries.** From one minute, doubled, up to an hour, `EMAIL_MAX_RETRIES` times. Permanent: a rejected address or content. A refused sender, password or connection is of the server: it is tried again, and the others are not tried until then. With no `SMTP_HOST`, an email fails at once.
- **Pause link.** It asks before pausing, because mail scanners open links. Signed for that action and subscription, for a year. Without `LINK_SECRET` and `PUBLIC_WEB_URL`, emails have no link, and startup says so.
- **Highlighting** uses the analyzer of plan 4, so "licitaciones" marks "licitación".
- **Web screens.** In this plan: sign-in, accounts, subscriptions and the inbox, without scripts. Forms sent by other sites are refused.
- **Old pending emails.** The migration marks them as failed: they would have been sent now, perhaps months later.

## Found meanwhile

- "obra" and "obras" did not become one term in the analyzer of plan 4, and so in the full-text part of the engine. Fixed; the figures of plan 4 are from before.
- A line break in the text of a subscription made its emails fail. Fixed.
- SMTP with STARTTLS does not verify the certificate of the server, as before this plan.
- An address is not verified when an account is created, so alerts can be sent to somebody else's. The limit on new accounts and the pause link reduce it; verifying the address would close it.
