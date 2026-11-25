# 14. Usage and operation statistics

## Goal

A statistics section that shows what an installation has collected, what it is doing for its users and how well it is working, with every figure defined and checkable against the stored data.

## Why

- Nobody can see how much an installation holds, whether it is growing, or whether its alerts reach anyone, without querying the database.
- Users cannot tell what the tool covers, so an empty result does not say whether nothing exists or nothing was collected.
- Decisions in other plans (thresholds, flush policies, which sources to fix) need numbers from real use.

## Current state

- There is no statistics endpoint or page.
- `ejecuciones_fuente` records the start, end, state and the discovered, new, existing and failed counts of each run. No endpoint lists them.
- Documents, fragments, subscriptions, matches, deliveries (with their state) and ratings are stored with creation times, and can be counted.
- Searches are not recorded, and neither is their latency. Only a rated result keeps its query text, in `valoraciones`.
- Accounts have no roles, so there is no way to restrict a page to an operator.
- Plan 13 plans a status page limited to source health. Plan 1 measures quality and speed on generated data, not on real use.

## Design

**Three audiences**

- **Public:** what the installation covers. Documents per source, date range, last successful update.
- **User:** their own activity. Matches per subscription over time, deliveries by state, their judgments.
- **Operator:** the whole installation. Ingestion per source and day, failures, delivery success and delay, match volume, ratings, search volume, latency and searches with no result.

**Definitions**

- One catalogue defines each statistic: name, formula, unit, time zone and audience. The API and the pages are built from it, so a number means the same everywhere.

**Computation**

- Counts come from the existing tables through one module with plain queries. This is the reference.
- Where a query becomes too slow, daily rollups are added and checked against the plain query. Rollups can always be rebuilt from the source tables.
- Search activity is recorded as daily aggregates: count, mode, latency buckets and number of empty results. Query text is not stored.

**Access**

- An operator role on accounts, granted by a command and not through the API.
- Public and user statistics never reveal another user's activity. Small groups are not broken out where doing so would identify one user.

**Presentation**

- An endpoint per audience and a statistics section in the web interface, with a table behind every chart, meeting the accessibility checklist.
- User statistics need the sign-in screens planned in plan 10. The operator view includes the source health of plan 13 instead of repeating it.

## The hard parts

- **History that changes.** Re-segmenting (plan 7), collapsing copies (plan 6) and retrying documents change past counts. Each statistic has to say whether it counts documents, notices or groups.
- **Day boundaries.** A publication date and an ingestion time are different things, and a day depends on the time zone.
- **Cost.** Counting large tables on every page view competes with search and ingestion.
- **Privacy.** Search behaviour is sensitive, and with few users even a total can point to one person.

## Milestones

1. Statistics catalogue and the plain queries, with tests against hand-counted data.
2. Public coverage endpoint and page.
3. Operator role, ingestion and delivery statistics, and run history (shared with plan 13).
4. Per-user statistics.
5. Aggregated search activity.
6. Daily rollups where measurements show they are needed.

## Success criteria

- On a small fixed data set, every statistic equals a value counted by hand.
- On the generated corpus, every rolled-up figure equals the plain query, including after deletes, retries and a rebuild.
- Access tests: a user never receives another user's figures, and only an operator reaches the operator view.
- No query text, email address or watched value is stored by statistics or appears in their responses.
- At the proposed scale of 1,000,000 fragments, each statistics page answers in under a stated time, and search latency does not rise measurably while it is loaded.

## Open decisions

- Whether public coverage statistics are shown to anonymous visitors by default.
- How long daily aggregates are kept.
- The minimum group size below which a figure is hidden.
- Whether to also expose operational metrics in a standard format for external monitoring tools.
