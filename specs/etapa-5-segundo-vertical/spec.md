# Feature: Etapa 5 — Segundo vertical

Framework: spec-kit (track default)
Feature ID: f_01m39qv30dtyfw4mhypkdt2ysb
Fuente: `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md` (v0.2), sección 8 (Etapa 5)

## User Scenarios

### Primary user story

Como operador de una nueva instalación temática, quiero incorporar un vertical distinto al de boletines (licitaciones públicas argentinas) declarando fuentes y filtros propios en un `installation.yaml` nuevo, sin modificar el motor genérico, para validar que la plataforma es realmente reutilizable entre temáticas.

### Acceptance scenarios

1. **Given** una instalación nueva "Licitaciones Argentina" con dos fuentes declaradas (comprar.gob.ar nacional, Boletín Oficial de Córdoba provincial), **When** se levanta el stack contra una base de datos propia, **Then** ambas fuentes se crean vía `upsert_fuentes` sin tocar código del motor.
2. **Given** el conector `comprar-gob-ar-csv` corriendo contra el dataset real de datos.gob.ar, **When** se ejecuta, **Then** descubre licitaciones nacionales dentro de la ventana de fecha configurada y produce un `DocumentoNormalizado` por cada una, con metadata (`organismo`, `monto`, `jurisdiccion="nacional"`).
3. **Given** el conector `boletin-cba-pdf-diario` corriendo contra la 4° Sección del Boletín Oficial de Córdoba de un día real, **When** se ejecuta, **Then** descarga el PDF de esa sección, extrae su texto y produce un `DocumentoNormalizado` con metadata (`jurisdiccion="provincial"`).
4. **Given** la instalación de licitaciones levantada, **When** se declara un filtro `organismo` (selección) y `monto` (rango numérico) en su `installation.yaml`, **Then** `GET /v1/search?filtro.monto=1000000,` filtra usando el mismo módulo `aplicar_filtros` sin cambios de código.
5. **Given** la instalación de boletines existente, **When** se corrige la fuente `cordoba-provincial` para usar el conector `boletin-cba-pdf-diario` contra el sitio argentino real (`boletinoficial.cba.gov.ar`) en vez del sitio español (`bop.dipucordoba.es`), **Then** la ingesta de esa fuente sigue funcionando end-to-end sin cambios en el motor ni en las suscripciones/notificaciones ya construidas.
6. **Given** ambos stacks (boletines y licitaciones) corriendo en paralelo, **When** se ingiere un documento nuevo en cada uno, **Then** cada instalación queda con su propia base de datos, sin mezclar documentos ni fuentes entre sí.

## Functional Requirements

### Conector `comprar-gob-ar-csv`

- **FR-001**: The system MUST implement a connector that downloads the official open-data CSV of national tenders (`Convocatorias.csv`, published at datos.gob.ar) and yields one `DocumentoNormalizado` per row within a configurable date window.
- **FR-002**: The connector MUST use `Numero_Proceso` as `identificador_externo`, `Nombre_del_Proceso` as `titulo`, a concatenation of `Nombre_del_Proceso` and `Objeto_del_Proceso` as `texto`, and populate metadata with `organismo` (from `Descripcion_SAF`), `monto` (parsed from `Monto_Estimado`, a comma-thousands/dot-decimal string, into a plain number) and `jurisdiccion="nacional"`.
- **FR-003**: WHEN a row's `Monto_Estimado` cannot be parsed as a number, the system SHALL still ingest the document, omitting `monto` from its metadata rather than failing the row.
- **FR-004**: The CSV download MUST use an explicit timeout; a download failure MUST fail the whole connector run (per the existing `ejecutar_conector` behavior for connector-level failures), not individual rows.

### Conector `boletin-cba-pdf-diario`

- **FR-005**: The system MUST implement a connector that, given a date and a configured list of section numbers, builds each section's predictable PDF URL on `boletinoficial.cba.gov.ar`, downloads it over plain HTTP (no Scrapy) and extracts its text with the existing `pypdf`-based extraction, reused from the Etapa 2 connector.
- **FR-006**: The connector MUST produce one `DocumentoNormalizado` per (fecha, sección), using `"{sección}_Secc_{ddmmyy}"` as `identificador_externo`.
- **FR-007**: WHEN a given section's PDF is not published for a date (HTTP 404) or its text cannot be extracted, the system SHALL record it as an error for that specific (fecha, sección) within the execution, without failing the rest.
- **FR-008**: Every outbound HTTP request the connector makes MUST have an explicit timeout and a bounded retry count, matching the standard already applied to the Etapa 2 connector.
- **FR-009**: The connector's configuration MUST let an installation choose which section numbers to ingest, so the same connector type serves both the licitaciones installation (section 4 only) and the corrected boletines installation (all sections).

### Instalación "Licitaciones Argentina"

- **FR-010**: A new `installation-licitaciones.yaml` MUST declare both new fuentes (`comprar-ar-nacional` using `comprar-gob-ar-csv`, `cba-provincial-licitaciones` using `boletin-cba-pdf-diario` configured for section 4) and declare `organismo` (selección) and `monto` (rango_numerico) as filters, using the existing `installation.yaml` schema without any change to `src/config/installation.py`.
- **FR-011**: The licitaciones installation MUST run against its own database and its own set of ports, isolated from the boletines installation's stack, using the existing multi-installation architecture (one `installation.yaml` + one deployment per installation) with no engine change.

