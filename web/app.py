"""Interfaz web (Jinja2 + htmx) — entrypoint.

En esta etapa de Setup (T001-T006) solo expone un health check, para poder
validar que la imagen Docker construye y arranca correctamente antes de
implementar la página de búsqueda real. Esa página se agrega en T026-T027.
"""
from fastapi import FastAPI

app = FastAPI(title="bo-ia web")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
