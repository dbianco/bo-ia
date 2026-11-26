"""Scheduler in-process (APScheduler) que dispara el conector de cada
fuente según la frecuencia declarada en `installation.yaml` (FR-010,
FR-012). Corre dentro del mismo contenedor `backend`: cada job abre su
propia `Session` corta, igual que cada request de la API.

A restart does not put off a source: when it is due comes from its last
successful run, in `ejecuciones_fuente`, and not from when the backend started.
"""
from __future__ import annotations

import datetime
import logging

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.installation import InstallationConfig
from src.connectors.protocol import Conector
from src.connectors.registry import CONECTORES, VERSIONES
from src.connectors.runner import ejecutar_conector
from src.db.models import SUCCESSFUL_RUNS, EjecucionFuente, Fuente
from src.processor.embeddings import EmbeddingProvider

logger = logging.getLogger("contextcrawl.scheduler")

# Sources that are overdue when the backend starts: the first one after a delay,
# and then one after another.
STARTUP_DELAY = datetime.timedelta(seconds=5)
STARTUP_GAP = datetime.timedelta(seconds=30)
MAX_CONCURRENT_RUNS = 2


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


def first_runs(
    session: Session, installation: InstallationConfig, now: datetime.datetime
) -> dict[str, datetime.datetime]:
    """When each source with a connector has to run first: when its interval since
    the last successful run ends, or soon if that has passed or there was none."""
    last_runs = dict(
        session.execute(
            select(Fuente.clave, func.max(EjecucionFuente.inicio))
            .join(EjecucionFuente, EjecucionFuente.fuente_id == Fuente.id)
            .where(EjecucionFuente.estado.in_(SUCCESSFUL_RUNS))
            .group_by(Fuente.clave)
        ).all()
    )
    runs: dict[str, datetime.datetime] = {}
    overdue: list[tuple[datetime.datetime, str]] = []
    for source in installation.fuentes:
        if source.conector is None:
            continue
        last = last_runs.get(source.clave)
        never = datetime.datetime.min.replace(tzinfo=datetime.UTC)
        due = never if last is None else last + datetime.timedelta(minutes=source.conector.frecuencia_minutos)
        if due > now:
            runs[source.clave] = due
        else:
            overdue.append((due, source.clave))
    for position, (_, key) in enumerate(sorted(overdue)):  # the longest overdue first
        runs[key] = now + STARTUP_DELAY + position * STARTUP_GAP
    return runs


def iniciar_scheduler(
    installation: InstallationConfig,
    engine: Engine,
    embedder: EmbeddingProvider,
    *,
    conectores: dict[str, type[Conector]] = CONECTORES,
    versiones: dict[str, str] = VERSIONES,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        executors={"default": ThreadPoolExecutor(MAX_CONCURRENT_RUNS)}, timezone=datetime.UTC
    )
    runs: dict[str, datetime.datetime] = {}
    if any(f.conector for f in installation.fuentes):
        with sessionmaker(bind=engine)() as session:
            runs = first_runs(session, installation, datetime.datetime.now(datetime.UTC))
    for fuente_cfg in installation.fuentes:
        if fuente_cfg.conector is None:
            continue
        conector_cls = conectores[fuente_cfg.conector.tipo]
        version = versiones.get(fuente_cfg.conector.tipo, fuente_cfg.conector.tipo)
        scheduler.add_job(
            _ejecutar_job,
            trigger=IntervalTrigger(
                seconds=fuente_cfg.conector.frecuencia_minutos * 60,
                start_date=runs[fuente_cfg.clave],
                timezone=datetime.UTC,
            ),
            args=[engine, embedder, fuente_cfg.clave, conector_cls(), fuente_cfg.conector.config, version],
            id=f"fuente:{fuente_cfg.clave}",
            max_instances=1,
            misfire_grace_time=None,  # one that has to wait for another starts late: it is not skipped
            coalesce=True,
        )
    scheduler.start()
    return scheduler


def detener_scheduler(scheduler: BackgroundScheduler) -> None:
    scheduler.shutdown(wait=False)
