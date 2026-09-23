"""T004: `hash_password`/`verificar_password` (FR-002)."""
from src.auth.security import hash_password, verificar_password


def test_hash_password_no_devuelve_la_contrasena_en_texto_plano() -> None:
    hashed = hash_password("una-contraseña-secreta")

    assert hashed != "una-contraseña-secreta"
    assert "una-contraseña-secreta" not in hashed


def test_hash_password_genera_hashes_distintos_para_la_misma_contrasena() -> None:
    """La sal por usuario evita que dos contraseñas iguales produzcan el
    mismo hash (protege contra tablas rainbow entre cuentas)."""
    assert hash_password("misma-contraseña") != hash_password("misma-contraseña")


def test_verificar_password_acepta_la_contrasena_correcta() -> None:
    hashed = hash_password("correcta")
    assert verificar_password("correcta", hashed) is True


def test_verificar_password_rechaza_la_contrasena_incorrecta() -> None:
    hashed = hash_password("correcta")
    assert verificar_password("incorrecta", hashed) is False
