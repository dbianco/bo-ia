"""Envío de correo por SMTP (FR-006 a FR-009). `smtplib`/`email` de la
librería estándar, configurado enteramente por variables de entorno — sin
sumar una dependencia nueva ni una cuenta de proveedor externo para esta
primera versión.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

TIMEOUT_SMTP_SEGUNDOS = 10


class EnvioCorreoFallido(RuntimeError):
    """SMTP no está configurado, o el envío falló (FR-007)."""


def _config_smtp() -> tuple[str, int, str | None, str | None, str]:
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise EnvioCorreoFallido("SMTP_HOST no está configurado")
    puerto = int(os.environ.get("SMTP_PORT", "587"))
    usuario = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    remitente = os.environ.get("SMTP_FROM") or usuario or "no-reply@bo-ia.local"
    return host, puerto, usuario, password, remitente


def enviar_correo(*, destinatario: str, asunto: str, cuerpo: str) -> None:
    host, puerto, usuario, password, remitente = _config_smtp()

    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = remitente
    mensaje["To"] = destinatario
    mensaje.set_content(cuerpo)

    try:
        with smtplib.SMTP(host, puerto, timeout=TIMEOUT_SMTP_SEGUNDOS) as smtp:
            smtp.starttls()
            if usuario and password:
                smtp.login(usuario, password)
            smtp.send_message(mensaje)
    except (OSError, smtplib.SMTPException) as exc:
        raise EnvioCorreoFallido(str(exc)) from exc
