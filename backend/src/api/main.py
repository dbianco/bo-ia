"""FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from src.api import deps
from src.api.deps import get_embedder
from src.api.feedback import router as feedback_router
from src.api.ingest import router as ingest_router
from src.api.search import router as search_router
from src.seed.seed import sembrar_si_vacio

logger = logging.getLogger("bo-ia")


@asynccontextmanager
async def lifespan(app: FastAPI):
    session_local = sessionmaker(bind=deps._engine())
    session = session_local()
    try:
        creados = sembrar_si_vacio(session, get_embedder())
        if creados:
            logger.info("Seed: %s boletines de ejemplo cargados", creados)
    finally:
        session.close()
    yield


app = FastAPI(title="bo-ia backend", lifespan=lifespan)
app.include_router(search_router)
app.include_router(feedback_router)
app.include_router(ingest_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
