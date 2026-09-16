"""Modelos SQLAlchemy del MVP (ver sección 7 del design spec).

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
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024  # dimensión de salida de Qwen/Qwen3-Embedding-0.6B

ORIGENES_TAG = ("manual", "modelo", "sugerido")
VALORES_FEEDBACK = ("positivo", "negativo")


class Base(DeclarativeBase):
    pass


class Boletin(Base):
    __tablename__ = "boletines"

    id: Mapped[int] = mapped_column(primary_key=True)
    jurisdiccion: Mapped[str] = mapped_column(String(64), nullable=False)
    identificador_oficial: Mapped[str] = mapped_column(String(128), nullable=False)
    fecha_publicacion: Mapped[datetime.date] = mapped_column(nullable=False)
    titulo: Mapped[str | None] = mapped_column(Text, nullable=True)
    texto_original: Mapped[str] = mapped_column(Text, nullable=False)
    url_oficial: Mapped[str] = mapped_column(Text, nullable=False)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)
    estado_ingesta: Mapped[str] = mapped_column(String(32), nullable=False, server_default="completo")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    fragmentos: Mapped[list["Fragmento"]] = relationship(
        back_populates="boletin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("jurisdiccion", "identificador_oficial", name="uq_boletin_identificador"),
        UniqueConstraint("hash_contenido", name="uq_boletin_hash_contenido"),
    )


class Fragmento(Base):
    __tablename__ = "fragmentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    boletin_id: Mapped[int] = mapped_column(ForeignKey("boletines.id", ondelete="CASCADE"), nullable=False)
    posicion: Mapped[int] = mapped_column(nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    # Denormalizada desde boletines.fecha_publicacion: REQ-05 exige que cada
    # fragmento la conserve, y el filtro de fecha de REQ-09 la necesita sin
    # tener que hacer join contra boletines en cada búsqueda.
    fecha_publicacion: Mapped[datetime.date] = mapped_column(nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    boletin: Mapped["Boletin"] = relationship(back_populates="fragmentos")
    tags: Mapped[list["FragmentoTag"]] = relationship(back_populates="fragmento", cascade="all, delete-orphan")
    valoraciones: Mapped[list["Valoracion"]] = relationship(
        back_populates="fragmento", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("boletin_id", "posicion", name="uq_fragmento_boletin_posicion"),
        Index("ix_fragmentos_fecha_publicacion", "fecha_publicacion"),
        # Coincide con el índice creado a mano en la migración fa9cc1623dda
        # (sa.execute CREATE INDEX ... USING hnsw): declarado acá también
        # para que `alembic check` no lo marque como drift.
        Index(
            "ix_fragmentos_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
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

    fragmento: Mapped["Fragmento"] = relationship(back_populates="tags")
    tag: Mapped["Tag"] = relationship()

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

    fragmento: Mapped["Fragmento"] = relationship(back_populates="valoraciones")

    __table_args__ = (
        CheckConstraint(f"valor IN {VALORES_FEEDBACK}", name="ck_valoracion_valor"),
    )
