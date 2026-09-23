"""Contrato común de ingesta (sección 8 del design spec, Etapa 1).

`DocumentoNormalizado` es lo que cualquier conector específico (hoy, el
adaptador del Boletín en `src/ingestor/adapters/`) debe producir. La
función `ingerir_documento` es el único punto que persiste, fragmenta y
genera embeddings — reemplaza la lógica que antes estaba duplicada entre
`src/api/ingest.py` y `src/seed/seed.py` (FR-002).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Documento, Fragmento, Fuente
from src.ingestor.fragmenter import fragmentar_texto
from src.processor.embeddings import EmbeddingProvider


class DocumentoInvalido(ValueError):
    """El documento recibido no tiene los campos obligatorios (FR-001)."""


class ErrorDeProcesamiento(RuntimeError):
    """Fragmentar o generar embeddings falló; el documento ya quedó
    persistido con `estado="error"` (FR-003, FR-006)."""


@dataclass
class DocumentoNormalizado:
    fuente_clave: str
    identificador_externo: str
    fecha: date
    texto: str
    url_fuente: str
    titulo: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ResultadoIngesta:
    documento: Documento
    ya_existia: bool
    fragmentos_creados: int


def _validar(doc: DocumentoNormalizado) -> None:
    faltantes = [
        nombre
        for nombre, valor in (
            ("fuente_clave", doc.fuente_clave),
            ("identificador_externo", doc.identificador_externo),
            ("texto", doc.texto),
            ("url_fuente", doc.url_fuente),
        )
        if not valor or not valor.strip()
    ]
    if doc.fecha is None:
        faltantes.append("fecha")
    if faltantes:
        raise DocumentoInvalido(f"Campos obligatorios faltantes: {', '.join(faltantes)}")


def _hash_contenido(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _resolver_fuente(session: Session, clave: str) -> Fuente:
    """Get-or-create por `clave`. `installation.yaml` hace upsert de las
    fuentes declaradas al arrancar (FR-008); esto cubre además cualquier
    fuente que llegue por fuera de esa configuración."""
    fuente = session.scalar(select(Fuente).where(Fuente.clave == clave))
    if fuente is None:
        fuente = Fuente(clave=clave, nombre=clave, config={})
        session.add(fuente)
        session.flush()
    return fuente


def ingerir_documento(
    session: Session,
    embedder: EmbeddingProvider,
    doc: DocumentoNormalizado,
    *,
    tamano_fragmento: int = 1000,
    solapamiento_fragmento: int = 200,
) -> ResultadoIngesta:
    """Persiste el documento si no existe, lo fragmenta y genera sus
    embeddings. Idempotente por (fuente, identificador_externo) y por
    hash_contenido (FR-002).

    El documento se commitea apenas se valida, antes de fragmentar: así,
    si la fragmentación o el embedding fallan, el documento ya recibido no
    se pierde (FR-003, FR-006) — solo queda marcado con estado="error".
    """
    _validar(doc)
    fuente = _resolver_fuente(session, doc.fuente_clave)
    hash_contenido = _hash_contenido(doc.texto)

    existente = session.scalar(
        select(Documento).where(
            (Documento.fuente_id == fuente.id)
            & (Documento.identificador_externo == doc.identificador_externo)
        )
    )
    if existente is None:
        existente = session.scalar(select(Documento).where(Documento.hash_contenido == hash_contenido))

    if existente is not None:
        fragmentos_existentes = session.scalar(
            select(func.count()).select_from(Fragmento).where(Fragmento.documento_id == existente.id)
        )
        return ResultadoIngesta(documento=existente, ya_existia=True, fragmentos_creados=fragmentos_existentes)

    documento = Documento(
        fuente_id=fuente.id,
        identificador_externo=doc.identificador_externo,
        fecha=doc.fecha,
        titulo=doc.titulo,
        texto=doc.texto,
        url_fuente=doc.url_fuente,
        hash_contenido=hash_contenido,
        estado="pendiente",
        metadata_=doc.metadata,
    )
    session.add(documento)
    session.flush()
    session.commit()  # el documento ya queda persistido, independiente de lo que pase después

    try:
        textos = fragmentar_texto(doc.texto, tamano=tamano_fragmento, solapamiento=solapamiento_fragmento)
        if not textos:
            # No debería pasar (fragmentar_texto garantiza >=1 para texto no
            # vacío), pero FR-007 (del MVP original) se verifica igual.
            raise RuntimeError("La fragmentación no produjo ningún fragmento")

        for posicion, texto in enumerate(textos):
            embedding = embedder.embed_passage(texto)
            session.add(
                Fragmento(
                    documento_id=documento.id,
                    posicion=posicion,
                    texto=texto,
                    fecha=documento.fecha,
                    embedding=embedding,
                )
            )
        documento.estado = "completo"
        session.commit()
    except Exception as exc:
        session.rollback()  # descarta fragmentos parcialmente insertados
        documento.estado = "error"
        session.commit()  # FR-003/FR-006: el error queda registrado sin perder el documento
        raise ErrorDeProcesamiento(
            "Error al fragmentar o generar embeddings; el documento quedó registrado con estado 'error'."
        ) from exc

    return ResultadoIngesta(documento=documento, ya_existia=False, fragmentos_creados=len(textos))
