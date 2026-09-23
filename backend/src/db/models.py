"""Modelos SQLAlchemy (Etapa 1: núcleo genérico, ver sección 8 del design
spec `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md`).

Los tags a nivel de documento no tienen tabla propia: se derivan de la
unión de los tags de sus fragmentos (`fragmento_tags`). `origen` y `valor`
se guardan como texto con un CHECK constraint en vez de un ENUM nativo de
Postgres, para no tener que lidiar con ALTER TYPE en migraciones futuras
cuando cambien los valores permitidos.
"""
from __future__ import annotations

import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024  # dimensión de salida de Qwen/Qwen3-Embedding-0.6B

ORIGENES_TAG = ("manual", "modelo", "sugerido")
VALORES_FEEDBACK = ("positivo", "negativo")


class Base(DeclarativeBase):
    pass


class Fuente(Base):
    """Una fuente concreta dentro de una instalación (p. ej. un boletín
    provincial o municipal). Reemplaza al string libre `jurisdiccion` del
    MVP original."""

    __tablename__ = "fuentes"

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(256), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    documentos: Mapped[list[Documento]] = relationship(back_populates="fuente")
    ejecuciones: Mapped[list[EjecucionFuente]] = relationship(back_populates="fuente")


ESTADOS_EJECUCION = ("en_curso", "completada", "fallida")


class EjecucionFuente(Base):
    """Una corrida de un conector sobre una fuente (Etapa 2, sección 4.4
    del design spec). Registra qué encontró y qué falló, sin depender de
    revisar logs."""

    __tablename__ = "ejecuciones_fuente"

    id: Mapped[int] = mapped_column(primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuentes.id"), nullable=False)
    inicio: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fin: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estado: Mapped[str] = mapped_column(String(32), nullable=False)
    descubiertos: Mapped[int] = mapped_column(nullable=False, server_default="0")
    nuevos: Mapped[int] = mapped_column(nullable=False, server_default="0")
    existentes: Mapped[int] = mapped_column(nullable=False, server_default="0")
    errores: Mapped[int] = mapped_column(nullable=False, server_default="0")
    version_conector: Mapped[str] = mapped_column(String(64), nullable=False)
    # Lista de {"identificador_externo": str | None, "error": str}, una por
    # documento que falló dentro de esta ejecución.
    detalle_errores: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    fuente: Mapped[Fuente] = relationship(back_populates="ejecuciones")

    __table_args__ = (
        CheckConstraint(f"estado IN {ESTADOS_EJECUCION}", name="ck_ejecucion_fuente_estado"),
        Index("ix_ejecuciones_fuente_fuente_id_inicio", "fuente_id", "inicio"),
    )


class Documento(Base):
    __tablename__ = "documentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuentes.id"), nullable=False)
    identificador_externo: Mapped[str] = mapped_column(String(128), nullable=False)
    fecha: Mapped[datetime.date] = mapped_column(nullable=False)
    titulo: Mapped[str | None] = mapped_column(Text, nullable=True)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    url_fuente: Mapped[str] = mapped_column(Text, nullable=False)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)
    estado: Mapped[str] = mapped_column(String(32), nullable=False, server_default="completo")
    # Metadatos específicos de la vertical/instalación (provincia, municipio,
    # organismo, rubro, ...). JSONB + índice GIN para que los filtros
    # declarados por instalación (`aplicar_filtros`) usen el operador `@>`.
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    version_ingesta: Mapped[str] = mapped_column(String(32), nullable=False, server_default="v1")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    fuente: Mapped[Fuente] = relationship(back_populates="documentos")
    fragmentos: Mapped[list[Fragmento]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("fuente_id", "identificador_externo", name="uq_documento_fuente_identificador"),
        UniqueConstraint("hash_contenido", name="uq_documento_hash_contenido"),
        Index("ix_documentos_metadata_gin", "metadata", postgresql_using="gin"),
    )


class Fragmento(Base):
    __tablename__ = "fragmentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(
        ForeignKey("documentos.id", ondelete="CASCADE"), nullable=False
    )
    posicion: Mapped[int] = mapped_column(nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    # Denormalizada desde documentos.fecha: cada fragmento la conserve, y el
    # filtro de fecha de la búsqueda la necesita sin tener que hacer join
    # contra documentos en cada búsqueda.
    fecha: Mapped[datetime.date] = mapped_column(nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    # Búsqueda de texto completo en español (modos HYBRID/ALL). Columna
    # generada: Postgres la mantiene sola, no se escribe desde la app.
    texto_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('spanish', texto)", persisted=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    documento: Mapped[Documento] = relationship(back_populates="fragmentos")
    tags: Mapped[list[FragmentoTag]] = relationship(back_populates="fragmento", cascade="all, delete-orphan")
    valoraciones: Mapped[list[Valoracion]] = relationship(
        back_populates="fragmento", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("documento_id", "posicion", name="uq_fragmento_documento_posicion"),
        Index("ix_fragmentos_fecha", "fecha"),
        # Coincide con el índice creado a mano en la migración (sa.execute
        # CREATE INDEX ... USING hnsw): declarado acá también para que
        # `alembic check` no lo marque como drift.
        Index(
            "ix_fragmentos_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_fragmentos_texto_tsv_gin", "texto_tsv", postgresql_using="gin"),
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(128), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    activo: Mapped[bool] = mapped_column(nullable=False, server_default="true")


class FragmentoTag(Base):
    __tablename__ = "fragmento_tags"

    fragmento_id: Mapped[int] = mapped_column(
        ForeignKey("fragmentos.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    origen: Mapped[str] = mapped_column(String(16), nullable=False)
    confianza: Mapped[float | None] = mapped_column(nullable=True)
    modelo_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revisado_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    fragmento: Mapped[Fragmento] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship()

    __table_args__ = (
        CheckConstraint(f"origen IN {ORIGENES_TAG}", name="ck_fragmento_tag_origen"),
        CheckConstraint(
            "confianza IS NULL OR (confianza >= 0 AND confianza <= 1)",
            name="ck_fragmento_tag_confianza_rango",
        ),
    )


class Valoracion(Base):
    __tablename__ = "valoraciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    fragmento_id: Mapped[int] = mapped_column(ForeignKey("fragmentos.id", ondelete="CASCADE"), nullable=False)
    consulta: Mapped[str] = mapped_column(Text, nullable=False)
    valor: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    fragmento: Mapped[Fragmento] = relationship(back_populates="valoraciones")

    __table_args__ = (
        CheckConstraint(f"valor IN {VALORES_FEEDBACK}", name="ck_valoracion_valor"),
    )
