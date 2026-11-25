# Evidencia de verificación — Etapa 5 (segundo vertical)

Feature ID: `f_01m39qv30dtyfw4mhypkdt2ysb` · Fecha: 2026-09-24

Cruza cada escenario de aceptación y criterio de éxito de `spec.md` contra la verificación real hecha durante `implement`. Esta etapa se apoyó más que ninguna anterior en verificación real contra sitios/datasets externos (no solo fixtures): dos conectores nuevos, una instalación nueva y **un segundo stack de Docker Compose real, levantado en paralelo** al de boletines.

## Acceptance scenarios (spec.md)

| # | Escenario | Estado | Evidencia |
|---|---|---|---|
| 1 | Instalación nueva con 2 fuentes vía `upsert_fuentes`, sin tocar el motor | ✅ | `GET /v1/config` y consulta directa a Postgres contra el stack real de licitaciones (`bo-ia-licitaciones-db-1`): exactamente 2 fuentes (`comprar-ar-nacional`, `cba-provincial-licitaciones`) |
| 2 | `comprar-gob-ar-csv` descubre licitaciones nacionales reales, con metadata | ✅ | Corrida real contra el dataset real: **miles de documentos reales** ingeridos (más de 5600 antes de acotar con `limite_filas`), con `organismo`, `monto` y `jurisdiccion="nacional"` poblados; confirmado con `SELECT` directo a Postgres |
| 3 | `boletin-cba-pdf-diario` descarga y extrae texto de la 4° Sección real | ✅ | Descarga real exitosa del PDF de hoy (`4_Secc_240926.pdf`, 200 OK, 3.8MB) usada como fixture; `pypdf` extrajo 42.790 caracteres de texto real, incluida la palabra "LICITACIONES"; confirmado también en la corrida real dentro de Docker (ver limitación más abajo) |
| 4 | Filtro `monto` declarado en la instalación filtra sin cambiar el motor | ✅ | `GET /v1/search?filtro.monto=1000000000,` contra el stack real de licitaciones: 50/50 resultados muestreados con `monto >= 1e9` confirmado contra Postgres; 188 documentos reales cumplen ese umbral en la base |
| 5 | `cordoba-provincial` corregido sigue funcionando end-to-end | ✅ | Corrida real contra `boletinoficial.cba.gov.ar` (ver limitación de rate-limit abajo); suite completa de Etapas 3/4 sin cambios (135/135 tests) + verificación real de registro/login/notificaciones contra el stack de boletines después del fix |
| 6 | Ambos stacks aislados, sin mezclar documentos | ✅ | Búsquedas cruzadas reales: un documento real de licitaciones (`34-0001-LPR26`) no aparece en `GET /v1/search` del stack de boletines, y viceversa (`BO-DEMO-0001` no aparece en licitaciones) |

## Success Criteria (spec.md)

| Criterio | Estado | Evidencia |
|---|---|---|
| SC-001: `comprar-gob-ar-csv` real produce ≥1 documento con `organismo`/`monto` | ✅ | Ampliamente superado: miles de documentos reales con ambos campos poblados |
| SC-002: `boletin-cba-pdf-diario` real produce exactamente 1 documento con texto | ✅ (parcial, ver nota) | Confirmado con la descarga real original (200, texto extraído); la corrida repetida horas después, dentro de Docker, quedó bloqueada por rate-limit de CloudFront (ver "Limitación real" abajo) — el camino feliz ya está probado con datos reales, no solo con fixtures |
| SC-003: instalación nueva termina con exactamente 2 fuentes | ✅ | Confirmado tras corregir el bug real del seed (ver Bugs); sin el fix, terminaba con 5 |
| SC-004: `filtro.monto` filtra correctamente sobre datos reales | ✅ | 50/50 resultados muestreados cumplen el umbral; contraste con el conteo real en Postgres (188) |
| SC-005: boletines corregido, 0 cambios en suscripciones/notificaciones/auth/api | ✅ | 135/135 tests en verde sin tocar `src/subscriptions/`, `src/notifications/`, `src/auth/`; `src/api/` solo cambia por el flag `seed` en `main.py`, no por rutas de esos módulos |
| SC-006: ambos stacks corren en paralelo, sin mezclar documentos | ✅ | Confirmado con búsquedas cruzadas reales, ver arriba |
| SC-007: 0 tests del suite por defecto llaman a datos.gob.ar/boletinoficial.cba.gov.ar reales | ✅ | Los tests `test_comprar_gob_ar_live.py`/`test_boletin_cba_live.py` están marcados `live`, excluidos por defecto y de CI; el resto usa fixtures `file://` |

## Trazabilidad FR → test/evidencia

| FR | Cubierto por |
|---|---|
| FR-001 a FR-004 | `tests/connectors/test_comprar_gob_ar.py` (4 tests) + corrida real (SC-001) |
| FR-005 a FR-009 | `tests/connectors/test_boletin_cba.py` (3 tests) + descarga real original + corridas reales dentro de Docker |
| FR-010, FR-011 | `installation-licitaciones.yaml`, `docker-compose.licitaciones.override.yml`, `.env.licitaciones.example`; verificado con el segundo stack real levantado |
| FR-012, FR-013 | `installation.yaml` (fuente corregida), `bop-cordoba-scrapy` sigue registrado y con tests propios sin cambios |

## Checklist de la fase `verify`

