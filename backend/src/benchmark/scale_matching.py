"""Measures the matching engine with many subscriptions and long documents.

Recall and precision are against an exact scan of every subscription that passes
the filters. The scan itself is checked against the plain loop, one subscription
after another in Python, which is too slow to run on every document."""
from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

from src.benchmark.harness import BenchmarkResult, machine, timing
from src.benchmark.systems import embed_passages
from src.matching.subscription_index import DEFAULT_EF, SubscriptionIndex
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.processor.providers import describe_provider
from src.search.filters import construir_filtros_suscripcion, cumple_filtros
from src.synthetic.corpus import CorpusConfig, generate_corpus
from src.synthetic.subscriptions import generate_long_documents, generate_subscriptions
from src.vector.hnsw import DEFAULT_SLACK, DEFAULT_UPPER_EF, GRAPH_FROM

CHUNK = 20_000
SQL_SUBSCRIPTIONS = 2_000


@dataclass(frozen=True)
class ScaleMatchingConfig:
    seed: int = 42
    profile: str = "gazette"
    subscriptions: int = 1_000_000
    corpus_documents: int = 40_000  # where topics, filters and documents come from
    documents: int = 30
    fragments: int = 20
    threshold: float = 0.45
    synonym_coverage: float = 0.8
    dim: int = 1024
    reference_documents: int = 3  # also matched by the loop
    graph_from: int = GRAPH_FROM
    exact_below: int | None = None
    ef: int = DEFAULT_EF
    upper_ef: int = DEFAULT_UPPER_EF
    slack: float = DEFAULT_SLACK


def run_scale_matching(config: ScaleMatchingConfig, *, database_url: str | None = None) -> BenchmarkResult:
    corpus = generate_corpus(CorpusConfig(seed=config.seed, documents=config.corpus_documents, profile=config.profile))
    provider = HashedEmbeddingProvider(dim=config.dim, synonyms=corpus.synonym_table(config.synonym_coverage))
    declared = list(corpus.profile.filters)
    index = SubscriptionIndex(
        config.dim,
        graph_from=config.graph_from,
        exact_below=config.exact_below,
        ef=config.ef,
        upper_ef=config.upper_ef,
        slack=config.slack,
        capacity=config.subscriptions,
    )
    filters: list[dict] = []
    build = 0.0
    pending: list = []

    def flush() -> None:
        nonlocal build
        vectors = embed_passages(provider, [s.text for s in pending])
        snapshots = [construir_filtros_suscripcion(s.filters, declared) for s in pending]
        first = len(filters)
        start = time.perf_counter()
        index.add_many((first + i, v, f, True) for i, (v, f) in enumerate(zip(vectors, snapshots, strict=True)))
        build += time.perf_counter() - start
        filters.extend(snapshots)
        pending.clear()

    for subscription in generate_subscriptions(corpus, config.subscriptions):
        pending.append(subscription)
        if len(pending) == CHUNK:
            flush()
    if pending:
        flush()

    documents = [
        (metadata, embed_passages(provider, texts))
        for metadata, texts in generate_long_documents(corpus, count=config.documents, fragments=config.fragments)
    ]
    for metadata, fragments in documents[:2]:  # compiles, and fills the scratch space
        index.match(metadata, fragments, config.threshold)

    indexed, indexed_seconds = _timed(documents, lambda m, f: index.match(m, f, config.threshold))
    scan, scan_seconds = _timed(documents, lambda m, f: index.match_exactly(m, f, config.threshold))
    few = documents[: config.reference_documents]
    vectors = index.vectors_in_order()
    loop, loop_seconds = _timed(few, lambda m, f: _loop(filters, vectors, m, f, config.threshold))

    expected = sum(map(len, scan))
    found = sum(map(len, indexed))
    hits = sum(len(a.keys() & b.keys()) for a, b in zip(indexed, scan, strict=True))
    error = max(
        (abs(a[i] - b[i]) for a, b in zip(indexed, scan, strict=True) for i in a.keys() & b.keys()), default=0.0
    )
    report = {
        "config": asdict(config),
        "embedding": {**describe_provider(provider), "synonym_coverage": config.synonym_coverage},
        "quality": {
            "matches": expected,
            "recall": round(hits / expected, 4) if expected else 1.0,
            "precision": round(hits / found, 4) if found else 1.0,
            "largest_score_error": round(error, 7),
        },
        "reference": {
            "documents": len(few),
            "differences": sum(len(_clearly_different(a, b, config.threshold)) for a, b in zip(loop, scan, strict=False)),
        },
    }
    per_document = sum(indexed_seconds) / len(indexed_seconds)
    timings = {
        "machine": machine(),
        "build_seconds": round(build, 1),
        "indexed": timing(indexed_seconds),
        "scan": timing(scan_seconds),
        "loop": timing(loop_seconds),
        "speedup_over_loop": round(sum(loop_seconds) / len(loop_seconds) / per_document, 1),
        "speedup_over_scan": round(sum(scan_seconds) / len(scan_seconds) / per_document, 1),
    }
    if database_url:
        per_subscription = _sql_loop(database_url, filters, vectors, documents)
        timings["sql_loop"] = {
            "measured_subscriptions": min(SQL_SUBSCRIPTIONS, len(filters)),
            "ms_per_subscription": round(per_subscription * 1000, 4),
            "extrapolated_seconds_per_document": round(per_subscription * len(filters), 1),
            "speedup": round(per_subscription * len(filters) / per_document),
        }
    return BenchmarkResult(report, timings)


