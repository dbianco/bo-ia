"""FastAPI application entrypoint.

En esta etapa de Setup (T001-T006) solo expone un health check, para poder
validar que la imagen Docker construye y arranca correctamente antes de
implementar los endpoints reales. Los endpoints de búsqueda, ingesta y
valoraciones se agregan en T022, T023 y T024.
"""
from fastapi import FastAPI

app = FastAPI(title="bo-ia backend")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
