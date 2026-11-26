"""Splits the documents a source stored as whole sections into notices.

    python -m src.commands.resegment --source cordoba-provincial --dry-run
    python -m src.commands.resegment --source cordoba-provincial [--refetch]

Uses DATABASE_URL, INSTALLATION_CONFIG and the embedding settings of the service.
It can be run again: it continues where it stopped."""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.api import deps
from src.config.installation import cargar_installation_config, upsert_fuentes
from src.connectors.protocol import Resegmenter
from src.connectors.registry import CONECTORES
from src.db.models import Fuente
from src.ingestor.resegment import resegment_source


def main(argv: Sequence[str] | None = None) -> None:

    parser = argparse.ArgumentParser(prog="python -m src.commands.resegment", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--source", required=True, help="key of the source in installation.yaml")
    parser.add_argument("--refetch", action="store_true",
                        help="download each PDF again to know the pages; without it the notices have no page")
    parser.add_argument("--dry-run", action="store_true", help="only count")
    args = parser.parse_args(argv)

    installation = cargar_installation_config(os.environ["INSTALLATION_CONFIG"])
    declared = next((f for f in installation.fuentes if f.clave == args.source), None)
    if declared is None or declared.conector is None:
        parser.error(f"the source {args.source!r} does not exist or has no connector")
    connector = CONECTORES[declared.conector.tipo]()
    if not isinstance(connector, Resegmenter):
        parser.error(f"the connector of {args.source!r} does not produce notices")

    session = sessionmaker(bind=deps._engine())()
    try:
        upsert_fuentes(session, installation)  # the fixed metadata of the sources
        fuente = session.scalar(select(Fuente).where(Fuente.clave == args.source))
        embedder = None if args.dry_run else deps.get_embedder()
        summary = resegment_source(
            session,
            embedder,
            fuente,
            connector,
            config=declared.conector.config,
            refetch=args.refetch,
            dry_run=args.dry_run,
        )
    finally:
        session.close()
    print(
        f"{summary.sections} sections, {summary.notices} notices, {summary.unsegmented} sections without notices, "
        f"{summary.failed} failed, {summary.refetch_failed} not downloaded, "
        f"{summary.metadata_filled} documents with metadata added" + (" (dry run)" if args.dry_run else "")
    )
    if summary.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
