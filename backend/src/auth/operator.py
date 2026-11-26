"""The token that the endpoints of the operator require: adding documents and
running a source. It is not the session of a user."""
from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

TOKEN_VARIABLE = "OPERATOR_TOKEN"


def configured_token() -> str:
    """Empty if there is none, and then nobody is the operator."""
    return os.environ.get(TOKEN_VARIABLE, "").strip()


def require_operator(request: Request) -> None:
    """401 unless the request carries the token: `Authorization: Bearer <token>`.
    Neither token is ever logged or returned."""
    expected = configured_token().encode()
    # Headers are bytes; the framework decodes them as latin-1.
    scheme, _, sent = request.headers.get("authorization", "").encode("latin-1").partition(b" ")
    # Always compared, so that the time does not tell how far it got.
    same = hmac.compare_digest(sent.strip(), expected)
    if not (expected and scheme.lower() == b"bearer" and same):
        raise HTTPException(
            status_code=401, detail="Se requiere el token de operador", headers={"WWW-Authenticate": "Bearer"}
        )
