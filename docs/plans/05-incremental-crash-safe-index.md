# 5. Incremental, crash-safe index

## Goal

The indexes from plans 3 and 4 accept additions, updates and deletes while serving queries, survive a process kill at any moment, and restart to a correct state without a full rebuild.

## Why

Ingestion is continuous and idempotent: connectors run on a schedule and the same document can arrive again. An index that has to be rebuilt from the database after every change, or that can be left half-written, is not usable in the product.

## Current state

- PostgreSQL provides durability and updates for both search and matching today.
- Ingestion is idempotent at the document level.
- Plans 3 and 4 introduce in-process indexes with no persistence of their own.

## Design

**Write path**

- A write-ahead log: every change (add, update, delete) is appended and synced before it is acknowledged.
- An in-memory segment receives new entries and is searchable immediately.
- When it reaches a size limit it is written as an immutable on-disk segment, checksummed, and the log is truncated.

**Read path**

- A query searches every live segment and merges the results.
- Deletes and updates are recorded as tombstones, applied when merging results.
- Each query runs against a consistent snapshot of the segment list.

**Maintenance**

- Background merging of small segments into larger ones, dropping tombstoned entries.
- A manifest file lists the live segments; it is replaced atomically (write, sync, rename), so a crash leaves either the old or the new list, never a mix.

**Recovery**

- On start: read the manifest, verify segment checksums, replay the log, discard a torn final record.
- A consistency check against PostgreSQL, which remains the system of record, with a rebuild path if the index is beyond repair.

## The hard parts

- **Ordering of sync and rename.** Durability bugs come from doing these in the wrong order and only show up on a crash.
- **Deletes in a graph index.** Removing a node from HNSW damages the paths through it; tombstones keep the graph intact until a merge rebuilds it.
- **Merging without blocking.** Queries and writes continue while segments are merged and swapped.
- **Ranking across segments.** BM25 statistics differ per segment; scores must be computed from global statistics to stay comparable.

## Milestones

1. Write-ahead log with checksummed records and replay.
2. Immutable segment format, flush and the manifest swap.
3. Multi-segment search with tombstones and global statistics.
4. Background merge.
5. Recovery, the consistency check and the rebuild path.
6. Fault-injection test suite.

## Success criteria

- **Crash tests.** The process is killed at injected points in every write, flush and merge step. After restart, every acknowledged change is present, no unacknowledged change is half-applied, and search results equal those of an index rebuilt from scratch with the same changes.
- **Randomized history test.** Long random sequences of add, update, delete, flush, merge and crash, compared after each step with a simple in-memory model.
- **Recovery time.** Proportional to the log since the last flush, not to the index size.
- **No pauses.** Query p95 during a merge stays within a stated factor of the idle p95.

## Open decisions

- One shared storage layer for both indexes, or one each.
- How far to test real power-loss behaviour, as opposed to process kills, without special hardware.
- Flush and merge policies, to be set from benchmark numbers.
