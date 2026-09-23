# Feature: Etapa 2 — Ingesta operativa

Framework: spec-kit (track default)
Feature ID: f_01m37nm2axpsc7gyjt6sq9vktt
Fuente: `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md` (v0.2), sección 4.3 (Conectores), 4.4 (Scheduler) y 8 (Etapa 2); `docs/superpowers/reports/2026-09-23-scraping-poc.md` (PoC de scraping)

## User Scenarios

### Primary user story

Como operador de la instalación, quiero que el sistema descubra e incorpore automáticamente nuevos documentos del Boletín Oficial de la Provincia de Córdoba según una frecuencia configurada, sin intervención manual, para no depender de cargar cada documento a mano vía la API.

### Acceptance scenarios

1. **Given** una fuente con conector y frecuencia configurados en `installation.yaml`, **When** llega el momento programado, **Then** el scheduler ejecuta el conector automáticamente, sin intervención manual.
2. **Given** una ejecución de conector, **When** se completa, **Then** queda registrada una fila en `ejecuciones_fuente` con fuente, inicio, fin, descubiertos, nuevos, existentes, errores y versión del conector.
3. **Given** el conector del BOP corriendo contra un fixture de la página de anuncios de un día, **When** se ejecuta, **Then** descubre cada anuncio, extrae título, organismo y URL del PDF, descarga y extrae el texto del PDF, y produce un `DocumentoNormalizado` por anuncio.
4. **Given** un documento ya ingerido antes (misma fuente + `identificador_externo`), **When** el conector lo vuelve a descubrir en una ejecución posterior, **Then** no se duplica (idempotencia ya existente de la Etapa 1) y la ejecución lo cuenta como "existente", no como "nuevo".
5. **Given** un error de descarga o de extracción de texto en el PDF de un anuncio particular, **When** ocurre durante una ejecución, **Then** el resto de los anuncios de esa ejecución se procesan igual, el error queda contado y registrado en la ejecución, y la ejecución no se pierde completa.
6. **Given** un desarrollador que quiere disparar una corrida sin esperar al scheduler, **When** invoca la ejecución manual de una fuente, **Then** corre el mismo conector y registra la misma clase de ejecución que una corrida programada.
7. **Given** el backend arrancando, **When** el scheduler se inicializa, **Then** programa cada fuente que declara conector y frecuencia en `installation.yaml`, sin requerir configuración adicional en código.

## Functional Requirements

### Ejecuciones y estado

- **FR-001**: The system MUST store one `ejecuciones_fuente` row per connector run, with `fuente_id`, `inicio`, `fin`, `estado` (`en_curso`/`completada`/`fallida`), `descubiertos`, `nuevos`, `existentes`, `errores` and `version_conector`.
- **FR-002**: The existing idempotent-ingestion mechanism (`fuente_id` + `identificador_externo`, or `hash_contenido`) MUST determine whether a discovered document counts as `nuevos` or `existentes` within an execution.
- **FR-003**: WHEN an individual document fails to normalize or ingest, the system SHALL continue processing the remaining documents of the same execution, incrementing `errores` and recording enough detail (at least the source's identifier and the error message) to diagnose it without losing the rest of the execution's results.

### Conector (interfaz)

- **FR-004**: The system MUST define a connector interface (a `Protocol`) with a single entry point that yields `DocumentoNormalizado` instances for a given fuente and its configuration, independent of the scheduler and of persistence.
- **FR-005**: Connector implementations MUST NOT write directly to `documentos` or `fragmentos`, nor call the embedding provider; only the shared `ingerir_documento` pipeline does that.

### Conector del Boletín Oficial de la Provincia (BOP)

- **FR-006**: The system MUST implement a connector for the Boletín Oficial de la Provincia de Córdoba (Diputación), using Scrapy, that discovers announcements from a day's index page and extracts título, organismo, URL del PDF and `identificador_externo`.
- **FR-007**: The connector MUST download and extract the text of each announcement's PDF, using it as the document's `texto`.
- **FR-008**: WHEN a PDF cannot be downloaded or its text cannot be extracted (for example, a scanned/image-only PDF), the system SHALL record it as an error for that specific document within the execution (per FR-003), rather than failing the whole run.
- **FR-009**: Every outbound HTTP request the connector makes (index page, PDF downloads) MUST have an explicit timeout and a bounded retry count.

### Scheduler

- **FR-010**: The system MUST run an in-process scheduler that triggers each fuente's connector at the interval declared in its `installation.yaml` configuration.
- **FR-011**: The system MUST allow triggering a connector run manually for a given fuente, outside its schedule, for operability and debugging.
- **FR-012**: WHERE a fuente has no connector or frequency declared, the scheduler MUST NOT attempt to run anything for it; such fuentes (for example, the current municipal fuentes fed only via `POST /v1/documentos` or the seed) MUST keep working unaffected.

### Configuración

- **FR-013**: `installation.yaml`'s fuente declaration MUST support an optional connector block (a `tipo` naming a registered connector, the connector's own config, and a frequency) so that adding a new fuente that reuses an existing connector type requires no code changes.

## Success Criteria

- **SC-001**: A full connector run against a fixture of a day's BOP index page (30 announcements, per the PoC) produces exactly 30 normalized documents.
- **SC-002**: Re-running the connector against the same fixture data produces 0 new documents (100% counted as `existentes`), verified by an integration test.
- **SC-003**: For 100% of executions in the test suite, `nuevos + existentes + errores` equals `descubiertos`.
- **SC-004**: A fixture containing 1 unreadable PDF among N announcements results in exactly 1 error and N-1 successfully ingested documents in the same execution.
- **SC-005**: In a test with an accelerated interval (for example 2 seconds), the scheduler triggers a connector run automatically, without manual intervention, within that interval.
- **SC-006**: 0 tests in the default suite (`pytest` without an explicit `live`/`docker` marker) make a real network call to `bop.dipucordoba.es`; all connector tests run against local fixtures (saved HTML and PDF samples).

## Clarifications

- **Q**: ¿Dónde corre el scheduler? **A**: In-process, con APScheduler, en el mismo contenedor `backend`. Alternativa considerada: un proceso/contenedor separado — se descartó por ahora para no sumar un servicio a `docker-compose.yml` sin evidencia de que haga falta. (2026-09-23)
- **Q**: ¿Se incluye extracción de texto de PDF en esta etapa? **A**: Sí. El PoC de scraping no la había probado (quedaba como spike aparte), pero se decidió resolverla ahora para que el conector del BOP produzca documentos con texto real, no solo el título del anuncio. (2026-09-23)
- **Q**: ¿Cómo se prueban los conectores sin depender de la red real? **A**: Con fixtures (HTML del índice y PDFs de muestra guardados en el repo) para la suite por defecto. Un test contra la red real, si existe, se marca aparte (como ya existen `slow`/`docker`) y no corre en CI por defecto. (2026-09-23)
- **Q**: ¿Qué fuente recibe el primer conector real? **A**: `cordoba-provincial`, ya declarada en `installation.yaml`. Las fuentes municipales (`carlos-paz-municipal`, `noetinger-municipal`) siguen sin conector real, alimentadas solo por seed o por `POST /v1/documentos` manual. (2026-09-23)
