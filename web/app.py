"""Interfaz web (Jinja2 + htmx): campo de búsqueda, filtros de fecha,
lista de resultados y valoración con pulgar arriba/abajo (sección 10 del
design spec, FR-014)."""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BACKEND_URL = os.environ.get("BACKEND_INTERNAL_URL", "http://backend:8000")

app = FastAPI(title="bo-ia web")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    with httpx.Client(timeout=10.0) as client:
        respuesta = client.get(f"{BACKEND_URL}/v1/config")
    respuesta.raise_for_status()
    config = respuesta.json()

    return templates.TemplateResponse(
        request, "search.html", {"nombre_instalacion": config["nombre"], "filtros": config["filtros"]}
    )


@app.get("/resultados", response_class=HTMLResponse)
def resultados(
    request: Request,
    q: str,
    date_from: str | None = None,
    date_to: str | None = None,
    mode: str = "semantic",
) -> HTMLResponse:
    params: dict[str, str] = {"q": q, "mode": mode}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    # Filtros declarados por la instalación (Etapa 1): se reenvían tal
    # cual, sin que la web conozca sus claves de antemano.
    for clave, valor in request.query_params.items():
        if clave.startswith("filtro.") and valor:
            params[clave] = valor

    with httpx.Client(timeout=30.0) as client:
        respuesta = client.get(f"{BACKEND_URL}/v1/search", params=params)
    respuesta.raise_for_status()
    cuerpo = respuesta.json()

    return templates.TemplateResponse(
        request, "_resultados.html", {"resultados": cuerpo["resultados"], "consulta": q}
    )


@app.post("/valorar", response_class=HTMLResponse)
def valorar(
    request: Request,
    fragmento_id: int = Form(...),
    consulta: str = Form(...),
    valor: str = Form(...),
) -> HTMLResponse:
    with httpx.Client(timeout=10.0) as client:
        respuesta = client.post(
            f"{BACKEND_URL}/v1/valoraciones",
            json={"fragmento_id": fragmento_id, "consulta": consulta, "valor": valor},
        )
    respuesta.raise_for_status()

    return templates.TemplateResponse(request, "_gracias.html", {"valor": valor})
