# bo-ia

Plataforma de búsqueda semántica del Boletín Oficial de la Provincia de Córdoba.

## Documentación

- **Spec de diseño:** [docs/superpowers/specs/2026-09-16-boletin-oficial-design.md](docs/superpowers/specs/2026-09-16-boletin-oficial-design.md) — contexto, alcance por etapas, arquitectura y modelo de datos.
- **Feature MVP (spec-kit / SDD):** [specs/construir-el-mvp-de-busqueda-semantica-del-bolet/](specs/construir-el-mvp-de-busqueda-semantica-del-bolet/) — `spec.md`, `plan.md` y `tasks.md` de la Etapa 1.

## Estado actual

El MVP (Etapa 1) está en implementación, siguiendo las tareas de `tasks.md`. El entorno de Docker ya levanta (`db`, `backend`, `web` healthy), pero todavía no tiene los endpoints de ingesta/búsqueda ni los datos de ejemplo (tareas T007 en adelante).

## Estructura del repositorio

- `backend/` — Ingestor, Procesador y API (Python/FastAPI), consolidados en un solo servicio.
- `web/` — interfaz de búsqueda (Jinja2 + htmx).
- `specs/` — artefactos del framework spec-kit (spec, plan, tareas) para el flujo de fases del SDD.
- `docs/` — spec de diseño original y documentación de referencia.

## Cómo correr esto localmente

Requiere Docker y Docker Compose (Docker Desktop en macOS o Windows).

```bash
cp .env.example .env
docker compose up --build
```

Esto levanta tres servicios: `db` (PostgreSQL + pgvector, puerto 9100), `backend` (Ingestor + Procesador + API, puerto 9101) y `web` (interfaz de búsqueda, puerto 9102). Los puertos están en el rango 9100 para evitar choques con otras apps corriendo en la máquina.

Por ahora los servicios solo exponen un chequeo de salud, mientras se completan los endpoints reales:

```bash
curl http://localhost:9101/health   # backend
curl http://localhost:9102/health   # web
```

La búsqueda de punta a punta (con datos de ejemplo precargados) queda disponible cuando se completen las tareas de `tasks.md` hasta T025.
