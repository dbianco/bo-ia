"""Evalúa un documento contra las suscripciones activas (sección 4.5 del
design spec, FR-012 a FR-017), en el momento y en la sesión del llamador.

Ingestion does not call it: it leaves the document in the matching queue (see
`src/matching/queue.py`), which does the same in the background with the
matcher that `MATCHING_ENGINE` selects."""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.db.models import Documento
from src.matching.matchers import Matcher, SqlLoopMatcher
from src.matching.queue import match_document


def evaluar_documento(session: Session, documento: Documento, matcher: Matcher | None = None) -> None:
    """Para cada suscripción activa cuyo filtro cumpla la metadata del
    documento (FR-013) y cuya mejor similitud con sus fragmentos supere el
    umbral (FR-014), registra un `EvaluacionMatch` (a lo sumo uno por par
    documento/suscripción, FR-015) y sus entregas. `ultima_evaluacion` avanza
    para todas las activas, matcheen o no (FR-016). Una suscripción pausada no
    se toca (FR-017)."""
    match_document(session, documento, matcher or SqlLoopMatcher())
