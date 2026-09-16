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
    if tamano <= 0:
        raise ValueError("El tamaño del fragmento debe ser mayor a 0")
    if solapamiento < 0 or solapamiento >= tamano:
        raise ValueError("El solapamiento debe ser >= 0 y menor al tamaño del fragmento")

    texto = texto.strip()
    if not texto:
        raise ValueError("No se puede fragmentar un texto vacío")

    fragmentos: list[str] = []
    inicio = 0
    n = len(texto)
    paso = tamano - solapamiento

    while inicio < n:
        fin = min(inicio + tamano, n)
        fragmentos.append(texto[inicio:fin])
        if fin == n:
            break
        inicio += paso

    return fragmentos
