"""Envío de correo por SMTP (FR-006 a FR-009). `smtplib`/`email` de la
librería estándar, configurado enteramente por variables de entorno — sin
sumar una dependencia nueva ni una cuenta de proveedor externo para esta
primera versión.

A failure says whether it makes sense to try again, and whether it is of the
server or of this message.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, parseaddr

TIMEOUT_SMTP_SEGUNDOS = 10
SECURITY = ("starttls", "ssl", "none")
DEFAULT_FROM = "no-reply@contextcrawl.local"


class EnvioCorreoFallido(RuntimeError):
    """SMTP no está configurado, o el envío falló (FR-007)."""

    def __init__(self, message: str, *, permanent: bool = False, server: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent  # trying again would fail in the same way
        self.server = server  # any other message would fail too


def _remitente() -> str:
    return os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or DEFAULT_FROM


def sender_domain() -> str:
    return parseaddr(_remitente())[1].rpartition("@")[2] or "contextcrawl.local"


def _config_smtp() -> tuple[str, int, str, str | None, str | None]:
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise EnvioCorreoFallido("SMTP_HOST no está configurado", permanent=True)
    security = (os.environ.get("SMTP_SECURITY") or "starttls").strip().lower()
    if security not in SECURITY:
        raise EnvioCorreoFallido(f"SMTP_SECURITY debe ser uno de {', '.join(SECURITY)}", server=True)
    puerto = int(os.environ.get("SMTP_PORT") or "587")
    return host, puerto, security, os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")


def _mensaje(destinatario: str, asunto: str, cuerpo: str, html: str | None, message_id: str | None) -> EmailMessage:
    mensaje = EmailMessage()
    try:
        mensaje["Subject"] = asunto
        mensaje["From"] = _remitente()
        mensaje["To"] = destinatario
        mensaje["Date"] = formatdate()
        if message_id:
            mensaje["Message-ID"] = message_id
        mensaje.set_content(cuerpo)
        if html is not None:
            mensaje.add_alternative(html, subtype="html")
    except ValueError as exc:  # a line break in an address, for instance
        raise EnvioCorreoFallido(f"el mensaje no se puede construir: {exc}", permanent=True) from exc
    return mensaje


def enviar_correo(
    *, destinatario: str, asunto: str, cuerpo: str, html: str | None = None, message_id: str | None = None
) -> None:
    host, puerto, security, usuario, password = _config_smtp()
    mensaje = _mensaje(destinatario, asunto, cuerpo, html, message_id)
    connect = smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP
    connected = False
    try:
        with connect(host, puerto, timeout=TIMEOUT_SMTP_SEGUNDOS) as smtp:
            if security == "starttls":
                smtp.starttls()
            if usuario and password:
                smtp.login(usuario, password)
            connected = True
            smtp.send_message(mensaje)
    except smtplib.SMTPRecipientsRefused as exc:
        code, text = next(iter(exc.recipients.values()), (0, b""))
        raise EnvioCorreoFallido(f"{code} {_text(text)}", permanent=500 <= code < 600) from exc
    except smtplib.SMTPDataError as exc:
        raise EnvioCorreoFallido(
            f"{exc.smtp_code} {_text(exc.smtp_error)}", permanent=500 <= exc.smtp_code < 600
        ) from exc
    except smtplib.SMTPNotSupportedError as exc:
        # Before connecting, the server lacks something that is configured. After,
        # it is the address: the server does not accept letters beyond ASCII.
        raise EnvioCorreoFallido(str(exc), permanent=connected, server=not connected) from exc
    except smtplib.SMTPResponseException as exc:  # the sender, the password or the connection
        raise EnvioCorreoFallido(f"{exc.smtp_code} {_text(exc.smtp_error)}", server=True) from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise EnvioCorreoFallido(str(exc), server=True) from exc


def _text(reply: bytes | str) -> str:
    return reply.decode(errors="replace") if isinstance(reply, bytes) else str(reply)
