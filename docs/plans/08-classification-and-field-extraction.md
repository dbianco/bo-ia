# 8. Notice classification and field extraction

## Goal

Each notice gets a type, an issuing body and, where it has one, an amount, extracted at ingestion, so people can filter by them in search and in subscriptions.

## Why

- A gazette section mixes many kinds of notice. "Only tenders" or "only company incorporations" cannot be asked for today.
- The tender installation filters by contracting body and amount, but only the national dataset provides them. Notices from the Córdoba gazette have neither.
- The companion project classifies notices by norm type, which ContextCrawl does not do.

## Current state

- Metadata is whatever the connector supplies. Nothing is derived from the text.
- `comprar-gob-ar-csv` fills `organismo` and `monto` from CSV columns. `boletin-cba-pdf-diario` fills neither.
- The filter types `seleccion` and `rango_numerico` already work on any metadata key (`backend/src/search/filters.py`).
- There is no table or field that records where a metadata value came from.
- The companion project labels norm types with rules over the gazette's structure and trains a baseline classifier on them. It reports macro F1 0.876 against those rule labels, which no person has validated: the figure measures agreement with the rules, not accuracy. It also found that the issuing body could not be read reliably from the extracted text.

## Design

**Enrichment step**

- Runs after segmentation and before matching, so subscription filters see the extracted values.
- Each installation lists its extractors in `installation.yaml`. The engine knows only the interface: text and source metadata in, fields out.
- A value supplied by the connector always wins over an extracted one.

**Extractors**

- **Rules** for structured cues: act headings, opening phrases, amounts with their currency.
- **A classifier trained here** (a linear model over word features) for the notice type, compared with the rules as a baseline.

**Provenance**

- Each extracted value records the extractor, its version, a confidence and the text span it was read from.
- Below a confidence cut-off the field is left empty. An empty value is better than a wrong one that hides a notice from a filter.

**Reprocessing**

- A command runs a new extractor version over stored documents without embedding them again.

## The hard parts

- **Circular evaluation.** A classifier trained on rule labels and scored on rule labels measures nothing new. Truth must come from the generator, plus a hand-labelled sample of real notices.
- **Filters make errors invisible.** A wrong value does not appear as a bad result; the notice simply never appears. Precision matters more than coverage, and users need a way to include notices with no value.
- **Amounts.** Notices carry several figures: budget, price of the bidding documents, guarantee. Picking the first number is wrong.
- **Local number formats.** `$ 1.735.400,00` in a gazette and `1,735,400.00` in the CSV are the same amount.

## Milestones

1. Extractor interface, provenance storage and the reprocessing command.
2. Notice-type rules, with a taxonomy declared per installation.
3. Amount and issuing-body extractors.
4. Trained notice-type classifier, compared with the rules.
5. Notice type as a search and subscription filter, with an option to include unclassified notices.
6. A hand-labelled sample of real notices and a report of the results on it.

## Success criteria

Measured on the synthetic corpus from plan 1, whose notice types and field values are known:

- Notice type: macro F1 of at least 0.90, with the score of each class reported.
- Amount and issuing body: precision of at least 0.98 among the values filled in, with coverage reported next to it.
- The classifier is kept only if it beats the rules on text whose cues the rules were not written for.
- Reprocessing the same documents with the same version changes nothing.
- A report on the hand-labelled real sample, stating its size and who labelled it. No threshold is set until that sample exists.

## Open decisions

- The list of notice types for each installation.
- Whether a notice can have more than one type.
- Where the hand-labelled sample lives, given that real notices name real people and benchmarks use generated data only.
- Whether a language model is allowed as an optional extractor. It could not be part of the offline tests.
