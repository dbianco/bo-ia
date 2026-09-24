# Plan: Etapa 5 — Segundo vertical

Framework: spec-kit (track default)
Feature ID: f_01m39qv30dtyfw4mhypkdt2ysb
Fuente: `spec.md` de esta feature

## Technical Context

- **Lenguaje y versión:** Python 3.12, mismo backend consolidado.
- **Dependencias nuevas:** ninguna. Ambos conectores usan `urllib.request` (librería estándar) para las descargas HTTP, siguiendo el mismo criterio ya aplicado a hash de contraseña (Etapa 3) y envío de correo (Etapa 4): preferir la librería estándar antes que sumar una dependencia (`httpx`/`requests`) para una necesidad de infraestructura. El parseo del CSV usa el módulo estándar `csv`. La extracción de PDF reusa `pypdf` (ya instalado desde la Etapa 2).
- **Almacenamiento:** ningún cambio de esquema. Ambas fuentes nuevas usan las tablas ya existentes (`fuentes`, `documentos`, `fragmentos`, `ejecuciones_fuente`); no hay migración Alembic en esta etapa.
- **Herramientas de testing:** pytest, más fixtures reales bajo `backend/tests/fixtures/comprar_gob_ar/` (una muestra real acotada del CSV real) y `backend/tests/fixtures/boletin_cba/` (un PDF real de una sección, descargado una vez y guardado como fixture), consumidas vía URLs `file://`. Se agrega el marker `live` a los tests que sí pegan contra datos.gob.ar/boletinoficial.cba.gov.ar reales (mismo patrón que la Etapa 2), excluidos del run por defecto y de CI.
- **Plataforma objetivo:** un segundo stack de Docker Compose real, en paralelo al existente, usando el mismo `docker-compose.yml` con un archivo de override (`docker-compose.licitaciones.override.yml`, monta `installation-licitaciones.yaml` en vez de `installation.yaml`) y un `.env.licitaciones` propio (puertos y nombre de base de datos distintos), levantado como un proyecto de Compose separado (`-p bo-ia-licitaciones`). No se toca `docker-compose.yml` para esto — el override alcanza.
- **Objetivos de performance y restricciones:** el CSV de `Convocatorias.csv` pesa ~55MB con datos desde 2016; el conector lo procesa en streaming (`csv.DictReader` sobre el response iterado línea a línea, nunca cargado entero en memoria) y descarta filas fuera de la ventana de fecha configurada (`anio_desde`) sin acumularlas.

## Constitution Check

- **Sin datos personales en logs:** sin cambios; licitaciones y notificaciones oficiales son actos públicos, igual que el Boletín.
- **Timeout y retry en llamadas HTTP salientes:** ambos conectores nuevos fijan un timeout explícito en cada `urllib.request.urlopen` (descarga del CSV, descarga de cada PDF de sección) y un número acotado de reintentos, mismo criterio que FR-009 de la Etapa 2.
- **Migraciones de esquema reversibles con rollback probado:** no aplica; esta etapa no cambia el esquema.
- **Cambios de API pública aditivos:** no se agrega ni cambia ningún endpoint; `GET /v1/search` y `GET /v1/config` siguen funcionando igual, ahora también contra la instalación de licitaciones (misma API, otra base de datos).
- **Secretos desde el entorno:** sin cambios; ambas fuentes son datos públicos sin autenticación.
- **Tests en CI antes de mergear:** se agregan al mismo `ci.yml`; los tests marcados `live` quedan excluidos, igual que en la Etapa 2.
- **Accesibilidad:** no aplica; esta etapa no toca la interfaz web.

## Project Structure

Lista final real, actualizada tras `implement`.

Modificados (difiere de la lista inicial: ver Research para el porqué de cada agregado no planeado):

