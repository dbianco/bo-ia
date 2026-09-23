# Plan: Etapa 2 — Ingesta operativa

Framework: spec-kit (track default)
Feature ID: f_01m37nm2axpsc7gyjt6sq9vktt
Fuente: `spec.md` de esta feature y `docs/superpowers/reports/2026-09-23-scraping-poc.md`

## Technical Context

- **Lenguaje y versión:** Python 3.12, mismo backend consolidado.
- **Dependencias nuevas:** `scrapy` (motor de conectores, recomendado por el PoC), `apscheduler` (scheduler in-process), `pypdf` (extracción de texto de PDF). Versiones exactas a confirmar contra PyPI al implementar (mismo criterio que `pyyaml` en la Etapa 1: sin alternativa razonable en la librería estándar para ninguna de las tres).
- **Almacenamiento:** nueva tabla `ejecuciones_fuente` (Postgres), con `detalle_errores` en JSONB (lista de `{identificador_externo, error}`).
- **Herramientas de testing:** pytest, más fixtures reales (HTML del índice y PDFs de muestra) bajo `backend/tests/fixtures/bop_cordoba/`, consumidas vía URLs `file://` para que el conector corra sin red (SC-006). Se agrega el marker `live` (mismo patrón que `slow`/`docker`) para un test opcional contra la red real, excluido del run por defecto y de CI.
- **Plataforma objetivo:** sin cambios — el scheduler corre dentro del mismo contenedor `backend`, no se agrega un servicio a `docker-compose.yml` (decisión ya tomada en `spec.md`).
- **Objetivos de performance y restricciones:** cada corrida del conector del BOP corre el spider de Scrapy en un subproceso propio (`multiprocessing`, contexto `spawn`), con un timeout de proceso desde el padre además del `DOWNLOAD_TIMEOUT`/`RETRY_TIMES` de Scrapy (FR-009).

## Constitution Check

- **Sin datos personales en logs:** sin cambios; los anuncios del BOP son actos oficiales públicos.
- **Timeout y retry en llamadas HTTP salientes:** el spider fija `DOWNLOAD_TIMEOUT` y `RETRY_TIMES` para la página de índice y cada descarga de PDF (FR-009); el proceso padre además aplica un timeout duro sobre el subproceso completo.
- **Migraciones de esquema reversibles con rollback probado:** una revisión Alembic nueva crea `ejecuciones_fuente`, con `downgrade` completo, probada con el mismo patrón `upgrade → downgrade → upgrade` de `test_migrations.py`.
- **Cambios de API pública aditivos:** `POST /v1/fuentes/{clave}/ejecutar` es un endpoint nuevo (FR-011); no se modifica ningún contrato existente de la Etapa 1.
- **Secretos desde el entorno:** sin cambios; el BOP es un sitio público sin autenticación, no hay credenciales nuevas.
- **Tests en CI antes de mergear:** se agregan al mismo `ci.yml`; el test marcado `live` (si se agrega) queda excluido del job, igual que `docker`.
- **Accesibilidad:** no aplica; esta etapa no toca la interfaz web.

## Project Structure

Lista inicial; se actualiza con los nombres reales de la migración y el árbol final antes de `verify`, igual que en la Etapa 1.

Modificados:

- `backend/pyproject.toml`
- `backend/src/db/models.py`
- `backend/src/api/main.py`
- `installation.yaml`
- `README.md`
- `backend/tests/test_migrations.py`

Nuevos:

- `backend/src/db/migrations/versions/<rev>_create_ejecuciones_fuente.py`
- `backend/src/connectors/__init__.py`
- `backend/src/connectors/protocol.py` (`Conector`, `ErrorDescubrimiento`)
- `backend/src/connectors/registry.py`
- `backend/src/connectors/runner.py` (`ejecutar_conector`)
- `backend/src/connectors/bop_cordoba/__init__.py`
- `backend/src/connectors/bop_cordoba/spider.py`
- `backend/src/connectors/bop_cordoba/pdf.py`
- `backend/src/connectors/bop_cordoba/connector.py`
- `backend/src/scheduler/__init__.py`
- `backend/src/api/fuentes.py` (`POST /v1/fuentes/{clave}/ejecutar`)
- `backend/tests/fixtures/bop_cordoba/index.html`
- `backend/tests/fixtures/bop_cordoba/anuncio_ok.pdf`
- `backend/tests/fixtures/bop_cordoba/anuncio_corrupto.pdf`
- `backend/tests/connectors/test_bop_cordoba.py`
- `backend/tests/connectors/test_runner.py`
- `backend/tests/scheduler/test_scheduler.py`
- `backend/tests/api/test_fuentes.py`

## Research

- **Scrapy en subproceso propio, no `CrawlerProcess` embebido en el proceso del backend:** Scrapy corre sobre el reactor de Twisted, que no se puede reiniciar dentro del mismo proceso — un problema real para un scheduler que dispara la misma fuente repetidamente. Se ejecuta cada corrida en un `multiprocessing.Process` (contexto `spawn`) que corre `CrawlerProcess` y exporta los items a un archivo temporal (`FEEDS` de Scrapy, formato `jsonlines`); el conector del proceso padre lee ese archivo y lo traduce a `DocumentoNormalizado`/`ErrorDescubrimiento`. Esto aísla el reactor por corrida y evita el problema, a cambio de la complejidad de comunicarse por archivo en vez de en memoria.
- **Extracción de PDF dentro del spider, no en el conector:** el spider sigue el link al PDF con un `scrapy.Request` propio (callback `parse_pdf`), así la descarga usa el mismo downloader con retry/timeout que la página de índice (FR-009 cubierto en un solo lugar). `parse_pdf` extrae el texto con `pypdf` y arma el item final; un error de descarga o de extracción se captura ahí y se emite como un item de error distinguible (`error: true`), no como una excepción que tire abajo el spider completo.
- **`pypdf` sobre `pdfplumber`/`pymupdf`:** los documentos oficiales del BOP son PDFs generados digitalmente (texto real, no escaneado), así que alcanza con un extractor de texto simple. `pypdf` es la opción más liviana y con licencia BSD, sin dependencias pesadas. Si aparecen PDFs escaneados, la extracción falla de forma controlada (FR-008) y queda como gap conocido para una etapa futura (OCR).
- **APScheduler `BackgroundScheduler` (basado en threads), no `AsyncIOScheduler`:** el resto del backend usa SQLAlchemy síncrono (no async), así que un scheduler basado en threads evita mezclar dos modelos de concurrencia. Cada job abre su propia `Session` corta, igual que hace cada request de la API.
- **Fixtures vía `file://`, no mocks de `httpx`/`requests`:** Scrapy tiene su propio downloader; mockear a nivel de librería HTTP no lo intercepta. Apuntar el spider a una URL `file://` con HTML y PDFs de muestra ejercita el pipeline completo (parseo, seguimiento de links, extracción de PDF) sin red real, cumpliendo SC-006.
- **Conector registrado por `tipo` en `installation.yaml`, no hardcodeado por `clave` de fuente:** mantiene la línea de la Etapa 1 ("configuración antes que código"): agregar una fuente nueva que reutiliza el mismo tipo de conector (por ejemplo, otro boletín municipal que también expone HTML) no requiere tocar `backend/src/`.