def _sql_loop(url: str, filters: list[dict], vectors: np.ndarray, documents: Sequence) -> float:
    """Seconds per subscription and document of the loop that the service used
    before, with a query for each subscription. Its cost is proportional to how
    many there are, so it is measured with few."""
    import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.benchmark.postgres import scratch_database
    from src.db.models import Documento, Fragmento, Fuente, Suscripcion, Usuario
    from src.matching.matchers import SqlLoopMatcher

    count = min(SQL_SUBSCRIPTIONS, len(filters))
    with scratch_database(url) as database:
        engine = create_engine(database)
        with Session(engine) as session:
            user, source = Usuario(email="a@example.org", password_hash="!"), Fuente(clave="f", nombre="f", config={})
            session.add_all([user, source])
            session.flush()
            session.add_all(
                Suscripcion(usuario_id=user.id, texto_busqueda="x", embedding=vectors[i], filtros=filters[i])
                for i in range(count)
            )
            seconds = 0.0
            few = documents[:3]
            for i, (metadata, fragments) in enumerate(few):
                day = datetime.date(2026, 1, 1)
                document = Documento(
                    fuente_id=source.id, identificador_externo=str(i), fecha=day, texto="x", url_fuente="x",
                    hash_contenido=str(i), metadata_=metadata,
                )  # fmt: skip
                session.add(document)
                session.flush()
                session.add_all(
                    Fragmento(documento_id=document.id, posicion=j, texto="x", fecha=day, embedding=f)
                    for j, f in enumerate(fragments)
                )
                session.commit()
                start = time.perf_counter()
                SqlLoopMatcher().match(session, document, 0.45)
                seconds += time.perf_counter() - start
        engine.dispose()
    return seconds / len(few) / count


def _timed(documents: Sequence, match) -> tuple[list[dict], list[float]]:
    results, seconds = [], []
    for metadata, fragments in documents:
        start = time.perf_counter()
        results.append(match(metadata, fragments))
        seconds.append(time.perf_counter() - start)
    return results, seconds


def _loop(filters: list[dict], vectors: np.ndarray, metadata: dict, fragments: np.ndarray, threshold: float) -> dict:
    matches = {}
    for identifier, condition in enumerate(filters):
        if cumple_filtros(metadata, condition):
            score = float((fragments @ vectors[identifier]).max())
            if score >= threshold:
                matches[identifier] = score
    return matches


def _clearly_different(a: dict, b: dict, threshold: float) -> set:
    """Leaves out what only the rounding of the last digit decides."""
    return {i for i in a.keys() ^ b.keys() if abs(a.get(i, b.get(i)) - threshold) > 1e-5}


def format_scale_matching(result: BenchmarkResult) -> str:
    quality, timings = result.report["quality"], result.timings
    return "\n".join(
        [
            f"{result.report['config']['subscriptions']} subscriptions, {quality['matches']} matches",
            f"recall {quality['recall']:.4f}, precision {quality['precision']:.4f}, "
            f"{result.report['reference']['differences']} differences between the scan and the loop",
            f"build {timings['build_seconds']} s",
            *(f"{name}: {timings[name]['p50_ms']} ms p50, {timings[name]['p95_ms']} ms p95"
              for name in ("indexed", "scan", "loop")),
            f"{timings['speedup_over_loop']} times the loop, {timings['speedup_over_scan']} times the scan",
            *([f"SQL loop: {timings['sql_loop']}"] if "sql_loop" in timings else []),
        ]
    )
