"""FastAPI application entrypoint."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from src.api import deps
from src.api.auth import router as auth_router
from src.api.config import router as config_router
from src.api.deps import get_embedder, get_installation_config, get_search_backend
from src.api.feedback import router as feedback_router
from src.api.fuentes import router as fuentes_router
from src.api.ingest import router as ingest_router
from src.api.issues import router as issues_router
from src.api.notificaciones import router as notificaciones_router
from src.api.search import router as search_router
from src.api.suscripciones import router as suscripciones_router
from src.auth.operator import TOKEN_VARIABLE, configured_token
from src.config.installation import unfillable_filters, upsert_fuentes
from src.connectors.registry import METADATA_KEYS
from src.matching.matchers import matcher_from_environment
from src.matching.worker import DEFAULT_POLL_SECONDS, MatchingWorker
from src.scheduler import detener_scheduler, iniciar_scheduler
from src.seed.seed import sembrar_si_vacio

logger = logging.getLogger("contextcrawl")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FR-007: una configuración de instalación inválida no debe permitir
    # que el servicio arranque con configuración parcial.
    installation = get_installation_config()
    matcher = matcher_from_environment()
    if not configured_token():
        logger.warning("%s is not set: adding documents and running a source through the API are closed", TOKEN_VARIABLE)
    for clave in unfillable_filters(installation, METADATA_KEYS):
        logger.warning(
            "Config: no configured source can fill the filter '%s'; it will only find documents posted with that value",
            clave,
        )
    session_local = sessionmaker(bind=deps._engine())
    session = session_local()
    try:
        creadas = upsert_fuentes(session, installation)
        if creadas:
            logger.info("Config: %s fuentes nuevas de '%s'", creadas, installation.nombre)
        if installation.seed:
            creados = sembrar_si_vacio(session, get_embedder())
            if creados:
                logger.info("Seed: %s documentos de ejemplo cargados", creados)
    finally:
        session.close()

    scheduler = iniciar_scheduler(installation, deps._engine(), get_embedder())
    poll_seconds = float(os.environ.get("MATCHING_POLL_SECONDS") or DEFAULT_POLL_SECONDS)
    worker = MatchingWorker(deps._engine(), matcher, poll_seconds=poll_seconds)
    worker.start()
    # The engine loads in the background; until it is ready, PostgreSQL answers.
    search_backend = get_search_backend()
    search_backend.start(deps._engine())
    yield
    search_backend.stop()
    worker.stop()
    detener_scheduler(scheduler)


app = FastAPI(title="ContextCrawl backend", lifespan=lifespan)
app.include_router(search_router)
app.include_router(feedback_router)
app.include_router(ingest_router)
app.include_router(config_router)
app.include_router(fuentes_router)
app.include_router(auth_router)
app.include_router(suscripciones_router)
app.include_router(notificaciones_router)
app.include_router(issues_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
