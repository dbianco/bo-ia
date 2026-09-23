"""T018: el scheduler dispara un conector fake en un intervalo acelerado
sin intervención manual (SC-005); una fuente sin conector declarado no
programa nada (FR-012)."""
import datetime
import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.config.installation import ConectorConfig, FuenteConfig, InstallationConfig
from src.db.models import EjecucionFuente, Fuente
from src.ingestor.contract import DocumentoNormalizado
from src.processor.embeddings import FakeEmbeddingProvider
from src.scheduler import detener_scheduler, iniciar_scheduler


class _ConectorFakeRapido:
    def descubrir(self, *, fuente_clave: str, config: dict):
        yield DocumentoNormalizado(
            fuente_clave=fuente_clave,
            identificador_externo="a",
            fecha=datetime.date(2026, 1, 1),
            texto="texto de prueba",
            url_fuente="https://example.org/a",
        )


def test_scheduler_dispara_automaticamente_sin_intervencion_manual(
    db_session: Session, test_database_url: str
) -> None:
    fuente = Fuente(clave="fuente-scheduler", nombre="Fuente scheduler", config={})
    db_session.add(fuente)
    db_session.commit()

    engine = create_engine(test_database_url)
    installation = InstallationConfig(
        nombre="test",
        fuentes=[
            FuenteConfig(
                clave="fuente-scheduler",
                nombre="Fuente scheduler",
                conector=ConectorConfig(tipo="fake", frecuencia_minutos=2 / 60),  # ~2 segundos
            )
        ],
    )
    scheduler = iniciar_scheduler(
        installation,
        engine,
        FakeEmbeddingProvider(),
        conectores={"fake": _ConectorFakeRapido},
        versiones={"fake": "fake-v1"},
    )
    try:
        ejecuciones = []
        for _ in range(20):
            time.sleep(0.5)
            db_session.expire_all()
            ejecuciones = db_session.scalars(
                select(EjecucionFuente)
                .where(EjecucionFuente.fuente_id == fuente.id)
                .where(EjecucionFuente.fin.is_not(None))
            ).all()
            if ejecuciones:
                break
        else:
            pytest.fail("El scheduler no completó ninguna ejecución dentro del tiempo esperado")
    finally:
        detener_scheduler(scheduler)
        engine.dispose()

    assert ejecuciones[0].estado == "completada"
    assert ejecuciones[0].version_conector == "fake-v1"


def test_fuente_sin_conector_declarado_no_programa_nada() -> None:
    installation = InstallationConfig(
        nombre="test",
        fuentes=[FuenteConfig(clave="fuente-sin-conector", nombre="Sin conector", conector=None)],
    )

    scheduler = iniciar_scheduler(installation, engine=None, embedder=None, conectores={}, versiones={})
    try:
        assert scheduler.get_jobs() == []
    finally:
        detener_scheduler(scheduler)
