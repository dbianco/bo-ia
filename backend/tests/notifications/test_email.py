"""T004: `enviar_correo` — éxito con SMTP mockeado, falta configuración,
error de SMTP (FR-006, FR-007, FR-009)."""
from unittest.mock import MagicMock, patch

import pytest

from src.notifications.email import EnvioCorreoFallido, enviar_correo


@pytest.fixture(autouse=True)
def _config_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bo-ia")
    monkeypatch.setenv("SMTP_PASSWORD", "secreta")
    monkeypatch.setenv("SMTP_FROM", "avisos@bo-ia.local")


def test_enviar_correo_exitoso_usa_smtp_configurado() -> None:
    with patch("src.notifications.email.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp

        enviar_correo(destinatario="cliente@example.org", asunto="Asunto", cuerpo="Cuerpo del aviso")

        smtp_cls.assert_called_once()
        _, kwargs = smtp_cls.call_args
        assert kwargs.get("timeout") is not None
        smtp.login.assert_called_once_with("bo-ia", "secreta")
        smtp.send_message.assert_called_once()


def test_enviar_correo_sin_smtp_host_configurado_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with pytest.raises(EnvioCorreoFallido):
        enviar_correo(destinatario="cliente@example.org", asunto="Asunto", cuerpo="Cuerpo")


def test_enviar_correo_con_error_de_smtp_levanta_envio_correo_fallido() -> None:
    with patch("src.notifications.email.smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.side_effect = ConnectionRefusedError("conexión rechazada")

        with pytest.raises(EnvioCorreoFallido):
            enviar_correo(destinatario="cliente@example.org", asunto="Asunto", cuerpo="Cuerpo")
