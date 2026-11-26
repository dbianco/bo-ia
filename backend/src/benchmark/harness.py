"""Runs systems against a corpus and writes the report.

Quality figures depend only on the seed, the size and the embedding provider.
Timings go to a separate file, so that a diff of two reports shows a regression
and nothing else."""
from __future__ import annotations

import json
import os
import platform
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from src.benchmark.metrics import (
    match_scores,
    mean,
    ndcg_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from src.benchmark.systems import MatchSystem, SearchSystem
from src.synthetic.corpus import Corpus

DEFAULT_KS = (10, 50)
DECIMALS = 4


def timing(seconds: Sequence[float]) -> dict[str, float]:
    total = sum(seconds)
    return {
        "count": len(seconds),
        "p50_ms": round(percentile(seconds, 50) * 1000, 3),
        "p95_ms": round(percentile(seconds, 95) * 1000, 3),
        "p99_ms": round(percentile(seconds, 99) * 1000, 3),
        "per_second": round(len(seconds) / total, 1) if total else 0.0,
    }


def evaluate_search(
    system: SearchSystem, corpus: Corpus, *, ks: Sequence[int] = DEFAULT_KS
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Quality per kind of query (and for all of them), and latency."""
    known = {d.identificador_externo for d in corpus.documents}
    per_query: list[tuple[str, dict[str, float]]] = []
    seconds = []
    for query in corpus.truth.queries:
        start = time.perf_counter()
        ranking = system.search(query.text, query.filters, max(ks))
        seconds.append(time.perf_counter() - start)
        unknown = [i for i in ranking if i not in known]
        if unknown:
            raise ValueError(f"{system.name} returned documents that are not in the corpus: {', '.join(unknown[:5])}")
        scores = {"mrr": reciprocal_rank(ranking, query.relevant)}
        for k in ks:
            scores[f"precision@{k}"] = precision_at_k(ranking, query.relevant, k)
            scores[f"recall@{k}"] = recall_at_k(ranking, query.relevant, k)
            scores[f"ndcg@{k}"] = ndcg_at_k(ranking, query.relevant, k)
        per_query.append((query.kind, scores))

    quality = {}
    for kind in ("all", "paraphrase", "same_vocabulary"):
        rows = [s for k, s in per_query if kind in ("all", k)]
        if rows:
            quality[kind] = {metric: round(mean([r[metric] for r in rows]), DECIMALS) for metric in sorted(rows[0])}
    return quality, timing(seconds)


def evaluate_matching(system: MatchSystem, corpus: Corpus) -> tuple[dict[str, float], dict[str, float]]:
    expected = {s.id: set(s.must_match) for s in corpus.truth.subscriptions}
    actual: dict[str, set[str]] = {}
    seconds = []
    for document in corpus.documents:
        start = time.perf_counter()
        matched = system.match(document)
        seconds.append(time.perf_counter() - start)
        for subscription in matched:
            actual.setdefault(subscription, set()).add(document.identificador_externo)
    scores = match_scores(expected, actual)
    return {k: round(v, DECIMALS) if isinstance(v, float) else v for k, v in scores.items()}, timing(seconds)


@dataclass
class BenchmarkResult:
    report: dict
    timings: dict = field(default_factory=dict)


def machine() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }


def run_benchmark(
    corpus: Corpus,
    *,
    search_systems: Sequence[SearchSystem] = (),
    match_systems: Sequence[MatchSystem] = (),
    embedding: dict | None = None,
    threshold: float | None = None,
    ks: Sequence[int] = DEFAULT_KS,
) -> BenchmarkResult:
    truth = corpus.truth
    report: dict = {
        "corpus": {
            "seed": truth.seed,
            "profile": truth.profile,
            "documents": len(corpus.documents),
            "generator_version": truth.generator_version,
            "topics": len(truth.topics),
            "queries": len(truth.queries),
            "subscriptions": len(truth.subscriptions),
            "republication_groups": len(truth.republications),
        },
        # Results from different providers are not comparable.
        "embedding": embedding,
        "match_threshold": threshold,
        "search": {},
        "matching": {},
    }
    timings: dict = {"machine": machine(), "search": {}, "matching": {}}
    for system in search_systems:
        report["search"][system.name], timings["search"][system.name] = evaluate_search(system, corpus, ks=ks)
    for system in match_systems:
        report["matching"][system.name], timings["matching"][system.name] = evaluate_matching(system, corpus)
    return BenchmarkResult(report, timings)


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    widths = [max(len(str(row[i])) for row in (header, *rows)) for i in range(len(header))]
    return ["  ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in (header, *rows)]


def format_report(report: dict) -> str:
    corpus = report["corpus"]
    lines = ["Corpus: " + ", ".join(f"{k}={v}" for k, v in corpus.items())]
    embedding = report["embedding"]
    described = ", ".join(f"{k}={v}" for k, v in embedding.items()) if embedding else "none"
    lines += [f"Embedding: {described}", f"Match threshold: {report['match_threshold']}", ""]
    if report["search"]:
        metrics = sorted(next(iter(report["search"].values()))["all"])
        rows = [
            [name, kind, *(f"{scores[m]:.4f}" for m in metrics)]
            for name, kinds in report["search"].items()
            for kind, scores in kinds.items()
        ]
        lines += _table(["search", "queries", *metrics], rows) + [""]
    if report["matching"]:
        metrics = ["precision", "recall", "true_positives", "false_positives", "misses"]
        rows = [[name, *(str(s[m]) for m in metrics)] for name, s in report["matching"].items()]
        lines += _table(["matching", *metrics], rows) + [""]
    return "\n".join(lines)


def format_timings(timings: dict) -> str:
    columns = ["count", "p50_ms", "p95_ms", "p99_ms", "per_second"]
    rows = [[f"{kind}: {name}", *(str(t[c]) for c in columns)] for kind in ("search", "matching")
            for name, t in timings[kind].items()]
    return "\n".join(_table(["timing", *columns], rows))


def write_report(result: BenchmarkResult, directory: Path, *, text: bool = True) -> None:
    directory.mkdir(parents=True, exist_ok=True)

    def write(name: str, text: str) -> None:
        (directory / name).write_text(text, encoding="utf-8", newline="\n")

    write("report.json", json.dumps(result.report, indent=1, ensure_ascii=False) + "\n")
    if text:
        write("report.txt", format_report(result.report))
    write("timings.json", json.dumps(result.timings, indent=1, ensure_ascii=False) + "\n")
