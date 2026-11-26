"""Benchmark command.

    python -m src.benchmark generate --profile gazette --seed 42 --documents 2000 --out benchmark-output/corpus
    python -m src.benchmark run --seed 42 --documents 2000 --out benchmark-output/run
    python -m src.benchmark precompute --provider model --documents 2000 --out benchmark-output/vectors.npz

Everything runs offline except `--provider model`. Corpora are generated on
demand and never committed."""
from __future__ import annotations

import argparse
import contextlib
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from src.benchmark.harness import format_report, format_timings, run_benchmark, write_report
from src.benchmark.systems import BruteForceMatch, LexicalSearch, OracleMatch, OracleSearch, VectorExactSearch
from src.ingestor.fragmenter import fragmentar_texto
from src.processor.embeddings import EMBEDDING_DIM, EmbeddingProvider
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.processor.precomputed_embeddings import MissingPrecomputedEmbedding, write_precomputed
from src.processor.providers import PROVIDERS, create_provider, describe_provider
from src.synthetic.corpus import PROFILES, Corpus, CorpusConfig, generate_corpus, write_corpus

OFFLINE_SYSTEMS = ("oracle", "lexical", "vector-exact", "match-brute-force")
POSTGRES_SEARCH = ("postgres-semantic", "postgres-hybrid", "postgres-all")
SYSTEMS = (*OFFLINE_SYSTEMS, *POSTGRES_SEARCH, "postgres-match")
NEED_EMBEDDINGS = set(SYSTEMS) - {"oracle", "lexical"}

# Share of the phrases that the offline provider is told are synonyms, and the
# similarity from which it matches. See docs/plans/02 for how they were chosen.
DEFAULT_COVERAGE = 0.8
DEFAULT_THRESHOLD = 0.45


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.benchmark", description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)

    corpus = argparse.ArgumentParser(add_help=False)
    corpus.add_argument("--profile", choices=sorted(PROFILES), default="gazette")
    corpus.add_argument("--seed", type=int, default=42)
    corpus.add_argument("--documents", type=int, default=2000)
    corpus.add_argument("--queries", type=int, default=120)
    corpus.add_argument("--subscriptions", type=int, default=60)
    corpus.add_argument("--out", type=Path, required=True)

    embedding = argparse.ArgumentParser(add_help=False)
    embedding.add_argument("--provider", choices=PROVIDERS, default="hashed")
    embedding.add_argument("--embedding-seed", type=int, default=0)
    embedding.add_argument("--dim", type=int, default=EMBEDDING_DIM,
                           help="hashed provider only; the database needs the default")
    embedding.add_argument("--synonym-coverage", type=float, default=DEFAULT_COVERAGE,
                           help="hashed provider only: share of the synonym phrases it knows, from 0 to 1")
    embedding.add_argument("--precomputed", type=Path, help="vector file for the precomputed provider")

    commands.add_parser("generate", parents=[corpus], help="write a corpus and its truth file")
    commands.add_parser("precompute", parents=[corpus, embedding], help="embed a corpus and save the vectors")
    run = commands.add_parser("run", parents=[corpus, embedding], help="measure systems against a corpus")
    run.add_argument("--systems", default=",".join(OFFLINE_SYSTEMS), help=f"comma separated: {', '.join(SYSTEMS)}")
    run.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="similarity threshold")
    run.add_argument("--database-url", help="PostgreSQL server for the postgres-* systems, which run in a "
                                            "database of their own, created and dropped by the command")
    return parser


def _generate(args: argparse.Namespace) -> Corpus:
    return generate_corpus(
        CorpusConfig(
            seed=args.seed,
            documents=args.documents,
            profile=args.profile,
            queries=args.queries,
            subscriptions=args.subscriptions,
        )
    )


def _provider(args: argparse.Namespace, corpus: Corpus) -> tuple[EmbeddingProvider, dict]:
    if args.provider == "hashed":
        if not 0 <= args.synonym_coverage <= 1:
            raise ValueError("--synonym-coverage must be between 0 and 1")
        provider = HashedEmbeddingProvider(
            dim=args.dim, seed=args.embedding_seed, synonyms=corpus.synonym_table(args.synonym_coverage)
        )
        return provider, {**describe_provider(provider), "synonym_coverage": args.synonym_coverage}
    provider = create_provider(args.provider, precomputed_file=args.precomputed)
    return provider, describe_provider(provider)


def _precompute(args: argparse.Namespace) -> None:
    corpus = _generate(args)
    provider, _ = _provider(args, corpus)
    passages = [text for d in corpus.documents for text in fragmentar_texto(d.texto)]
    queries = [q.text for q in corpus.truth.queries] + [s.text for s in corpus.truth.subscriptions]
    count = write_precomputed(args.out, provider, passages=passages, queries=queries)
    print(f"{count} vectors written to {args.out}")


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    requested = list(dict.fromkeys(s.strip() for s in args.systems.split(",") if s.strip()))
    unknown = [s for s in requested if s not in SYSTEMS]
    if unknown:
        parser.error(f"unknown systems: {', '.join(unknown)}")
    on_postgres = [s for s in requested if s.startswith("postgres-")]
    if on_postgres and not args.database_url:
        # On purpose not DATABASE_URL: that one belongs to an installation.
        parser.error("the postgres-* systems need --database-url")
    if on_postgres and args.dim != EMBEDDING_DIM:
        parser.error(f"the postgres-* systems need --dim {EMBEDDING_DIM}")

    corpus = _generate(args)
    filters = corpus.profile.filters
    provider, description = _provider(args, corpus) if NEED_EMBEDDINGS & set(requested) else (None, None)

    with contextlib.ExitStack() as stack:
        search, match = [], []
        if "oracle" in requested:
            search.append(OracleSearch(corpus.truth))
            match.append(OracleMatch(corpus.truth))
        if "lexical" in requested:
            search.append(LexicalSearch(corpus.documents, filters))
        if "vector-exact" in requested:
            search.append(VectorExactSearch(corpus.documents, provider, filters))
        if "match-brute-force" in requested:
            match.append(BruteForceMatch(corpus.truth.subscriptions, provider, filters, threshold=args.threshold))
        if on_postgres:
            from src.benchmark.postgres import PostgresMatch, PostgresSearch, scratch_database

            if "postgres-match" in on_postgres:  # measures ingestion, so it needs an empty database
                url = stack.enter_context(scratch_database(args.database_url))
                match.append(stack.enter_context(PostgresMatch(url, corpus, provider, threshold=args.threshold)))
            if set(on_postgres) & set(POSTGRES_SEARCH):
                url = stack.enter_context(scratch_database(args.database_url))
                for name in (s for s in on_postgres if s in POSTGRES_SEARCH):
                    mode = name.removeprefix("postgres-")
                    search.append(
                        stack.enter_context(PostgresSearch(url, corpus, provider, mode=mode, threshold=args.threshold))
                    )
        result = run_benchmark(
            corpus,
            search_systems=search,
            match_systems=match,
            embedding=description,
            threshold=args.threshold if provider else None,
        )
    write_report(result, args.out)
    print(format_report(result.report))
    print(format_timings(result.timings))


def main(argv: Sequence[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            corpus = _generate(args)
            write_corpus(corpus, args.out)
            print(f"{len(corpus.documents)} documents written to {args.out}")
        elif args.command == "precompute":
            _precompute(args)
        else:
            _run(parser, args)
    except (ValueError, MissingPrecomputedEmbedding) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    # A terminated run must still drop its scratch databases.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    main(sys.argv[1:])
