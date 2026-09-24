"""Conector `comprar-gob-ar-csv`: parseo de filas del CSV de convocatorias
nacionales (T004-T005), Etapa 5, FR-001 a FR-004."""
from pathlib import Path

from src.connectors.comprar_gob_ar.connector import ConectorComprarGobAr
from src.connectors.protocol import ErrorDescubrimiento
from src.ingestor.contract import DocumentoNormalizado

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "comprar_gob_ar"


def _config(**overrides) -> dict:
    csv_url = (FIXTURES / "convocatorias_sample.csv").resolve().as_uri()
    base = {"csv_url": csv_url}
    base.update(overrides)
    return base


def test_conector_produce_un_documento_normalizado_por_fila() -> None:
    conector = ConectorComprarGobAr()

    items = list(conector.descubrir(fuente_clave="comprar-ar-nacional", config=_config()))

    documentos = [i for i in items if isinstance(i, DocumentoNormalizado)]
    assert len(documentos) == 46  # 45 filas reales + 1 fila sintética sin Monto_Estimado

    primero = next(d for d in documentos if d.identificador_externo == "23-0001-LPR17")
    assert primero.titulo == "Servicio café  azúcar  edulcorante y máquinas  para de cafeterías en CASA DE GOBIERNO y HANGARES"
    assert "Servicio café" in primero.texto
    assert primero.metadata["organismo"] == "301 - Secretaria General de la Presidencia de la Nación"
    assert primero.metadata["monto"] == 1735400.00
    assert primero.metadata["jurisdiccion"] == "nacional"
    assert primero.fecha.isoformat() == "2017-03-03"


def test_fila_con_monto_no_parseable_se_ingiere_igual_sin_monto_en_metadata() -> None:
    conector = ConectorComprarGobAr()

    items = list(conector.descubrir(fuente_clave="comprar-ar-nacional", config=_config()))

    documentos = [i for i in items if isinstance(i, DocumentoNormalizado)]
    edge = next(d for d in documentos if d.identificador_externo == "99-9999-LPR26")
    assert "monto" not in edge.metadata
    assert edge.metadata["organismo"]
    assert not any(isinstance(i, ErrorDescubrimiento) for i in items)


def test_filtro_anio_desde_descarta_filas_de_anios_anteriores() -> None:
    conector = ConectorComprarGobAr()

    items = list(
        conector.descubrir(fuente_clave="comprar-ar-nacional", config=_config(anio_desde=2017))
    )

    documentos = [i for i in items if isinstance(i, DocumentoNormalizado)]
    # Fixture: 23 filas de 2016, 22 de 2017 y 1 fila sintética de 2026.
    assert len(documentos) == 23
    assert "81-0021-LPU16" not in {d.identificador_externo for d in documentos}
    assert not any(isinstance(i, ErrorDescubrimiento) for i in items)


def test_limite_filas_acota_la_corrida() -> None:
    # Una corrida real contra el dataset real (55MB, historia desde 2016)
    # con anio_desde=2026 llegó a matchear miles de filas: `limite_filas`
    # acota cuántas se procesan en una corrida, para no correr sin límite.
    conector = ConectorComprarGobAr()

    items = list(conector.descubrir(fuente_clave="comprar-ar-nacional", config=_config(limite_filas=3)))

    documentos = [i for i in items if isinstance(i, DocumentoNormalizado)]
    assert len(documentos) == 3