### Corrección de la fuente `cordoba-provincial` (boletines)

- **FR-012**: The existing `installation.yaml` (boletines) MUST be updated so `cordoba-provincial` uses the `boletin-cba-pdf-diario` connector against `boletinoficial.cba.gov.ar` (the real Argentine site), configured for all 5 sections, replacing the previous `bop-cordoba-scrapy` connector against the Spanish site (`bop.dipucordoba.es`).
- **FR-013**: The existing `bop-cordoba-scrapy` connector's code, registry entry and tests MUST remain in place (unused in production configuration, still a valid Scrapy-connector reference implementation), rather than being deleted, since removing tested code is out of scope for this fix.

## Success Criteria

- **SC-001**: A real run of `comprar-gob-ar-csv` against the real datos.gob.ar CSV, restricted to a bounded date window (for example, the current year), produces at least 1 `DocumentoNormalizado` with `organismo` and `monto` populated in metadata.
- **SC-002**: A real run of `boletin-cba-pdf-diario` against today's real 4° Sección PDF on `boletinoficial.cba.gov.ar` produces exactly 1 `DocumentoNormalizado`, with non-empty extracted text.
- **SC-003**: The licitaciones installation, freshly deployed against an empty database, ends up with exactly 2 fuentes after startup (`upsert_fuentes`), with 0 changes to any file under `src/` outside the two new connector modules and the registry.
- **SC-004**: `GET /v1/search?filtro.monto=1000000,` against the licitaciones installation returns only documents whose metadata `monto` is >= 1,000,000, verified against real ingested data.
- **SC-005**: The corrected boletines installation, run against `boletinoficial.cba.gov.ar`, ingests at least 1 real document per section per day with 0 changes to `src/subscriptions/`, `src/notifications/`, `src/auth/` or `src/api/` (Etapas 3 and 4 keep working unmodified).
- **SC-006**: Both stacks (boletines and licitaciones) run simultaneously via Docker Compose with independent databases and ports; a document ingested in one does not appear in a `GET /v1/search` against the other.
- **SC-007**: 0 tests in the default suite (`pytest` without an explicit `live`/`docker` marker) make a real network call to `datos.gob.ar` or `boletinoficial.cba.gov.ar`; all connector tests run against local fixtures (saved CSV sample and PDF sample).

## Clarifications

- **Q**: ¿Cuál es el segundo vertical y con qué fuente real? **A**: Licitaciones, combinando comprar.gob.ar (nacional, vía el CSV abierto de datos.gob.ar) y la sección de licitaciones del Boletín Oficial de Córdoba, Argentina (provincial) — ambas fuentes en una sola instalación "Licitaciones Argentina". (2026-09-24)
- **Q**: comprar.gob.ar en vivo es ASP.NET con postbacks (`__VIEWSTATE`), frágil para scrapear. **A**: Usar en cambio el dataset oficial abierto (`Convocatorias.csv` en datos.gob.ar), actualizado semestralmente — conector de tipo completamente distinto (HTTP + CSV, sin Scrapy), lo que además valida que un conector puede tener lógica propia sin parecerse al existente. (2026-09-24)
- **Q**: ¿Qué sitio usar para la licitaciones del Boletín de Córdoba, dado que el conector de la Etapa 2 apunta a España (`bop.dipucordoba.es`)? **A**: `boletinoficial.cba.gov.ar`, el sitio real de Córdoba, Argentina — coincide con el dominio ya usado en los fixtures de test del MVP original. Publica 5 secciones diarias como PDFs individuales con URL predecible; la sección 4 ("Notificaciones, Licitaciones y Contrataciones") es la fuente de licitaciones provinciales. (2026-09-24)
- **Q**: `boletinoficial.cba.gov.ar/robots.txt` bloquea explícitamente por nombre a `ClaudeBot` y otros bots de IA (`Disallow: /`), pero no bloquea crawlers genéricos en rutas de contenido. **A**: Construir el conector igual, identificándose con un User-Agent genérico (no uno de los nombres bloqueados) — decisión explícita del usuario; el dato es público y de interés ciudadano, y el propio robots.txt distingue crawlers genéricos (permitidos) de una lista de bots de IA nombrados (bloqueados). (2026-09-24)
- **Q**: Al construir el conector correcto para Córdoba, Argentina, ¿corregimos también la fuente `cordoba-provincial` de la instalación de boletines (Etapa 2), que apunta al sitio equivocado? **A**: Sí, corregirlo dentro de esta misma etapa — se actualiza `installation.yaml` (boletines) para usar `boletin-cba-pdf-diario` contra el sitio argentino real; el conector `bop-cordoba-scrapy` (España) queda en el código sin usarse en producción, no se borra. (2026-09-24)
- **Q**: ¿Una sola instalación de licitaciones o dos separadas (nacional/provincial)? **A**: Una sola ("Licitaciones Argentina"), con ambas fuentes y un filtro `jurisdiccion` (vía metadata) para distinguirlas si hace falta — sigue siendo una sola temática coherente (licitaciones argentinas). (2026-09-24)
- **Q**: ¿Cómo se verifica de verdad que el motor es reutilizable? **A**: Levantando un segundo stack Docker real y completo (base de datos y puertos propios) en paralelo al de boletines, con ingesta real contra los sitios/datasets reales — no solo tests con fixtures. (2026-09-24)
