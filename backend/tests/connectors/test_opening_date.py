"""Plan 15, defects F and G on the tender dataset."""
import csv
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.connectors.comprar_gob_ar.connector import METADATA_KEYS, ConectorComprarGobAr, parse_opening
from src.connectors.runner import ejecutar_conector
from src.db.models import Documento, Fuente
from src.processor.embeddings import FakeEmbeddingProvider

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "comprar_gob_ar" / "convocatorias_sample.csv"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("16/03/2017 02:00:00 p.m.", "2017-03-16T14:00:00"),
        ("25/08/2017 11:00:00 a.m.", "2017-08-25T11:00:00"),
        ("11/07/2017 12:00:00 p.m.", "2017-07-11T12:00:00"),
        ("11/07/2017 12:30:00 a.m.", "2017-07-11T00:30:00"),
        (" 6/3/2017  2:00:00 P. M. ", "2017-03-06T14:00:00"),
        ("16/03/2017 14:05", "2017-03-16T14:05:00"),
        ("16/03/2017", "2017-03-16"),
        ("", None),
        ("   ", None),
        (None, None),
        ("a confirmar", None),
        ("31/02/2017 02:00:00 p.m.", None),
        ("16/03/2017 25:00:00", None),
        ("16/03/2017 13:00:00 p.m.", None),
    ],
)
def test_reads_the_opening_date(value, expected) -> None:
    assert parse_opening(value) == expected


def _rows() -> list[dict]:
    return list(csv.DictReader(SAMPLE.open(encoding="utf-8")))


def _write(path: Path, rows: list[dict]) -> dict:
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"csv_url": path.as_uri()}


@pytest.fixture()
def run(db_session: Session):
    source = Fuente(clave="t", nombre="t", config={})
    db_session.add(source)
    db_session.commit()

    def execute(config: dict):
        return ejecutar_conector(
            db_session, FakeEmbeddingProvider(), source, ConectorComprarGobAr(), config, version_conector="v"
        )

    return execute


def _stored(session: Session, identifier: str) -> Documento:
    session.expire_all()
    return session.scalar(select(Documento).where(Documento.identificador_externo == identifier))


def test_every_row_of_the_sample_keeps_its_opening_date() -> None:
    documents = list(ConectorComprarGobAr().descubrir(fuente_clave="t", config={"csv_url": SAMPLE.as_uri()}))
    assert documents[0].metadata["opening_date"] == "2017-03-16T14:00:00"
    assert all("opening_date" in d.metadata for d in documents)
    assert "opening_date" in METADATA_KEYS


@pytest.mark.parametrize("value", ["", "a confirmar"])
def test_a_row_without_a_readable_date_is_still_ingested(db_session: Session, run, tmp_path, value) -> None:
    row = {**_rows()[0], "Fecha_de_Apertura": value}
    assert run(_write(tmp_path / "a.csv", [row])).nuevos == 1
    assert "opening_date" not in _stored(db_session, row["Numero_Proceso"]).metadata_


def test_a_dataset_without_the_column_is_still_ingested(run, tmp_path) -> None:
    row = _rows()[0]
    del row["Fecha_de_Apertura"]
    assert run(_write(tmp_path / "a.csv", [row])).nuevos == 1


def test_a_changed_opening_date_is_counted_and_the_same_row_reformatted_is_not(
    db_session: Session, run, tmp_path
) -> None:
    row = _rows()[0]
    assert run(_write(tmp_path / "a.csv", [row])).nuevos == 1
    reformatted = {
        **row,
        "Fecha_de_Apertura": "16/3/2017 2:00:00 p. m.",
        "Fecha_de_Publicacion": "3/3/2017 08:00:00 p.m.",
        "Monto_Estimado": "1735400",
        "Nombre_del_Proceso": " ".join(row["Nombre_del_Proceso"].split()) + " ",
        "Objeto_del_Proceso": " ".join(row["Objeto_del_Proceso"].split()) + " ",
    }
    again = run(_write(tmp_path / "b.csv", [dict(reversed(list(reformatted.items())))]))
    assert (again.existentes, again.changed) == (1, 0)
    moved = run(_write(tmp_path / "c.csv", [{**row, "Fecha_de_Apertura": "20/03/2017 02:00:00 p.m."}]))
    assert (moved.existentes, moved.changed) == (1, 1)
    assert _stored(db_session, row["Numero_Proceso"]).metadata_["opening_date"] == "2017-03-16T14:00:00"


def test_a_stored_tender_gets_its_date_when_its_row_is_read_again(db_session: Session, run, tmp_path) -> None:
    row = _rows()[0]
    run(_write(tmp_path / "a.csv", [row]))
    stored = _stored(db_session, row["Numero_Proceso"])
    stored.metadata_ = {k: v for k, v in stored.metadata_.items() if k != "opening_date"}
    db_session.commit()
    again = run(_write(tmp_path / "a.csv", [row]))
    assert (again.existentes, again.changed) == (1, 0)
    assert _stored(db_session, row["Numero_Proceso"]).metadata_["opening_date"] == "2017-03-16T14:00:00"
