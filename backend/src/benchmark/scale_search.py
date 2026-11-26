"""Measures the search engine with many fragments: agreement of the pruned
lexical search with the exhaustive one, recall of the vector search against an
exact scan for several widths and filters, quality of each mode, and latency.
Apart, the latency of the PostgreSQL implementation on the same corpus."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np

from src.benchmark.harness import BenchmarkResult, evaluate_search, machine, timing
from src.benchmark.systems import EngineSearch, embed_query
from src.engine.engine import DEFAULT_EF
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.processor.providers import describe_provider
from src.synthetic.corpus import Corpus, CorpusConfig, generate_corpus
from src.vector.hnsw import GRAPH_FROM

SHARES = (1.0, 0.3, 0.1, 0.01)  # of the rows that a filter leaves
K = 10
MODES = ("lexical", "semantic", "hybrid", "all")


@dataclass(frozen=True)
class ScaleSearchConfig:
    seed: int = 42
    profile: str = "gazette"
    documents: int = 868_000  # some 1,000,000 fragments
    queries: int = 200
    threshold: float = 0.45
    synonym_coverage: float = 0.8
    dim: int = 1024
    graph_from: int = GRAPH_FROM
    ef: int = DEFAULT_EF
    widths: str = "32,64,128,256,512"


def run_scale_search(config: ScaleSearchConfig) -> BenchmarkResult:
    corpus = _corpus(config)
    provider = _provider(config, corpus)
    start = time.perf_counter()
    system = EngineSearch.build(
        corpus.documents, provider, corpus.profile.filters, ef=config.ef, graph_from=config.graph_from
    )
    build = time.perf_counter() - start  # with the embedding
    engine = system.engine
    queries = [(q.text, embed_query(provider, q.text), q.filters) for q in corpus.truth.queries]
    for text, vector, _ in queries[:3]:  # compiles
        engine.search(text, vector, mode="all", limit=K, threshold=0.0)
        engine.search(text, vector, mode="lexical", limit=K, threshold=0.0)

    report: dict = {
        "config": asdict(config),
        "embedding": {**describe_provider(provider), "synonym_coverage": config.synonym_coverage},
        "fragments": engine.rows,
    }
    timings: dict = {"machine": machine(), "build_seconds": round(build, 1)}
    report["lexical"], timings["lexical_exhaustive"] = _check_lexical(engine.lexical, [q[0] for q in queries])
    report["vector_curve"], timings["vector_curve"] = _vector_curve(
        engine.vectors, [q[1] for q in queries], [int(w) for w in config.widths.split(",")], config.seed
    )
    report["quality"] = {
        mode: evaluate_search(system.with_mode(mode, threshold=config.threshold), corpus)[0] for mode in MODES
    }

    def in_engine(mode: str, text: str, vector: np.ndarray, filters: dict):
        return engine.search(
            text, vector, mode=mode, limit=K, threshold=config.threshold, filters=filters,
            filters_declared=corpus.profile.filters,
        )  # fmt: skip

    for mode in MODES:
        timings[mode] = _latency(lambda *q, mode=mode: in_engine(mode, *q), queries)
    return BenchmarkResult(report, timings)


def _latency(search: Callable, queries: list) -> dict[str, float]:
    seconds = []
    for query in queries:
        start = time.perf_counter()
        search(*query)
        seconds.append(time.perf_counter() - start)
    return timing(seconds)


def _check_lexical(index, texts: list[str]) -> tuple[dict, dict]:
    different = scored = postings = 0
    seconds = []
    for text in texts:
        for require_all in (False, True):
            rows, scores = index.search(text, K, require_all=require_all)
            if not require_all:
                scored += index.last_scored
                postings += index.postings(text)
            start = time.perf_counter()
            expected_rows, expected_scores = index.search_exhaustive(text, K, require_all=require_all)
            seconds.append(time.perf_counter() - start)
            different += rows.tolist() != expected_rows.tolist() or scores.tolist() != expected_scores.tolist()
    return {
        "queries": len(texts),
        "different_top_10": different,
        "postings_scored": round(scored / postings, 4) if postings else 0.0,
    }, timing(seconds)


def _vector_curve(vectors, queries: list[np.ndarray], widths: list[int], seed: int) -> tuple[list[dict], list[dict]]:
    quality, latency = [], []
    for share in SHARES:
        allowed = None
        if share < 1:
            random = np.random.default_rng([seed, int(share * 1000)])
            allowed = (random.random(len(vectors)) < share).astype(np.uint8)
        # The similarity of the k-th: rows that tie with it are as good.
        floors, seconds = [], []
        for query in queries:
            start = time.perf_counter()
            _, sims = vectors.search(query, K, allowed=allowed, exact_below=len(vectors))
            seconds.append(time.perf_counter() - start)
            floors.append(sims[-1])
        latency.append({"allowed": share, "width": "exact scan", **timing(seconds)})
        for width in widths:
            hits, seconds = 0, []
            for query, floor in zip(queries, floors, strict=True):
                start = time.perf_counter()
                _, sims = vectors.search(query, K, ef=width, allowed=allowed)
                seconds.append(time.perf_counter() - start)
                hits += int((sims >= floor - 1e-6).sum())
            quality.append({"allowed": share, "width": width, "recall@10": round(hits / (K * len(queries)), 4)})
            latency.append({"allowed": share, "width": width, **timing(seconds)})
    return quality, latency


def run_scale_postgres(config: ScaleSearchConfig, database_url: str) -> BenchmarkResult:
    """The same corpus and queries on the PostgreSQL implementation. Apart from
    the engine, because both do not fit in the memory of a laptop at once."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from src.benchmark.postgres import PostgresSearch, _environment, scratch_database
    from src.benchmark.postgres_load import bulk_load
    from src.db.models import Documento, Fragmento
    from src.search.postgres import buscar
    from src.search.results import ModoBusqueda

    corpus = _corpus(config)
    provider = _provider(config, corpus)
    queries = [(q.text, q.filters) for q in corpus.truth.queries]
    report: dict = {"config": asdict(config)}
    timings: dict = {"machine": machine()}
    with scratch_database(database_url) as database, _environment("SIMILARITY_THRESHOLD", str(config.threshold)):
        report["fragments"], timings["load_seconds"] = bulk_load(database, corpus.documents, provider)
        engine = create_engine(database)
        with Session(engine) as session:
            # What the API does after a search in the engine.
            random = np.random.default_rng(config.seed)
            picks = [(random.integers(1, report["fragments"], size=K).tolist(),) for _ in queries]

            def read_rows(identifiers: list[int]) -> None:
                session.execute(
                    select(Fragmento, Documento)
                    .join(Documento, Fragmento.documento_id == Documento.id)
                    .where(Fragmento.id.in_(identifiers))
                ).all()
                session.expunge_all()

            _latency(read_rows, picks)
            timings["read_10_rows"] = _latency(read_rows, picks)
            for mode in ModoBusqueda:

                def search(text: str, filters: dict, mode=mode) -> None:
                    buscar(
                        session, provider, consulta=text, limite=K, modo=mode, filtros_solicitados=filters,
                        filtros_declarados=list(corpus.profile.filters),
                    )  # fmt: skip
                    session.expunge_all()

                _latency(search, queries)  # once, to warm the caches
                timings[mode.value] = _latency(search, queries)
        engine.dispose()
        report["quality"] = {}
        for mode in ModoBusqueda:
            with PostgresSearch(database, corpus, provider, mode=mode.value, threshold=config.threshold) as system:
                report["quality"][mode.value] = evaluate_search(system, corpus)[0]
    return BenchmarkResult(report, timings)


