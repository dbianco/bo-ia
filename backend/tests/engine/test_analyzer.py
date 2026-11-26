"""Plan 4: Spanish analyzer."""
import pytest

from src.engine.analyzer import analyze, stem


@pytest.mark.parametrize(
    "forms",
    [
        ("licitación", "licitaciones", "LICITACION"),
        ("pública", "público", "públicas", "públicos"),
        ("luz", "luces"),
        ("calle", "calles"),
        ("obra", "obras"),
        ("pago", "pagos"),
        ("ley", "leyes"),
        ("red", "redes"),
        ("pliego", "pliegos"),
        ("interés", "intereses"),
        ("mes", "meses"),
        ("municipal", "municipales"),
        ("provincial", "provinciales"),
        ("camión", "camiones"),
        ("vez", "veces"),
    ],
)
def test_forms_of_a_word_become_one_term(forms: tuple) -> None:
    assert len({tuple(analyze(form)) for form in forms}) == 1


def test_different_words_stay_different() -> None:
    words = ["puente", "puerto", "obra", "hora", "ley", "res", "resto", "agua", "camino", "camión", "gas", "gasto"]
    assert len({analyze(w)[0] for w in words}) == len(words)


def test_lowercases_folds_accents_and_drops_stopwords() -> None:
    assert analyze("El Ministerio de la Nación, y los demás") == [stem("ministerio"), stem("nacion")]


def test_numbers_are_kept_as_they_are() -> None:
    assert analyze("Expediente Nº 0683-080515/2026") == [stem("expediente"), "0683", "080515", "2026"]


def test_short_words_are_not_stemmed() -> None:
    assert [stem(w) for w in ("gas", "mesa", "rio", "ano")] == ["gas", "mesa", "rio", "ano"]


@pytest.mark.parametrize("text", ["", "   ", "de la y el", "¿¡...!?"])
def test_text_without_terms(text: str) -> None:
    assert analyze(text) == []


def test_analysis_is_stable() -> None:
    """Analyzing what was already analyzed must not lose the match."""
    text = "Llámese a licitación pública para la adquisición de neumáticos"
    assert analyze(text) == analyze(text.upper())
