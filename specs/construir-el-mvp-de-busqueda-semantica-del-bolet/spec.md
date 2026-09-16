# Feature: MVP público de búsqueda semántica del Boletín Oficial

Framework: spec-kit (track default)
Feature ID: f_01m2npz2d7t6489bgwchqas3wm
Fuente: adaptado de `docs/superpowers/specs/2026-09-16-boletin-oficial-design.md` (v0.4), Etapa 1

## User Scenarios

### Primary user story

Como usuario público, quiero buscar boletines oficiales de la Provincia de Córdoba mediante una consulta en lenguaje natural, acotable por fecha, para encontrar información relevante sin revisar boletines uno por uno, verificando cada resultado en la fuente oficial.

### Acceptance scenarios

1. **Given** un corpus de boletines ya ingerido e indexado, **When** el usuario ingresa una consulta en lenguaje natural, **Then** el sistema devuelve fragmentos relevantes ordenados por relevancia semántica, cada uno con fecha, identificador y enlace oficial.
2. **Given** una consulta con fecha desde, fecha hasta o ambas, **When** se ejecuta la búsqueda, **Then** los resultados quedan acotados a ese intervalo.
3. **Given** una consulta cuya mejor coincidencia no supera el umbral interno de similitud, **When** se ejecuta la búsqueda, **Then** el sistema devuelve una lista vacía junto con un aviso de que no hay resultados confiables.
4. **Given** un resultado mostrado en la interfaz, **When** el usuario hace clic en el ícono de pulgar arriba o pulgar abajo, **Then** la valoración queda registrada, asociada a la consulta y al fragmento mostrado.
5. **Given** un boletín nuevo con su texto, identificador, fecha de publicación y URL oficial, **When** se completa la ingesta, **Then** el boletín queda dividido en al menos un fragmento con su embedding generado y disponible para búsqueda.
6. **Given** una persona con Docker instalado en macOS o en Windows, **When** ejecuta `docker compose up --build` sobre el repositorio, **Then** el entorno completo (base de datos, backend e interfaz web) queda levantado con datos de ejemplo cargados, listo para probar la búsqueda de punta a punta.

## Functional Requirements

### Ingesta

- **FR-001**: The system MUST accept a boletín's text together with its official identifier, publication date and official URL.
- **FR-002**: The system MUST perform ingestion idempotently, so a boletín is never duplicated.
- **FR-003**: The system MUST retain a reference to the original content received.
- **FR-004**: The system MUST split long texts into fragments with configurable size and overlap.
- **FR-005**: Each fragment MUST retain the boletín identifier, its position within the document and the publication date.
- **FR-006**: WHEN a processing error occurs, the system SHALL record it without losing the document that was received.
- **FR-007**: The system MUST guarantee that every ingested boletín has at least one associated fragment; a boletín with zero fragments SHALL NOT be considered successfully ingested.

### Búsqueda

- **FR-008**: The system MUST allow the user to search using a natural-language query.
- **FR-009**: The system MUST allow the user to specify a from-date, a to-date, or both.
- **FR-010**: The system MUST order results by semantic relevance.
- **FR-011**: Each result MUST display a contextual fragment, its date and the official link.
- **FR-012**: WHEN no fragment clears the similarity threshold, the system SHALL inform the user that no reliable results were found, returning an empty result list.
- **FR-013**: The API MUST allow limiting the number of results and MUST return metadata sufficient to cite them.
- **FR-014**: The system MUST allow the user to rate each result as helpful or not helpful via thumbs-up / thumbs-down icons, and the rating MUST be associated with the query and the fragment shown.
- **FR-015**: The system MUST discard from the ranking any fragment whose similarity to the query falls below an internal, configurable minimum threshold (not exposed to the end user), applied before the result-count limit of FR-013.

### Entorno de desarrollo

- **FR-016**: WHERE the local development environment is used, the system MUST allow starting the full MVP (backend, database and web interface) with a single command, equivalently on macOS and Windows.
- **FR-017**: The local development environment MUST include example data so search can be exercised end to end without depending on the real, still-undefined ingestion feed.

## Success Criteria

- **SC-001**: At least 95% of ingested records are correctly identified as unique (no duplicate boletines created by repeated ingestion).
- **SC-002**: 100% of returned search results include both a publication date and an official URL.
- **SC-003**: 100% of searches that specify a date filter return only results within that date range.
- **SC-004**: Search response time is under 2 seconds for common queries against the initial corpus.
- **SC-005**: At least 80% of the first representative set of test queries are rated positive in manual evaluation.
- **SC-006**: The local Docker environment starts successfully (all services healthy) with a single command, verified at least once on macOS and once on Windows before the MVP is considered done.

## Clarifications

- **Q**: ¿El umbral de similitud lo controla el usuario final? **A**: No; es un parámetro interno del servicio, no expuesto en la API pública del MVP. (2026-09-16)
- **Q**: ¿Qué ocurre cuando ningún resultado supera el umbral de similitud? **A**: Se devuelve una lista vacía junto con el aviso de "sin resultados confiables"; no se muestran resultados de baja confianza con una advertencia. (2026-09-16)
- **Q**: ¿Qué modelo de embeddings se usa para la búsqueda del MVP? **A**: `Qwen/Qwen3-Embedding-0.6B`, self-hosted, compartido con el tagging de la Etapa 2 para no mantener dos modelos distintos. (2026-09-16)
- **Q**: ¿De dónde viene el texto de los boletines a ingerir? **A**: Se asume un feed estructurado (no scraping de una interfaz web); el formato exacto del feed queda como pregunta abierta. (2026-09-16)
- **Q**: ¿Cuántos contenedores Docker se usan para el MVP? **A**: Tres — un backend consolidado (Ingestor + Procesador + API), la base de datos (PostgreSQL + pgvector) y la interfaz web. (2026-09-16)
- **Q**: ¿Cómo se maneja el modelo de embeddings dentro del contenedor? **A**: Se descarga en el primer arranque y se cachea en un volumen nombrado, en vez de incluirlo en la imagen Docker. (2026-09-16)
- **Q**: ¿Se necesita protección contra abuso (rate limiting) en el MVP? **A**: No, mientras el sistema corra solo en un entorno de desarrollo; queda pendiente antes de exponerlo fuera de ese entorno. (2026-09-16)