- `installation.yaml` (corrige `cordoba-provincial`: conector `boletin-cba-pdf-diario` contra `boletinoficial.cba.gov.ar`, ya no `bop-cordoba-scrapy` contra España)
- `backend/src/connectors/registry.py` (registra los 2 conectores nuevos)
- `backend/src/config/installation.py` (agrega `seed: bool = True` — no planeado, ver Research)
- `backend/src/api/main.py` (respeta `installation.seed` antes de llamar a `sembrar_si_vacio` — no planeado)
- `backend/tests/config/test_installation.py` (tests del flag `seed` — no planeado)
- `backend/Dockerfile` (instala `curl` — no planeado, ver Research)
- `.gitignore` (agrega `.env.licitaciones` — no planeado)
- `README.md`

Nuevos:

- `installation-licitaciones.yaml`
- `.env.licitaciones.example`
- `docker-compose.licitaciones.override.yml`
- `backend/src/connectors/comprar_gob_ar/__init__.py`
- `backend/src/connectors/comprar_gob_ar/connector.py` (`ConectorComprarGobAr`, parseo de CSV y montos, `limite_filas`)
- `backend/src/connectors/boletin_cba/__init__.py`
- `backend/src/connectors/boletin_cba/connector.py` (`ConectorBoletinCba`, construcción de URL por sección/fecha, descarga por `curl` y extracción de PDF reusando `src/connectors/bop_cordoba/pdf.py`)
- `backend/tests/fixtures/comprar_gob_ar/convocatorias_sample.csv`
- `backend/tests/fixtures/boletin_cba/4_Secc_sample.pdf`
- `backend/tests/connectors/test_comprar_gob_ar.py`
- `backend/tests/connectors/test_comprar_gob_ar_live.py` (marcado `live`)
- `backend/tests/connectors/test_boletin_cba.py`
- `backend/tests/connectors/test_boletin_cba_live.py` (marcado `live`)
- `specs/etapa-5-segundo-vertical/spec.md`
- `specs/etapa-5-segundo-vertical/plan.md`
- `specs/etapa-5-segundo-vertical/tasks.md`
- `specs/etapa-5-segundo-vertical/verify-evidence.md`

No modificado (a diferencia de lo planeado): `.github/workflows/ci.yml` no necesitó cambios — el marker `live` ya estaba excluido desde la Etapa 2 y los tests nuevos lo reusan sin declarar nada nuevo.

## Research

- **`urllib.request` en vez de `httpx`/`requests` para ambos conectores nuevos:** ninguno de los dos necesita las features de una librería HTTP completa (sesiones, reintentos automáticos, async); un `Request` con `timeout` explícito y un `for` con reintentos manuales alcanza, siguiendo el criterio ya usado para hash de contraseña y correo (Etapas 3 y 4): preferir la librería estándar antes que sumar una dependencia.
- **CSV en streaming, no descargado entero a memoria:** `Convocatorias.csv` pesa ~55MB y crece con cada actualización semestral; `csv.DictReader(codecs.iterdecode(response, "latin-1"))` sobre la respuesta de `urlopen` permite filtrar por `Ejercicio` fila por fila sin acumular el archivo completo. (El sample real mostró un carácter mal decodificado en UTF-8 — `Agrupaci�n` — que sugiere que el CSV está en `latin-1`/`cp1252`; se confirma y ajusta al implementar.)
- **Monto: parseo manual del formato argentino, no un parser de moneda:** `Monto_Estimado` viene como `"1,735,400.00"` (coma de miles, punto decimal) — alcanza con `float(valor.replace(",", ""))`, sin sumar una dependencia de formato de moneda.
- **`boletin-cba-pdf-diario` sin Scrapy, HTTP directo:** a diferencia del conector de la Etapa 2 (que necesita seguir links descubiertos en HTML), este sitio publica sus 5 secciones diarias en URLs 100% predecibles (`{base_url}/wp-content/4p96humuzp/{año}/{mes}/{sección}_Secc_{ddmmyy}.pdf`, confirmado navegando el sitio real) — no hace falta descubrir nada, solo construir la URL y descargar. Se reusa `extraer_texto_pdf` de `src/connectors/bop_cordoba/pdf.py` tal cual, sin duplicarlo.
- **User-Agent genérico, no el default de `urllib` (`Python-urllib/x.y`) ni un nombre de bot de IA:** `boletinoficial.cba.gov.ar/robots.txt` bloquea por nombre a `ClaudeBot` y otros bots de IA, pero no a crawlers genéricos en rutas de contenido (decisión ya tomada en `spec.md`). Se declara un User-Agent descriptivo propio (`bo-ia-connector/1.0`), ni el default de la librería ni uno de los nombres bloqueados.
- **Segundo stack por override de Compose, no un `docker-compose.yml` duplicado:** duplicar el archivo entero crearía dos fuentes de verdad que divergen con el tiempo. Un override que solo reemplaza el volumen de `installation.yaml` del backend, combinado con `-p bo-ia-licitaciones` (namespacing automático de red/volúmenes por proyecto de Compose) y un `.env.licitaciones` con puertos y `POSTGRES_DB` distintos, es suficiente y no duplica configuración de servicios.
- **`bop-cordoba-scrapy` no se borra:** sigue registrado en `registry.py` y sus tests siguen pasando; solo deja de estar referenciado desde `installation.yaml`. Se documenta en `README.md` como conector de referencia sin uso en producción, en vez de eliminar código ya probado (decisión ya tomada en `spec.md`, FR-013).

