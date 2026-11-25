# 12. Subscription preview and feedback-based tuning

## Goal

Before saving a subscription, a user sees what it would have matched. Afterwards, their judgments on alerts tune that subscription, and each change is checked against a fixed reference before it is applied.

## Why

- Nobody can tell whether a text query is too broad or too narrow until alerts arrive, or fail to.
- One similarity threshold serves every query, although score ranges differ between queries.
- Thumbs up and down are collected and never used.

## Current state

- `POST /v1/valoraciones` stores a fragment, the query text and a positive or negative value. It needs no account and records no user.
- Nothing reads the `valoraciones` table.
- Alerts cannot be rated.
- `SIMILARITY_THRESHOLD` is global, internal and absent from the API.
- A subscription's embedding is computed once from its text, when it is created.

## Design

**Preview**

- Given a text, filters and a strictness level, return the notices of a recent period that would have matched, with their count per week.
- It uses the same scoring and filter code as live matching, and creates no matches or notifications.

**Strictness**

- Each subscription has a threshold, offered to the user as a few strictness levels and not as a raw score.
- The global setting remains the default.

**Feedback on alerts**

- Each alert can be marked relevant or not, from the inbox or from a signed link in the email.
- The judgment is tied to the match, and so to a user and a subscription. Anonymous search ratings stay separate and never change anyone's alerts.

**Tuning**

- With enough judgments, the system proposes a change: a new threshold, or an adjusted query vector moved towards relevant examples and away from rejected ones (Rocchio).
- The proposal shows what it would add and remove over the recent period. The user accepts or rejects it.
- Every change is recorded and can be undone. The original text and vector are kept.

## The hard parts

- **Little data.** A subscription may collect only a handful of judgments, and fitting them closely overfits.
- **Feedback sees only what matched.** Judgments on alerts can raise precision but say nothing about notices that never alerted. Preview has to show near misses to cover that.
- **Silent loss.** A stricter subscription that drops a relevant notice produces no complaint.
- **Preview must not lie.** If preview and live matching differ in any way, the preview is worse than none.

## Milestones

1. Preview over a recent period, sharing the live matching code.
2. Per-subscription strictness.
3. Judgments on alerts, from the inbox and from email.
4. Offline evaluation of the tuning methods against a no-tuning baseline.
5. Proposals with their effect shown, accept, reject and undo.

## Success criteria

Measured on the synthetic corpus from plan 1, with simulated judgments drawn from its truth file, including a share of wrong ones:

- For the same documents and settings, preview returns exactly the matches that live matching records.
- On documents held out from tuning, precision improves over no tuning and recall does not fall by more than a stated margin. Both are always reported.
- With fewer judgments than a stated minimum, nothing is proposed.
- Undoing a change restores the earlier match results exactly.
- Anonymous ratings change no subscription.

## Open decisions

- The minimum number of judgments before a proposal.
- Whether a user can ever opt in to automatic tuning.
- The preview period and its cost without the index from plan 3.
- Whether aggregated search ratings should ever feed the ranking of plan 4, given that anyone can send them.
