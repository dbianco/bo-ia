import datetime
import itertools

import pytest
from sqlalchemy.orm import Session

from src.db.models import Documento, EvaluacionMatch, Fragmento, Fuente, Suscripcion, Usuario
from src.notifications.dispatcher import crear_entregas_para_match
from src.notifications.settings import NotificationSettings
from tests.notifications.fake_smtp import FakeSMTP

T0 = datetime.datetime(2026, 6, 3, 12, 0, tzinfo=datetime.UTC)  # a Wednesday
SECRET = "secret-for-links"


class Clock:
    def __init__(self, now: datetime.datetime = T0) -> None:
        self.now = now

    def __call__(self, session: Session) -> datetime.datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += datetime.timedelta(**delta)


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def smtp(monkeypatch):
    server = FakeSMTP()
    server.start()
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(server.port))
    monkeypatch.setenv("SMTP_SECURITY", "none")
    monkeypatch.setenv("SMTP_FROM", "avisos@contextcrawl.local")
    for name in ("SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    yield server
    server.stop()


@pytest.fixture()
def settings() -> NotificationSettings:
    return NotificationSettings(
        installation="Boletines de prueba",
        filter_labels={"provincia": "Provincia"},
        timezone="America/Argentina/Cordoba",
        digest_hour=7,
        public_url="https://alerts.example.org",
        link_secret=SECRET,
        max_retries=5,
    )


@pytest.fixture()
def make(db_session: Session):
    """Writes users, subscriptions, documents and matches (with their deliveries)."""
    numbers = itertools.count(1)

    class Make:
        def user(self, address: str | None = None) -> Usuario:
            user = Usuario(email=address or f"u{next(numbers)}@example.org", password_hash="x")
            db_session.add(user)
            db_session.commit()
            return user

        def subscription(
            self, user: Usuario | None = None, text: str = "pavimentación de calles", frequency: str = "immediate",
            channels=("bandeja", "correo"), filters=None,
        ) -> Suscripcion:  # fmt: skip
            subscription = Suscripcion(
                usuario_id=(user or self.user()).id, texto_busqueda=text, embedding=[1.0] + [0.0] * 1023,
                filtros=filters or {}, canales=list(channels), frecuencia_notificacion=frequency,
            )  # fmt: skip
            db_session.add(subscription)
            db_session.commit()
            return subscription

        def document(self, text: str = "Licitación para la pavimentación de calles.", **fields) -> Documento:
            source = db_session.query(Fuente).first()
            if source is None:
                source = Fuente(clave="f", nombre="f", config={})
                db_session.add(source)
                db_session.flush()
            n = next(numbers)
            values = dict(
                fuente_id=source.id, identificador_externo=f"d{n}", fecha=datetime.date(2026, 6, 1), texto=text,
                titulo=f"Documento {n}", url_fuente=f"https://example.org/{n}.pdf#page=3", hash_contenido=f"h{n}",
                estado="completo", metadata_={},
            )  # fmt: skip
            document = Documento(**{**values, **fields})
            db_session.add(document)
            db_session.flush()
            db_session.add(
                Fragmento(documento_id=document.id, posicion=0, texto=text, fecha=document.fecha, page=3)
            )
            db_session.commit()
            return document

        def match(
            self, subscription: Suscripcion, document: Documento | None = None, at: datetime.datetime = T0,
            score: float = 0.87,
        ) -> EvaluacionMatch:  # fmt: skip
            document = document or self.document()
            match = EvaluacionMatch(
                documento_id=document.id, suscripcion_id=subscription.id, score=score,
                filtros_aplicados=subscription.filtros, fecha_evaluacion=at, fragmento_id=document.fragmentos[0].id,
            )  # fmt: skip
            db_session.add(match)
            db_session.flush()
            crear_entregas_para_match(db_session, match, now=at)
            db_session.commit()
            return match

    return Make()