### Hallazgos reales durante `implement` (no anticipados en el plan original)

- **CSV real en UTF-8, no `latin-1`/`cp1252` como se sospechaba:** el mojibake observado en la muestra inicial (`Agrupaci�n`) resultó ser el efecto de decodificar bytes UTF-8 como `latin-1` en una inspección manual previa, no el encoding real del archivo — confirmado decodificando los bytes crudos como UTF-8 sin error. El conector usa `utf-8` directamente.
- **`boletinoficial.cba.gov.ar` devuelve 403 a `urllib` pero 200 a `curl` con el mismo User-Agent:** confirmado en real, con y sin headers `Accept`/`Accept-Language` adicionales — es casi seguro un bloqueo de CloudFront/WAF por fingerprint de TLS/HTTP2, no por el User-Agent. El conector `boletin-cba-pdf-diario` descarga vía `subprocess.run(["curl", ...])` en vez de `urllib.request`; `curl` se agrega al `Dockerfile` del backend (no estaba antes, la imagen `python:3.12-slim` no lo trae).
- **CloudFront/WAF de ese sitio parece aplicar rate-limiting real:** tras varias descargas de prueba en poco tiempo (incluida la descarga exitosa del fixture), tanto `urllib` como `curl` puro empezaron a devolver 403 de forma sostenida. Se documenta como limitación real de la verificación en vivo de esta etapa (ver `verify-evidence.md`), sin seguir insistiendo contra el sitio real para no generar más tráfico desde la misma IP.
- **`sembrar_si_vacio` (seed) es específico del Boletín y no respetaba la instalación:** se dispara en cualquier instalación con `documentos` vacía, sin mirar `installation.yaml` — la primera corrida del stack de licitaciones terminó con 5 fuentes (2 reales + 3 del seed del Boletín) en vez de 2. Corregido agregando `InstallationConfig.seed: bool = True` (default no rompe la instalación de boletines) y `installation-licitaciones.yaml` declara `seed: false`.
- **`comprar-gob-ar-csv` sin límite puede matchear miles de filas reales:** una corrida real con `anio_desde: 2026` (sin `limite_filas`) superó los 5600 documentos ingeridos (cada uno con un embedding real por CPU) antes de cancelarla manualmente. Se agregó `limite_filas` al conector; `installation-licitaciones.yaml` lo usa en 500 para producción, con un gap conocido y aceptado (ver FR/SC más abajo y `verify-evidence.md`): sin cursor, una corrida siempre ve las mismas primeras N filas que matchean `anio_desde`, nunca cubre progresivamente el resto — decisión consciente de acotar el costo de cada corrida por sobre la cobertura completa.
