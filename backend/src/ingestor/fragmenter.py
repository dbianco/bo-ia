"""Fragmentación de texto con tamaño y solapamiento configurables.

FR-004: divide textos extensos en fragmentos con tamaño y solapamiento
configurables.
FR-007 (parcial): garantiza al menos un fragmento para todo texto no
vacío; el llamador (T023) es responsable de persistirlos y de que el
boletín completo no se considere ingerido sin al menos uno.
"""
from __future__ import annotations

TAMANO_DEFAULT = 1000
SOLAPAMIENTO_DEFAULT = 200


def fragmentar_texto(
    texto: str, *, tamano: int = TAMANO_DEFAULT, solapamiento: int = SOLAPAMIENTO_DEFAULT
) -> list[str]:
    return [texto[a:b] for a, b in fragment_spans(texto, tamano=tamano, solapamiento=solapamiento)]


def fragment_spans(
    texto: str, *, tamano: int = TAMANO_DEFAULT, solapamiento: int = SOLAPAMIENTO_DEFAULT
) -> list[tuple[int, int]]:
    """Start and end of each fragment in the text as it was received."""
    if tamano <= 0:
        raise ValueError("El tamaño del fragmento debe ser mayor a 0")
    if solapamiento < 0 or solapamiento >= tamano:
        raise ValueError("El solapamiento debe ser >= 0 y menor al tamaño del fragmento")

    if not texto.strip():
        raise ValueError("No se puede fragmentar un texto vacío")

    fragmentos: list[tuple[int, int]] = []
    inicio = len(texto) - len(texto.lstrip())
    n = len(texto.rstrip())
    paso = tamano - solapamiento

    while inicio < n:
        fin = min(inicio + tamano, n)
        fragmentos.append((inicio, fin))
        if fin == n:
            break
        inicio += paso

    return fragmentos
