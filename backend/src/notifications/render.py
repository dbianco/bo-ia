"""The emails. Everything that comes from a document, a subscription or the
configuration is text from outside: it is escaped in the HTML version, and only
web addresses become links."""
from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from src.db.models import EvaluacionMatch, Suscripcion
from src.notifications.explain import Explanation, explain
from src.notifications.links import pause_token
from src.notifications.settings import NotificationSettings

EXCERPTS_PER_SUBSCRIPTION = 20  # in a digest; the rest are listed with their title and link
SUBJECT_LENGTH = 120


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


def _line(text: str, limit: int | None = None) -> str:
    text = " ".join(text.split())
    return text if limit is None or len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _is_web(url: str) -> bool:
    return url.startswith(("https://", "http://")) and not any(c.isspace() for c in url)


def _pause_url(settings: NotificationSettings, subscription: Suscripcion, now: datetime.datetime) -> str | None:
    if not settings.has_links:
        return None
    token = pause_token(settings.link_secret, subscription.id, now=now)
    return f"{settings.public_url}/pausar?token={token}"


def _facts(settings: NotificationSettings, e: Explanation) -> list[str]:
    facts = [e.citation] if e.citation else []
    facts.append(f"Fecha: {e.date:%d/%m/%Y}")
    facts.append(f"Similitud: {e.score:.2f}".replace(".", ","))
    facts += [f"{settings.filter_labels.get(key, key)}: {value}" for key, value in e.filters.items()]
    return facts


def _reason(e: Explanation) -> str:
    if e.shared_words:
        return f"Palabras en común: {', '.join(e.shared_words)}"
    return "Coincide por su significado: no comparte palabras con tu búsqueda."


def _item_text(settings: NotificationSettings, e: Explanation, *, full: bool) -> str:
    lines = [_line(e.title), *([_line(" · ".join(_facts(settings, e)))] if full else [])]
    if full:
        lines += [f"«{_line(e.excerpt)}»", _line(_reason(e))]
    if _is_web(e.url):
        lines.append(e.url)
    return "\n".join(lines)


def _item_html(settings: NotificationSettings, e: Explanation, *, full: bool) -> str:
    title = escape(_line(e.title))
    if _is_web(e.url):
        title = f'<a href="{escape(e.url)}">{title}</a>'
    if not full:
        return f"<li>{title}</li>"
    excerpt = "".join(f"<mark>{escape(p.text)}</mark>" if p.match else escape(p.text) for p in e.parts)
    return (
        f"<li><p><strong>{title}</strong><br>{escape(' · '.join(_facts(settings, e)))}</p>"
        f"<blockquote>{excerpt}</blockquote><p><small>{escape(_reason(e))}</small></p></li>"
    )


def _page(settings: NotificationSettings, body: str) -> str:
    return (
        f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{escape(settings.installation)}</title>'
        f"</head><body>{body}<hr><p><small>{escape(settings.installation)}</small></p></body></html>"
    )


def render_alert(settings: NotificationSettings, match: EvaluacionMatch, now: datetime.datetime) -> Rendered:
    """One match, of an immediate subscription."""
    e = explain(match)
    subscription = match.suscripcion
    query = _line(subscription.texto_busqueda)
    pause = _pause_url(settings, subscription, now)
    intro = "Hay un documento nuevo que coincide con tu suscripción"
    text = f"{intro} «{query}»:\n\n{_item_text(settings, e, full=True)}\n"
    html = f"<p>{intro} <strong>{escape(query)}</strong>:</p><ul>{_item_html(settings, e, full=True)}</ul>"
    if pause:
        text += f"\nPausar esta suscripción: {pause}\n"
        html += f'<p><a href="{escape(pause)}">Pausar esta suscripción</a></p>'
    subject = _line(f"Nuevo documento para tu suscripción: {query}", SUBJECT_LENGTH)
    return Rendered(subject, text, _page(settings, html))


def render_digest(
    settings: NotificationSettings, frequency: str, matches: Sequence[EvaluacionMatch], now: datetime.datetime
) -> Rendered:
    """All the matches of a user in a period, by subscription, the best first."""
    groups: dict[int, list[EvaluacionMatch]] = {}
    for match in matches:
        groups.setdefault(match.suscripcion_id, []).append(match)
    period = {"daily": "diario", "weekly": "semanal"}[frequency]
    count = f"{len(matches)} documento nuevo" if len(matches) == 1 else f"{len(matches)} documentos nuevos"
    texts, htmls = [f"Resumen {period}: {count}."], [f"<p>Resumen {period}: {count}.</p>"]
    for _, own in sorted(groups.items()):
        own.sort(key=lambda m: (-m.score, -m.documento.fecha.toordinal(), m.id))
        subscription = own[0].suscripcion
        query = _line(subscription.texto_busqueda)
        items = [(explain(m), i < EXCERPTS_PER_SUBSCRIPTION) for i, m in enumerate(own)]
        texts.append(f"\n== {query} ==\n")
        texts += [_item_text(settings, e, full=full) + "\n" for e, full in items]
        listed = "".join(_item_html(settings, e, full=full) for e, full in items)
        htmls.append(f"<h2>{escape(query)}</h2><ul>{listed}</ul>")
        pause = _pause_url(settings, subscription, now)
        if pause:
            texts.append(f"Pausar esta suscripción: {pause}")
            htmls.append(f'<p><a href="{escape(pause)}">Pausar esta suscripción</a></p>')
    subject = _line(f"{settings.installation}: resumen {period}, {count}", SUBJECT_LENGTH)
    return Rendered(subject, "\n".join(texts) + "\n", _page(settings, "".join(htmls)))
