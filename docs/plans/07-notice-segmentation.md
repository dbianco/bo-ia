# 7. Notice segmentation and citable results - DONE

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

## Status

Implemented and verified. Verified on 2026-11-26 on an Apple M4 Pro (14 cores, 24 GB, macOS 27.2, PostgreSQL 16 with pgvector in Docker): `ruff check src tests ../web` clean; 1,427 tests of the fast suite pass; the real model test and both search implementations of the `slow` suite pass; `pytest -m docker` passes with the real model, in a separate compose project. By hand: the connector ingested the real issue of the fixture into 35 notices and one cover. A second count on the rendered pages gave the same 35 (2, 5, 6, 5, 6, 3, 5 and 3 by page) and the same 6 image notices; the notices opened were on the stated pages; filtering by `provincia` returned them. The real site answered 403 to every weekday tried, from this version and from the previous one, so the issue was read from the fixture.

On 2026-11-26 the owner confirmed the count of 35 notices. Known limit: sections 1, 2, 3 and 5 of the real gazette have not been seen.

| Criterion | Result | Test |
|---|---|---|
| Boundary precision and recall of at least 0.99 | Met: 0.9997 and 0.9998 at worst over 17,053 notices in 400 generated issues, with no quoted closing lines and with one in every notice | `tests/connectors/test_boletin_cba_segmenter.py::test_boundary_precision_and_recall_on_generated_issues` (150 issues) |
| No text lost | Met, on the generated issues and on the fixture | same test, `::test_real_pdf_loses_no_text` and `tests/connectors/test_boletin_cba.py::test_no_text_of_the_issue_is_lost_between_extraction_and_documents` |
| Every result has a number and a page | Met for segmented issues. Text without a closing line is returned with its page, no number and `segmented: false` | `tests/api/test_notices.py::test_every_result_of_a_segmented_source_has_a_number_and_a_page`, `::test_an_unsegmented_document_says_so_and_has_a_page` |
| Each declared filter finds connector documents | Met | `tests/api/test_notices.py::test_provincia_filter_...`, `::test_municipio_filter_...`, `::test_organismo_and_monto_filters_...` |
| Fixture: notices equal the count | Met: 35 found, and the count of 35 confirmed by the owner: 2, 5, 6, 5, 6, 3, 5 and 3 ending on pages 1 to 8 | `tests/connectors/test_boletin_cba_segmenter.py::test_real_pdf_has_the_number_of_notices_counted_by_eye` |

The generator of issues shares no code with the splitter, but the same author wrote both. The fixture is the only real issue it was checked with.

## Findings

- 6 of the 35 notices of the fixture are images. Their text cannot be extracted: they are stored with their closing line only, and can be found by number but not by content. Reading them needs OCR, which no plan covers.
- The table of contents is extracted in the middle of a notice that continues on page 2. It is taken out, and the notice is made of two pieces of the text.
- A closing line gives the last publication date. A whole line with an earlier date than the issue is taken as a quotation.

## Decisions

- **PDF or paged text.** Both. Paged text measures the splitter at scale, and a small PDF writer (`src/synthetic/pdf.py`) tests extraction end to end.
- **Issue.** Not a table: `documentos.issue`, shared by its notices, with an index. `GET /v1/issues/{source}/{issue}` lists them.
- **Content hash.** Unique together with the date. Identical text on another day is another document; on the same day it is still a duplicate. This applies to every source: two tenders with the same text and different dates, of which the second was dropped, are now both stored. Downgrading gives the later copies a derived hash, so that no row is deleted.
- **Short notices.** Nothing special: a notice of up to 1,000 characters is already one fragment, and no fragment crosses a notice.
- **Cover and contents.** One document per issue, kept but not searchable (`not_searchable`), so that it does not match "licitaciones" every day.
- **Headers.** A line is removed if it repeats at the edge of at least 3 pages and 60% of them, and appears nowhere inside a page. In an issue of three pages or fewer the headers stay in the text: two pages are not proof, and removing body text is worse.
- **Page numbers** recorded are those of the PDF, which is what `#page=` opens.
- **`municipio`** is read from the title of municipal notices ("MUNICIPALIDAD DE ..."). The rule has not been checked with a real section 5. `organismo` and `monto` are not read from gazette notices, so filtering the tender installation by them excludes those: that is plan 8.
- **Re-segmented sections** are kept as `superseded`, because matches, deliveries and ratings refer to them, and raise no alerts.