def _corpus(config: ScaleSearchConfig) -> Corpus:
    return generate_corpus(
        CorpusConfig(seed=config.seed, documents=config.documents, profile=config.profile, queries=config.queries)
    )


def _provider(config: ScaleSearchConfig, corpus: Corpus) -> HashedEmbeddingProvider:
    return HashedEmbeddingProvider(dim=config.dim, synonyms=corpus.synonym_table(config.synonym_coverage))


def format_scale_search(result: BenchmarkResult) -> str:
    report, timings = result.report, result.timings
    lines = [
        f"{report['fragments']} fragments, built in {timings['build_seconds']} s",
        f"lexical: {report['lexical']['different_top_10']} different results, "
        f"{report['lexical']['postings_scored']:.1%} of the postings scored, p95 {timings['lexical']['p95_ms']} ms "
        f"(exhaustive {timings['lexical_exhaustive']['p95_ms']} ms)",
        "allowed  width       recall@10  p50_ms    p95_ms",
    ]
    recalls = {(r["allowed"], r["width"]): r["recall@10"] for r in report["vector_curve"]}
    for row in timings["vector_curve"]:
        recall = recalls.get((row["allowed"], row["width"]), 1.0)
        lines.append(f"{row['allowed']:<7}  {row['width']!s:<10}  {recall:<9}  {row['p50_ms']:<8}  {row['p95_ms']}")
    for mode in MODES:
        ndcg = {kind: scores["ndcg@10"] for kind, scores in report["quality"][mode].items()}
        lines.append(f"{mode}: ndcg@10 {ndcg}, p95 {timings[mode]['p95_ms']} ms")
    return "\n".join(lines)
