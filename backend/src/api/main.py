"""FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from src.api import deps
from src.api.config import router as config_router
from src.api.deps import get_embedder, get_installation_config
from src.api.feedback import router as feedback_router
from src.api.fuentes import router as fuentes_router
from src.api.ingest import router as ingest_router
from src.api.search import router as search_router
from src.config.installation import upsert_fuentes
from src.scheduler import detener_scheduler, iniciar_scheduler
from src.seed.seed import sembrar_si_vacio

logger = logging.getLogger("bo-ia")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FR-007: una configuración de instalación inválida no debe permitir
    # que el servicio arranque con configuración parcial.
    installation = get_installation_config()
    session_local = sessionmaker(bind=deps._engine())
    session = session_local()
    try:
        creadas = upsert_fuentes(session, installation)
        if creadas:
            logger.info("Config: %s fuentes nuevas de '%s'", creadas, installation.nombre)
        creados = sembrar_si_vacio(session, get_embedder())
        if creados:
            logger.info("Seed: %s documentos de ejemplo cargados", creados)
    finally:
        session.close()

    scheduler = iniciar_scheduler(installation, deps._engine(), get_embedder())
    yield
    detener_scheduler(scheduler)


app = FastAPI(title="bo-ia backend", lifespan=lifespan)
app.include_router(search_router)
app.include_router(feedback_router)
app.include_router(ingest_router)
app.include_router(config_router)
app.include_router(fuentes_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