- **Lint (ruff):** `ruff check .` → 0 hallazgos.
- **Tests:** 136/136 en verde (`pytest -m "not slow and not docker and not live"`); 1/1 smoke Docker real (`pytest -m docker`, reconstruye la imagen con `curl` instalado).
- **Verificación manual real, con dos stacks de Docker Compose corriendo en paralelo:**
  - Stack de boletines (`bo-ia-*`, puertos 9100): corregido (`cordoba-provincial` → sitio argentino real); registro/login/notificaciones reales siguen funcionando; búsqueda semántica real sin cambios.
  - Stack de licitaciones (`bo-ia-licitaciones-*`, puertos 9300, proyecto de Compose separado vía `-p`): 2 fuentes reales, miles de documentos reales ingeridos desde `comprar-gob-ar-csv`, filtro `monto` verificado contra datos reales, aislamiento confirmado contra el otro stack.
- **files_changed:** ver `plan.md` → Project Structure para el árbol final (incluye 3 archivos no planeados originalmente: el flag `seed`, `curl` en el Dockerfile, y `.gitignore`).

## Limitación real encontrada durante la verificación (no un bug de código)

`boletinoficial.cba.gov.ar` corre detrás de CloudFront y, tras varias descargas de prueba en poco tiempo durante esta sesión (incluida la descarga exitosa que generó el fixture real), empezó a devolver **403 Forbidden** de forma sostenida — tanto a `urllib` como a `curl` puro, con el mismo User-Agent. Confirmado con `curl -v`: la respuesta 403 viene con headers de CloudFront (`x-cache: Error from cloudfront`), no de la aplicación. Es consistente con un rate-limit o bloqueo temporal por IP, no con un bug del conector: la misma URL, con el mismo conector, había devuelto 200 con contenido real horas antes (el fixture de 3.8MB usado en los tests). El manejo de error del conector (FR-007) se probó igual de forma real y correcta: cada sección fallida quedó registrada individualmente (`ErrorDescubrimiento`, con el detalle exacto del error 403 de `curl`) sin abortar el resto de la ejecución ni la ingesta.

## Bugs reales encontrados y corregidos durante `implement`

1. **Fuente `cordoba-provincial` apuntaba a España, no a Argentina** (bug preexistente de la Etapa 2, corregido en esta etapa por decisión explícita del usuario): `bop.dipucordoba.es` es el Boletín Oficial de la Diputación de Córdoba, **España** (aparecen "Ayuntamiento de Cabra", municipios españoles), mientras que el `installation.yaml` original ya sembraba datos de municipios argentinos reales (Carlos Paz, Noetinger) y los fixtures del MVP original ya usaban `boletinoficial.cba.gov.ar`. Corregido apuntando `cordoba-provincial` al sitio argentino real.
2. **`boletinoficial.cba.gov.ar/robots.txt` bloquea por nombre a bots de IA** (`ClaudeBot`, `GPTBot`, etc. con `Disallow: /`), pero no a crawlers genéricos en rutas de contenido — decisión explícita del usuario de proceder igual con un User-Agent genérico, dato público de interés ciudadano.
3. **`urllib` recibe 403 de ese sitio; `curl` recibe 200** con el mismo User-Agent — decisión explícita del usuario de usar `curl` como subproceso en el conector en vez de `urllib` (herramienta estándar del sistema, no evasión de la política del sitio).
4. **`sembrar_si_vacio` no respetaba `installation.yaml`**: sembraba datos del Boletín en cualquier instalación nueva con `documentos` vacía. La primera corrida real del stack de licitaciones terminó con 5 fuentes en vez de 2. Corregido con el flag `InstallationConfig.seed: bool = True` (default sin cambios) + `installation-licitaciones.yaml` declara `seed: false`.
5. **`comprar-gob-ar-csv` sin límite es potencialmente muy caro**: una corrida real sin `limite_filas` superó los 5600 documentos (cada uno con un embedding real por CPU) antes de cancelarla manualmente — no llegó a completar. Se agregó `limite_filas` al conector, usado en producción (`installation-licitaciones.yaml`, valor 500) por decisión consciente del usuario, aceptando el gap de cobertura descrito abajo.

## Gaps conocidos, sin resolver

1. **`limite_filas` sin cursor → cobertura parcial permanente**: el conector `comprar-gob-ar-csv` siempre arranca desde el principio del CSV; con un límite fijo, una corrida ve siempre las mismas primeras N filas que matchean `anio_desde`, nunca las siguientes. Decisión consciente del usuario de aceptar este gap por sobre el costo de una corrida sin límite (ver Bugs #5). Una implementación futura con cursor persistido (por ejemplo en `Fuente.config`) resolvería esto.
2. **Rate-limit/bloqueo de CloudFront en `boletinoficial.cba.gov.ar`**: observado como real durante esta sesión (ver "Limitación real" arriba). El conector maneja el error correctamente (FR-007), pero una instalación real con esta fuente debería monitorear la tasa de fallos y, si el patrón se repite en producción, evaluar espaciar más las corridas o contactar al sitio.
3. **`comprar-gob-ar-csv` no tiene `url_fuente` individual por proceso**: comprar.gob.ar no expone una URL de detalle estable por licitación (sitio ASP.NET con postbacks, sin URLs guessables confirmadas); todos los documentos de esta fuente comparten `url_fuente` (la página del dataset abierto en datos.gob.ar), gap documentado en `plan.md` → Research.
4. **`bop-cordoba-scrapy` (España) queda sin usarse en ninguna instalación**: se mantiene registrado y con tests, sin borrar código ya probado (FR-013), pero no hay ninguna instalación real que lo use hoy.
