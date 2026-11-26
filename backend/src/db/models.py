"""Modelos SQLAlchemy (Etapa 1: núcleo genérico, ver sección 8 del design
spec `docs/design/2026-09-18-plataforma-tematica-reutilizable-design.md`).

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
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    case,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column, relationship

EMBEDDING_DIM = 1024  # dimensión de salida de Qwen/Qwen3-Embedding-0.6B

ORIGENES_TAG = ("manual", "modelo", "sugerido")
VALORES_FEEDBACK = ("positivo", "negativo")

# States of a document besides "pendiente", "completo" and "error".
NOT_SEARCHABLE = "not_searchable"  # kept for completeness, without fragments (the cover of an issue)
SUPERSEDED = "superseded"  # replaced by the notices it contained; kept for its history


class Base(DeclarativeBase):
    pass


# The transaction that last changed a row. An index in memory asks for the rows
# of the transactions that had not finished when it last looked, so it does not
# miss a change that commits late. Kept up to date by a trigger.
CURRENT_TRANSACTION = text("pg_current_xact_id()::text::bigint")


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
    # Also moves when one of its fragments changes.
    changed_xid: Mapped[int] = mapped_column(BigInteger, server_default=CURRENT_TRANSACTION, nullable=False)
    # Where to find the document in the publication it came in. `issue` is
    # shared by everything printed in one issue (one PDF, for instance); the
    # number is the official one within it. A document with an issue and no
    # number is text that could not be attributed to any notice.
    issue: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notice_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_page: Mapped[int | None] = mapped_column(nullable=True)
    last_page: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    fuente: Mapped[Fuente] = relationship(back_populates="documentos")
    fragmentos: Mapped[list[Fragmento]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("fuente_id", "identificador_externo", name="uq_documento_fuente_identificador"),
        # With the date: the same notice is published on consecutive days with
        # identical text, and each publication is a document.
        UniqueConstraint("hash_contenido", "fecha", name="uq_documento_hash_contenido_fecha"),
        Index("ix_documentos_fuente_id_issue", "fuente_id", "issue"),
        Index("ix_documentos_changed_xid", "changed_xid"),
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
    page: Mapped[int | None] = mapped_column(nullable=True)  # where the fragment starts
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


class Usuario(Base):
    """Un cliente de la instalación (Etapa 3, sección 3.2 del design spec).
    Multiusuario dentro de una instalación, sin organizaciones ni roles
    jerárquicos todavía."""

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sesiones: Mapped[list[Sesion]] = relationship(back_populates="usuario", cascade="all, delete-orphan")
    suscripciones: Mapped[list[Suscripcion]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )


class Sesion(Base):
    """Una sesión de login activa. El token es opaco; toda la validación
    (existencia, expiración) pasa por esta tabla, no por un JWT."""

    __tablename__ = "sesiones"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    expira_en: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    usuario: Mapped[Usuario] = relationship(back_populates="sesiones")


ESTADOS_SUSCRIPCION = ("activa", "pausada")


class Suscripcion(Base):
    """Una consulta persistente de un usuario (sección 4.5 del design
    spec). `filtros` es un snapshot autocontenido (clave -> {tipo, valor}),
    no una referencia a `installation.yaml`: se evalúa igual aunque la
    instalación cambie sus filtros declarados después de crearla.

    `canales` y `frecuencia_notificacion` están contemplados en el modelo
    de datos de la sección 4.5, pero sin lógica de envío — eso es la
    Etapa 4."""

    __tablename__ = "suscripciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    texto_busqueda: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    filtros: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    estado: Mapped[str] = mapped_column(String(16), nullable=False, server_default="activa")
    canales: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    frecuencia_notificacion: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Last evaluation before it was paused. Read `ultima_evaluacion`, below,
    # which also knows about an active subscription without writing to its row.
    ultima_evaluacion_guardada: Mapped[datetime.datetime | None] = mapped_column(
        "ultima_evaluacion", DateTime(timezone=True), nullable=True
    )
    active_since: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
    changed_xid: Mapped[int] = mapped_column(BigInteger, server_default=CURRENT_TRANSACTION, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    usuario: Mapped[Usuario] = relationship(back_populates="suscripciones")
    matches: Mapped[list[EvaluacionMatch]] = relationship(
        back_populates="suscripcion", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(f"estado IN {ESTADOS_SUSCRIPCION}", name="ck_suscripcion_estado"),
        Index("ix_suscripciones_changed_xid", "changed_xid"),
    )


class MatchingState(Base):
    """One row: when a document was last matched. Matching considers every
    active subscription, so this is when all of them were last evaluated."""

    __tablename__ = "matching_state"

    id: Mapped[int] = mapped_column(primary_key=True, server_default="1")
    last_run_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (CheckConstraint("id = 1", name="ck_matching_state_one_row"),)


_last_run_at = select(MatchingState.last_run_at).scalar_subquery()
Suscripcion.ultima_evaluacion = column_property(
    case(
        (
            (Suscripcion.estado == "activa") & (_last_run_at >= Suscripcion.active_since),
            _last_run_at,
        ),
        else_=Suscripcion.ultima_evaluacion_guardada,
    )
)


class MatchingQueue(Base):
    """Documents waiting to be matched. The row is written in the transaction
    that completes the document, so a crash loses none."""

    __tablename__ = "matching_queue"

    documento_id: Mapped[int] = mapped_column(
        ForeignKey("documentos.id", ondelete="CASCADE"), primary_key=True
    )
    enqueued_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Also the lease: a worker that takes a document moves it to the future.
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_matching_queue_next_attempt_at", "next_attempt_at"),)


class EvaluacionMatch(Base):
    """Evidencia de que un documento matcheó una suscripción (sección 4.5
    del design spec): documento, suscripción, score, filtros aplicados y
    fecha de evaluación. A lo sumo un match por par (documento,
    suscripción)."""

    __tablename__ = "evaluaciones_match"

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("documentos.id", ondelete="CASCADE"), nullable=False)
    suscripcion_id: Mapped[int] = mapped_column(
        ForeignKey("suscripciones.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(nullable=False)
    filtros_aplicados: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    fecha_evaluacion: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    documento: Mapped[Documento] = relationship()
    suscripcion: Mapped[Suscripcion] = relationship(back_populates="matches")
    entregas: Mapped[list[EntregaNotificacion]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "documento_id", "suscripcion_id", name="uq_evaluacion_match_documento_suscripcion"
        ),
    )


ESTADOS_ENTREGA = ("pendiente", "entregada", "fallida")
CANALES_NOTIFICACION = ("bandeja", "correo")


class EntregaNotificacion(Base):
    """Un intento de notificar un match por un canal (sección 4.6 del
    design spec, Etapa 4): a lo sumo una entrega por par (match, canal).
    `reintentos` queda en el modelo para un reintento manual futuro; en
    esta etapa nada lo incrementa todavía (no hay reintento automático,
    ver `spec.md`)."""

    __tablename__ = "entregas_notificacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("evaluaciones_match.id", ondelete="CASCADE"), nullable=False
    )
    canal: Mapped[str] = mapped_column(String(16), nullable=False)
    estado: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pendiente")
    fecha_intento: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reintentos: Mapped[int] = mapped_column(nullable=False, server_default="0")
    error_proveedor: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    match: Mapped[EvaluacionMatch] = relationship(back_populates="entregas")

    __table_args__ = (
        CheckConstraint(f"canal IN {CANALES_NOTIFICACION}", name="ck_entrega_notificacion_canal"),
        CheckConstraint(f"estado IN {ESTADOS_ENTREGA}", name="ck_entrega_notificacion_estado"),
        UniqueConstraint("match_id", "canal", name="uq_entrega_notificacion_match_canal"),
    )
