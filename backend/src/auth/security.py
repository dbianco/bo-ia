"""Hash de contraseñas con la librería estándar (FR-002).

`hashlib.pbkdf2_hmac` con SHA-256 y 600.000 iteraciones (recomendación
vigente de OWASP para PBKDF2) evita sumar una dependencia nueva
(`bcrypt`/`argon2-cffi`) para esta primera versión de autenticación.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

ITERACIONES = 600_000
LARGO_SAL = 16
ALGORITMO = "sha256"


def hash_password(password: str) -> str:
    sal = secrets.token_hex(LARGO_SAL)
    derivado = hashlib.pbkdf2_hmac(ALGORITMO, password.encode("utf-8"), bytes.fromhex(sal), ITERACIONES)
    return f"{ALGORITMO}${ITERACIONES}${sal}${derivado.hex()}"


def verificar_password(password: str, hashed: str) -> bool:
    try:
        algoritmo, iteraciones_str, sal, derivado_hex = hashed.split("$")
        iteraciones = int(iteraciones_str)
    except ValueError:
        return False

    candidato = hashlib.pbkdf2_hmac(algoritmo, password.encode("utf-8"), bytes.fromhex(sal), iteraciones)
    return hmac.compare_digest(candidato.hex(), derivado_hex)
