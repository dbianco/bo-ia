# 9. Entity watchlists

## Goal

A user lists companies or tax identifiers (CUIT) to watch and is alerted whenever a new notice mentions one, with no similarity threshold involved.

## Why

- "Was my company, or my client, named in the gazette?" is a basic reason to monitor one. Argentine services such as Indicadores Argentina and Dateas advertise following a CUIT.
- Semantic similarity is the wrong tool for it. An embedding does not tell two CUITs apart reliably, and a mention buried in a long notice barely moves its score.

## Current state

- A subscription is a free-text query plus metadata filters. Its only condition on the text is cosine similarity against `SIMILARITY_THRESHOLD`.
- Full-text search (`texto_tsv`) is used by the `hybrid` and `all` search modes, but not by subscription matching.
- No identifiers or names are extracted from documents.

## Design

**Watched entities**

- Two kinds: a tax identifier, validated by its check digit, and a name with optional aliases.
- They belong to a user, can be paused and deleted, and use the same notification channels as subscriptions.

**Normalization**

- Identifiers: digits only, so `30-12345678-1`, `30.12345678.1` and `30123456781` are equal.
- Names: case and accents folded, punctuation and spacing unified, and company suffixes (`S.A.`, `S.R.L.`, `S.A.S.`) treated as optional.

**Matching**

- One multi-pattern automaton (Aho-Corasick), written here, holds every watched form. A new document is scanned once, whatever the number of watched entities.
- A match must fall on token boundaries, so a number inside a longer number never counts.
- It runs on the whole document text, not on fragments, so a mention cut by a fragment boundary is not missed.
- Each match records the position and the matched text, to show it in the alert.

**History**

- When an entity is added, the user can ask for past mentions. This returns a list and creates no notifications.

## The hard parts

- **Extraction noise.** PDF text breaks numbers and names across lines and columns and hyphenates words.
- **Common names.** A person's name matches namesakes. A name match is evidence of a mention, not of identity, and the alert has to say so.
- **Personal data.** A CUIT can belong to a person, and a watchlist shows whom a user is interested in. Lists must be private, deletable and kept out of logs.
- **Updates.** Entities change while documents arrive, and the automaton cannot be rebuilt for every document.

## Milestones

1. Identifier validation and the normalizer, with tests for the written forms.
2. Aho-Corasick matcher, checked against a brute-force scan.
3. Watched entities: data model, API and ownership rules.
4. Matching after ingestion, creating alerts with the matched text.
5. Name entities with aliases.
6. Search of past mentions.

## Success criteria

Measured on the synthetic corpus from plan 1, extended with generated identifiers and names in the written forms above and with line breaks:

- Identifiers: recall of 1.0 and precision of 1.0 on every planted form.
- Names: recall of at least 0.98 on planted variants, with precision reported against planted near-names.
- Property tests: the automaton returns the same matches as the brute-force scan.
- Proposed scale: with 1,000,000 watched entities, scanning time per document stays within a stated factor of the time with 1,000.
- No watched value appears in application logs.

## Open decisions

- Whether watching a person's name is offered at all, or only companies and identifiers.
- Whether an alert on a name needs a second condition, such as a province or a notice type, to cut namesake noise.
- Whether watched entities are a kind of subscription or a separate model.
- Whether matching runs on the queue introduced by plan 3.
