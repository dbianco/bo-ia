"""Scheduler in-process (APScheduler) que dispara el conector de cada
fuente según la frecuencia declarada en `installation.yaml` (FR-010,
FR-012). Corre dentro del mismo contenedor `backend`: cada job abre su
propia `Session` corta, igual que cada request de la API.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.config.installation import InstallationConfig
from src.connectors.protocol import Conector
from src.connectors.registry import CONECTORES, VERSIONES
from src.connectors.runner import ejecutar_conector
from src.db.models import Fuente
from src.processor.embeddings import EmbeddingProvider

logger = logging.getLogger("bo-ia.scheduler")


def _ejecutar_job(
    engine: Engine,
    embedder: EmbeddingProvider,
    fuente_clave: str,
    conector: Conector,
    config: dict,
    version_conector: str,
) -> None:
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        fuente = session.scalar(select(Fuente).where(Fuente.clave == fuente_clave))
        if fuente is None:
            logger.error("Scheduler: la fuente '%s' no existe; se saltea la corrida", fuente_clave)
            return
        ejecutar_conector(session, embedder, fuente, conector, config, version_conector=version_conector)
    finally:
        session.close()


def iniciar_scheduler(
    installation: InstallationConfig,
    engine: Engine,
    embedder: EmbeddingProvider,
    *,
    conectores: dict[str, type[Conector]] = CONECTORES,
    versiones: dict[str, str] = VERSIONES,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    for fuente_cfg in installation.fuentes:
        if fuente_cfg.conector is None:
            continue
        conector_cls = conectores[fuente_cfg.conector.tipo]
        version = versiones.get(fuente_cfg.conector.tipo, fuente_cfg.conector.tipo)
        scheduler.add_job(
            _ejecutar_job,
            trigger=IntervalTrigger(seconds=fuente_cfg.conector.frecuencia_minutos * 60),
            args=[engine, embedder, fuente_cfg.clave, conector_cls(), fuente_cfg.conector.config, version],
            id=f"fuente:{fuente_cfg.clave}",
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    return scheduler


def detener_scheduler(scheduler: BackgroundScheduler) -> None:
    scheduler.shutdown(wait=False)
