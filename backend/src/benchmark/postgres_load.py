"""Loads a corpus into a scratch database without the ingestion path, which is
too slow for a million fragments. For benchmarks only."""
from __future__ import annotations

import time

import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from src.benchmark.systems import embed_passages
from src.ingestor.contract import DocumentoNormalizado
from src.ingestor.fragmenter import fragmentar_texto
from src.processor.embeddings import EmbeddingProvider

MEMORY = "5GB"


CHUNK = 2_000  # documents


def bulk_load(url: str, documents: list[DocumentoNormalizado], provider: EmbeddingProvider) -> tuple[int, float]:
    """Returns how many fragments there are and the seconds it took, with the
    embedding and the indexes."""
    start = time.perf_counter()
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as conn:
        register_vector(conn)
        indexes = conn.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'fragmentos' AND "
            "indexname IN ('ix_fragmentos_embedding_hnsw', 'ix_fragmentos_texto_tsv_gin')"
        ).fetchall()
        for name, _ in indexes:
            conn.execute(f"DROP INDEX {name}")
        conn.execute("ALTER TABLE fragmentos DISABLE TRIGGER USER")
        conn.execute("INSERT INTO fuentes (id, clave, nombre) VALUES (1, 'benchmark', 'benchmark')")
        with conn.cursor().copy(
            "COPY documentos (id, fuente_id, identificador_externo, fecha, titulo, texto, url_fuente, hash_contenido, "
            "metadata) FROM STDIN"
        ) as copy:
            for i, d in enumerate(documents, start=1):
                copy.write_row(
                    (i, 1, d.identificador_externo, d.fecha, d.titulo, d.texto, d.url_fuente, str(i), Jsonb(d.metadata))
                )
        row = 0
        with conn.cursor().copy(
            "COPY fragmentos (id, documento_id, posicion, texto, fecha, embedding) FROM STDIN WITH (FORMAT BINARY)"
        ) as copy:
            copy.set_types(["int4", "int4", "int4", "text", "date", "vector"])
            for start_at in range(0, len(documents), CHUNK):
                chunk = documents[start_at : start_at + CHUNK]
                texts = [fragmentar_texto(d.texto) for d in chunk]
                vectors = iter(embed_passages(provider, [t for own in texts for t in own]))
                for i, (d, own) in enumerate(zip(chunk, texts, strict=True), start=start_at + 1):
                    for position, text in enumerate(own):
                        row += 1
                        copy.write_row((row, i, position, text, d.fecha, next(vectors)))
        conn.execute("ALTER TABLE fragmentos ENABLE TRIGGER USER")
        conn.execute(f"SET maintenance_work_mem = '{MEMORY}'")
        conn.execute("SET max_parallel_maintenance_workers = 3")
        for _, definition in indexes:
            conn.execute(definition)
        conn.execute("ANALYZE")
    return row, round(time.perf_counter() - start, 1)
