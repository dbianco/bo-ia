"""Traduce filtros declarados por instalación a condiciones SQL sobre
`documentos.metadata` (sección 8 del design spec, FR-009, FR-012, FR-013).

Módulo puro: no importa FastAPI ni abre sesiones, para que la Etapa 3 lo
reutilice desde suscripciones sin acoplarse a la capa HTTP.
"""
from __future__ import annotations

from sqlalchemy import Numeric, Select, cast, literal
from sqlalchemy.dialects.postgresql import JSONB

from src.config.installation import Filtro, FiltroRangoNumerico, FiltroSeleccion
from src.db.models import Documento


class FiltroNoDeclarado(ValueError):
    """La clave de filtro solicitada no está declarada en
    `installation.yaml` (FR-012)."""


class ValorDeFiltroInvalido(ValueError):
    """El valor recibido para un filtro de rango numérico no es válido."""


def _condicion_seleccion(filtro: FiltroSeleccion, valor: str):
    # `literal(..., type_=JSONB)` (no `cast(json.dumps(...), JSONB)`): el
    # bind processor de JSONB serializa el dict una sola vez. Castear un
    # string ya serializado lo vuelve a serializar (doble encoding) y el
    # operador `@>` nunca matchea.
    return Documento.metadata_.op("@>")(literal({filtro.clave: valor}, type_=JSONB))


def _condiciones_rango(filtro: FiltroRangoNumerico, valor: str) -> list:
    """`valor` tiene forma "min,max"; cualquiera de los dos lados puede
    quedar vacío (p. ej. "100000," o ",500000")."""
    minimo_str, _, maximo_str = valor.partition(",")
    columna = cast(Documento.metadata_[filtro.clave].astext, Numeric)
    condiciones = []
    if minimo_str:
        try:
            condiciones.append(columna >= float(minimo_str))
        except ValueError as exc:
            raise ValorDeFiltroInvalido(
                f"Valor mínimo inválido para '{filtro.clave}': {minimo_str!r}"
            ) from exc
    if maximo_str:
        try:
            condiciones.append(columna <= float(maximo_str))
        except ValueError as exc:
            raise ValorDeFiltroInvalido(
                f"Valor máximo inválido para '{filtro.clave}': {maximo_str!r}"
            ) from exc
    return condiciones


def aplicar_filtros(
    stmt: Select, filtros_solicitados: dict[str, str], filtros_declarados: list[Filtro]
) -> Select:
    """Agrega a `stmt` una condición por cada filtro solicitado, validado
    contra los filtros declarados por la instalación."""
    declarados = {f.clave: f for f in filtros_declarados}
    for clave, valor in filtros_solicitados.items():
        filtro = declarados.get(clave)
        if filtro is None:
            raise FiltroNoDeclarado(clave)
        if isinstance(filtro, FiltroSeleccion):
            stmt = stmt.where(_condicion_seleccion(filtro, valor))
        else:
            for condicion in _condiciones_rango(filtro, valor):
                stmt = stmt.where(condicion)
    return stmt
