"""T013: fragmentación con tamaño/solapamiento configurables y la garantía
de al menos un fragmento (FR-004, FR-005, FR-007)."""
import pytest

from src.ingestor.fragmenter import fragmentar_texto


def test_fragmentar_texto_corto_devuelve_un_unico_fragmento() -> None:
    fragmentos = fragmentar_texto("Decreto breve.", tamano=1000, solapamiento=200)
    assert fragmentos == ["Decreto breve."]


def test_fragmentar_texto_largo_respeta_tamano_configurado() -> None:
    texto = "x" * 2500
    fragmentos = fragmentar_texto(texto, tamano=1000, solapamiento=200)
    assert len(fragmentos) > 1
    assert all(len(f) <= 1000 for f in fragmentos)


def test_fragmentar_texto_respeta_el_solapamiento() -> None:
    texto = "abcdefghij" * 150  # 1500 caracteres
    fragmentos = fragmentar_texto(texto, tamano=1000, solapamiento=200)
    # El final del primer fragmento debe reaparecer al inicio del segundo.
    assert fragmentos[0][-200:] == fragmentos[1][:200]


def test_fragmentar_texto_cubre_todo_el_contenido_sin_saltos() -> None:
    texto = "0123456789" * 300  # 3000 caracteres
    fragmentos = fragmentar_texto(texto, tamano=800, solapamiento=150)
    reconstruido = fragmentos[0]
    for frag in fragmentos[1:]:
        reconstruido += frag[150:]
    assert reconstruido == texto


def test_fragmentar_texto_garantiza_al_menos_un_fragmento_para_texto_no_vacio() -> None:
    fragmentos = fragmentar_texto("a", tamano=1000, solapamiento=200)
    assert len(fragmentos) >= 1


def test_fragmentar_texto_vacio_lanza_error_en_vez_de_devolver_cero_fragmentos() -> None:
    with pytest.raises(ValueError):
        fragmentar_texto("   ", tamano=1000, solapamiento=200)


def test_fragmentar_texto_rechaza_solapamiento_mayor_o_igual_al_tamano() -> None:
    with pytest.raises(ValueError):
        fragmentar_texto("algún texto", tamano=100, solapamiento=100)
