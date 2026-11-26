"""Splits documents that were stored as whole sections into their notices.

The notices go through the single ingestion path, without alerts: they were
published in the past. The section is not deleted, because matches, deliveries
and ratings refer to it; it only stops being searchable."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.connectors.protocol import Resegmenter
from src.db.models import SUPERSEDED, Documento, Fragmento, Fuente
from src.ingestor.contract import (
    DocumentoNormalizado,
    ErrorDeProcesamiento,
    ingerir_documento,
    source_metadata,
)
from src.processor.embeddings import EmbeddingProvider

logger = logging.getLogger("contextcrawl.resegment")


@dataclass
class ResegmentSummary:
    sections: int = 0  # stored whole sections that were looked at
    notices: int = 0
    unsegmented: int = 0  # sections without notices, left as they are
    failed: int = 0  # sections left for another run
    refetch_failed: int = 0  # sections split from the saved text because the PDF could not be downloaded
    metadata_filled: int = 0  # documents that received the fixed metadata of the source


def resegment_source(
    session: Session,
    embedder: EmbeddingProvider,
    fuente: Fuente,
    connector: Resegmenter,
    *,
    config: dict | None = None,
    refetch: bool = False,
    dry_run: bool = False,
) -> ResegmentSummary:
    summary = ResegmentSummary()
    refetch_config = (config or {}) if refetch else None
    _fill_metadata(session, fuente, summary, dry_run)
    stored = session.scalars(
        select(Documento)
        .where(Documento.fuente_id == fuente.id, Documento.issue.is_(None), Documento.estado != SUPERSEDED)
        .order_by(Documento.id)
    ).all()
    for section in stored:
        documents = _split(connector, fuente, section, refetch_config, summary)
        if documents is None:
            continue
        summary.sections += 1
        if not any(d.notice_number for d in documents):
            summary.unsegmented += 1
            if not dry_run:
                section.issue = section.identificador_externo
                session.commit()
            continue
        if dry_run:
            summary.notices += sum(1 for d in documents if d.notice_number)
            continue
        if _ingest_all(session, embedder, documents, summary):
            section.estado = SUPERSEDED
            # Out of the vector index too, where it would take the place of other results.
            session.execute(update(Fragmento).where(Fragmento.documento_id == section.id).values(embedding=None))
            session.commit()
        else:
            summary.failed += 1
    return summary


def _fill_metadata(session: Session, fuente: Fuente, summary: ResegmentSummary, dry_run: bool) -> None:
    fixed = source_metadata(fuente)
    if not fixed:
        return
    for document in session.scalars(select(Documento).where(Documento.fuente_id == fuente.id)):
        complete = {**fixed, **(document.metadata_ or {})}
        if complete != document.metadata_:
            summary.metadata_filled += 1
            if not dry_run:
                document.metadata_ = complete
    session.commit()


def _split(
    connector: Resegmenter, fuente: Fuente, section: Documento, refetch_config: dict | None, summary: ResegmentSummary
) -> list[DocumentoNormalizado] | None:
    def split(refetch_config: dict | None) -> list[DocumentoNormalizado] | None:
        return connector.resegment(
            fuente_clave=fuente.clave,
            identifier=section.identificador_externo,
            issue_date=section.fecha,
            text=section.texto,
            url=section.url_fuente,
            refetch_config=refetch_config,
        )

    if refetch_config is None:
        return split(None)
    try:
        return split(refetch_config)
    except Exception as exc:  # the network or the PDF: the saved text is still there
        logger.warning("%s: could not be downloaded again, using the saved text: %s", section.identificador_externo, exc)
        summary.refetch_failed += 1
        return split(None)


def _ingest_all(
    session: Session, embedder: EmbeddingProvider, documents: list[DocumentoNormalizado], summary: ResegmentSummary
) -> bool:
    for document in documents:
        try:
            result = ingerir_documento(session, embedder, document, evaluate=False)
        except ErrorDeProcesamiento as exc:
            logger.warning("%s: %s", document.identificador_externo, exc)
            # A document in "error" counts as ingested and would never be tried
            # again. This one can be rebuilt from the section at any time.
            failed = session.scalar(
                select(Documento)
                .join(Fuente, Documento.fuente_id == Fuente.id)
                .where(
                    Fuente.clave == document.fuente_clave,
                    Documento.identificador_externo == document.identificador_externo,
                    Documento.estado == "error",
                )
            )
            if failed is not None:
                session.delete(failed)
                session.commit()
            return False
        if document.notice_number and not result.ya_existia:
            summary.notices += 1
    return True
