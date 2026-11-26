"""Plan 10: the explained email, and text that comes from outside."""
import re

import pytest

from src.notifications.outbox import send_pending
from tests.notifications.conftest import SECRET

EVIL = '<script>alert("x")</script> & <img src=x onerror=alert(1)> \'"'


def _send(db_session, make, settings, clock, *, text="pavimentación de calles", filters=None, **document):
    subscription = make.subscription(make.user("cliente@example.org"), text, filters=filters)
    make.match(subscription, make.document(**document))
    assert send_pending(db_session, settings, clock=clock) == 1
    return subscription


def test_an_alert_says_what_matched_and_why(db_session, make, smtp, settings, clock) -> None:
    _send(
        db_session, make, settings, clock, filters={"provincia": {"tipo": "seleccion", "valor": "Córdoba"}},
        text="pavimentación de calles", titulo="Aviso Nº 688769 — Vialidad", notice_number="688769", first_page=4,
        last_page=5, url_fuente="https://example.org/4.pdf#page=4",
    )  # fmt: skip
    for body in (smtp.text(), smtp.html()):
        for expected in ("Aviso Nº 688769 — Vialidad", "Páginas 4 a 5", "01/06/2026", "0,87", "Provincia: Córdoba",
                         "https://example.org/4.pdf#page=4", "pavimentación de calles"):  # fmt: skip
            assert expected in body, expected
    assert "<mark>pavimentación</mark>" in smtp.html() and "<mark>calles</mark>" in smtp.html()
    assert "pavimentación, calles" in smtp.text()


def test_a_match_by_meaning_says_so_and_invents_nothing(db_session, make, smtp, settings, clock) -> None:
    subscription = make.subscription(make.user(), "combustible")
    make.match(subscription, make.document("Suministro de gasoil y nafta."))
    send_pending(db_session, settings, clock=clock)
    for body in (smtp.text(), smtp.html()):
        assert "por su significado" in body
    assert "<mark>" not in smtp.html()


def test_every_alert_carries_an_excerpt_that_is_part_of_the_document(db_session, make, smtp, settings, clock) -> None:
    plain = lambda s: " ".join(s.split())  # noqa: E731
    for i in range(8):
        text = f"Comienzo {i}.\n" + "Relleno de la resolución.\n" * 60 + f"Obra {i} de pavimentación\nde calles."
        make.match(make.subscription(make.user(), ["pavimentación", "zapatos"][i % 2]), make.document(text))
        send_pending(db_session, settings, clock=clock)
        excerpt = re.findall(r"«([^»]*)»", plain(smtp.text()))[-1]
        assert len(excerpt) > 50 and excerpt in plain(text)


def test_text_with_html_appears_as_text(db_session, make, smtp, settings, clock) -> None:
    import dataclasses

    settings = dataclasses.replace(settings, filter_labels={"provincia": f"Provincia {EVIL}"})
    subscription = make.subscription(
        make.user(), f"calle {EVIL}", filters={"provincia": {"tipo": "seleccion", "valor": EVIL}}
    )
    make.match(subscription, make.document(f"La calle {EVIL} fin", titulo=f"Título {EVIL}", notice_number="<b>1</b>"))
    send_pending(db_session, settings, clock=clock)
    html = smtp.html()
    assert "<script" not in html and "<img" not in html and "<b>1" not in html
    assert html.count("&lt;script&gt;") >= 4
    assert f"Título {EVIL}" in smtp.text()


@pytest.mark.parametrize("query", ["zapatos", "obra", f"obra {EVIL}"], ids=["by meaning", "around", "inside"])
def test_the_excerpt_is_escaped_wherever_the_shared_words_are(db_session, make, smtp, settings, clock, query) -> None:
    make.match(make.subscription(make.user(), query), make.document(f"Una obra {EVIL} y otra obra"))
    send_pending(db_session, settings, clock=clock)
    plain = re.sub("</?mark>", "", smtp.html())
    assert "&lt;script&gt;" in plain and "<script" not in plain and "<img" not in plain


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "ftp://x/y", "", "no es una url"])
def test_only_web_addresses_become_links(db_session, make, smtp, settings, clock, url) -> None:
    _send(db_session, make, settings, clock, url_fuente=url)
    hrefs = re.findall(r'href="([^"]*)"', smtp.html())
    assert hrefs and all(h.startswith("https://alerts.example.org/") for h in hrefs)


def test_a_quote_in_the_address_does_not_leave_the_attribute(db_session, make, smtp, settings, clock) -> None:
    _send(db_session, make, settings, clock, url_fuente='https://example.org/"onmouseover="alert(1)')
    assert 'onmouseover="' not in smtp.html()


@pytest.mark.parametrize("text", ["calle\nBcc: otro@example.org", "calle\r\nX: y", "x" * 1000, "  \t calle  "])
def test_the_subject_is_one_line(db_session, make, smtp, settings, clock, text) -> None:
    _send(db_session, make, settings, clock, text=text)
    subject = smtp.messages[0]["Subject"]
    assert "\n" not in subject and len(subject) < 200
    assert smtp.recipients == ["cliente@example.org"] and smtp.messages[0]["Bcc"] is None


def test_every_email_has_a_pause_link(db_session, make, smtp, settings, clock) -> None:
    from src.notifications.links import read_pause_token

    subscription = _send(db_session, make, settings, clock)
    for body in (smtp.text(), smtp.html()):
        token = re.search(r"https://alerts\.example\.org/pausar\?token=([\w.~-]+)", body).group(1)
        assert read_pause_token(SECRET, token) == subscription.id


def test_a_digest_has_a_pause_link_for_each_subscription(db_session, make, smtp, settings, clock) -> None:
    import datetime

    from src.notifications.digests import build_digests
    from src.notifications.links import read_pause_token

    user = make.user()
    subscriptions = [make.subscription(user, f"tema {i}", frequency="daily") for i in range(3)]
    for s in subscriptions:
        make.match(s)
    clock.now += datetime.timedelta(days=1)
    build_digests(db_session, settings, clock=clock)
    send_pending(db_session, settings, clock=clock)
    tokens = re.findall(r"pausar\?token=([\w.~-]+)", smtp.text())
    assert [read_pause_token(SECRET, t) for t in tokens] == [s.id for s in subscriptions]


@pytest.mark.parametrize("missing", ["public_url", "link_secret"])
def test_without_settings_for_links_the_email_has_none(db_session, make, smtp, settings, clock, missing) -> None:
    import dataclasses

    _send(db_session, make, dataclasses.replace(settings, **{missing: ""}), clock)
    assert "token=" not in smtp.text() and "token=" not in smtp.html()


def test_a_match_from_before_the_upgrade_has_an_excerpt_too(db_session, make, smtp, settings, clock) -> None:
    match = make.match(make.subscription(), make.document("El texto del documento."))
    match.fragmento_id = None
    db_session.commit()
    send_pending(db_session, settings, clock=clock)
    assert "El texto del documento." in smtp.text()


def test_the_email_has_a_plain_and_an_html_version(db_session, make, smtp, settings, clock) -> None:
    _send(db_session, make, settings, clock)
    assert smtp.messages[0].get_content_type() == "multipart/alternative"
    assert 'lang="es"' in smtp.html()
