# 7. Notice segmentation and citable results

## Goal

Each notice in a gazette issue is a document of its own, with its notice number and pages, so a search result and an alert point to one notice and say where to find it.

## Why

- An official gazette section is one PDF holding many unrelated notices. Users care about one notice, not about the section it was printed in.
- Because a match is recorded once per document and subscription, a subscriber gets at most one alert per section per day, however many notices in it are relevant.
- A citation today is a link to the whole PDF.
- The companion project (`bo-nlp`) splits the same PDFs into pages and keeps fragments inside notice boundaries, which shows this is feasible on the real source.

## Current state

- `backend/src/connectors/boletin_cba/connector.py` yields one `DocumentoNormalizado` per date and section, with the full PDF text.
- `extraer_texto_pdf` (`backend/src/connectors/bop_cordoba/pdf.py`) joins all pages into one string, so page numbers are lost.
- `backend/src/ingestor/fragmenter.py` cuts the text every 1,000 characters with 200 of overlap, so a fragment can start in one notice and end in the next.
- The connector writes the metadata keys `jurisdiccion` and `seccion`, but `installation.yaml` declares the filters `provincia` and `municipio`. Filtering a search or a subscription by either excludes every document this connector collects.
- The companion project found three properties of these PDFs: text is laid out in two columns, so extraction must follow content order and not position on the page; a page header repeats on later pages with the page number attached; and each notice ends with a closing line such as `3 días - Nº 688209 - s/c - 24/9/2026 - BOE`.

## Design

**Page-aware extraction**

- Extraction returns a list of pages instead of one string.
- A cleaner removes headers and footers found by repetition across pages, with no fixed list, and never removes body text.

**Notice splitting**

- The closing line ends a notice. The splitter reads the notice number, the number of publication days and the date from it.
- Text with no closing line (cover, table of contents, a section that uses another layout) becomes an explicit "unsegmented" document. No text is dropped.
- Splitting rules belong to the connector, not to the engine, as the connector protocol already requires.

**Document model**

- One document per notice. Its external identifier is built from the date, the section and the notice number.
- The issue it came from (source, date, section, URL) is kept, so the notices of one PDF can be listed together.
- Each document records its first and last page, and each fragment its page.
- The link opens the PDF at the first page of the notice where the viewer supports a page anchor.

**Filters**

- The connector fills the metadata keys the installation declares. Values that are constant for a source (such as the province) are set in the source's configuration, not in code.
- At startup, a declared filter that no configured source can fill is reported as a warning.

**Existing data**

- A command re-segments documents already stored as whole sections from their saved text. Pages cannot be recovered without the PDF, so those notices have no page number unless the PDF is downloaded again.

## The hard parts

- **Boundaries.** A missed closing line merges two notices; a false one cuts a notice in half. A line that quotes a closing line inside a notice must not split it.
- **No silent loss.** Every character of the cleaned text must belong to exactly one document.
- **Identity and deduplication.** The same notice runs on consecutive days with the same number. Each day's copy needs its own identifier, but ingestion also rejects a document whose content hash already exists, so copies with identical text would be dropped and their publication dates lost. Grouping them is plan 6.
- **Cost.** Many small documents mean many more rows, matches and alerts per issue than today.

## Milestones

1. Page-by-page extraction and header removal, tested against the existing fixture PDF.
2. Notice splitter with the unsegmented fallback and the no-loss check.
3. One document per notice from the connector, with issue, notice number and pages.
4. Declared filter values filled from source configuration, with the startup warning.
5. Page and notice number in the search response and the web results.
6. Re-segmentation command for stored data, with its migration.

## Success criteria

Measured on generated issues with known notice boundaries, laid out like the real ones:

- Boundary precision and recall of at least 0.99.
- For every issue, joining the notices and the unsegmented text gives back the cleaned text.
- Every result from a segmented source carries a notice number and a page.
- A test searches with each declared filter and finds connector documents.
- On the real fixture PDF, the number of notices equals a count made and written down by a person.

## Open decisions

- Whether the generator from plan 1 produces PDF files or paged text. Paged text tests the splitter; PDF files also test extraction.
- Whether an issue is a database table or only metadata shared by its notices.
- How the content-hash rule changes so that identical notices published on different days are all kept.
- Whether short notices should be one fragment each, with fragmenting applied only to long ones.
