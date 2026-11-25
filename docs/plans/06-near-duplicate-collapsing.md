# 6. Near-duplicate collapsing

## Goal

A notice that is republished on several days appears once in search results and triggers one alert per subscriber, with the other copies reachable from it.

## Why

Gazettes publish the same notice on consecutive days, changing only the date and the notice number. In a 30-day sample of the Córdoba gazette analysed in the companion project, 44% of the fragments were copies of another fragment. Without collapsing, the top results for a query are copies of one notice, and a subscriber receives the same alert day after day.

## Current state

- Ingestion is idempotent for the same document, but a republished notice is a new document on a new date and is stored, indexed and matched again.
- Search returns fragments with no grouping.
- `evaluar_documento` records at most one match per document and subscription pair, so each republication produces a new match and a new notification.

## Design

**Fingerprints**

- An exact fingerprint of the normalized text: case and accents folded, digits and whitespace removed. It catches copies that differ only in dates and numbers.
- A near-duplicate signature (MinHash over word shingles, with locality-sensitive hashing to find candidates) for copies with small edits such as a corrected line.
- Candidates are confirmed with a similarity measure before they are grouped, so two different notices built from the same template are not merged.

**Groups**

- A group id is assigned at ingestion. The first document seen is the representative; later copies join the group.
- Groups are stable: a copy arriving later never changes the id of an existing group.

**Search**

- Results are collapsed to one entry per group, the best-scoring fragment, with the publication dates of the copies.
- Collapsing happens before the limit is applied, so a request for ten results returns ten distinct notices.

**Alerts**

- A subscription is notified once per group. A republication adds a publication date to the existing match instead of creating a notification.

## The hard parts

- **Templates versus copies.** Notices of the same kind share most of their words. The threshold between "same notice" and "same form, different parties" has to be set from data.
- **Stability.** Grouping decisions are made online, in arrival order, and must not depend on that order in ways users can see.
- **Scale.** Comparing every new fragment with every stored one is quadratic; the signature index has to find candidates in roughly constant time.
- **Fragments versus documents.** A long notice is split into fragments; grouping has to be consistent at both levels.

## Milestones

1. Exact fingerprint and group assignment at ingestion, with a migration for existing documents.
2. Collapsed search results, with the limit applied after collapsing.
3. One alert per group and subscription.
4. Near-duplicate signatures and the candidate index.
5. Threshold tuning on the synthetic corpus, including same-template distractors.

## Success criteria

Measured on the synthetic corpus from plan 1, whose republication groups and same-template distractors are known:

- Grouping precision of at least 0.99 (different notices are almost never merged) and recall of at least 0.95.
- No subscriber receives two alerts for the same notice.
- A search for ten results returns ten distinct groups whenever ten exist.
- Ingestion throughput with grouping enabled stays within a stated factor of throughput without it.

## Open decisions

- Whether edited copies (a correction notice) belong in the group of the original or stand alone and link to it.
- Whether a subscriber can opt in to be told about each republication, since a new publication date can matter legally.
- How grouping interacts with the indexes from plans 3 and 4: index one entry per group, or every copy.
