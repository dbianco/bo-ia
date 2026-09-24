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

Modificados:

- `installation.yaml` (corrige `cordoba-provincial`: conector `boletin-cba-pdf-diario` contra `boletinoficial.cba.gov.ar`, ya no `bop-cordoba-scrapy` contra España)
- `backend/src/connectors/registry.py` (registra los 2 conectores nuevos)
- `README.md`
- `.github/workflows/ci.yml` (si hace falta excluir el marker `live` de los tests nuevos; ya excluido globalmente desde la Etapa 2)

Nuevos:

- `installation-licitaciones.yaml`
- `.env.licitaciones.example`
- `docker-compose.licitaciones.override.yml`
- `backend/src/connectors/comprar_gob_ar/__init__.py`
- `backend/src/connectors/comprar_gob_ar/connector.py` (`ConectorComprarGobAr`, parseo de CSV y montos)
- `backend/src/connectors/boletin_cba/__init__.py`
- `backend/src/connectors/boletin_cba/connector.py` (`ConectorBoletinCba`, construcción de URL por sección/fecha, descarga y extracción de PDF reusando `src/connectors/bop_cordoba/pdf.py`)
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

## Research

- **`urllib.request` en vez de `httpx`/`requests` para ambos conectores nuevos:** ninguno de los dos necesita las features de una librería HTTP completa (sesiones, reintentos automáticos, async); un `Request` con `timeout` explícito y un `for` con reintentos manuales alcanza, siguiendo el criterio ya usado para hash de contraseña y correo (Etapas 3 y 4): preferir la librería estándar antes que sumar una dependencia.
- **CSV en streaming, no descargado entero a memoria:** `Convocatorias.csv` pesa ~55MB y crece con cada actualización semestral; `csv.DictReader(codecs.iterdecode(response, "latin-1"))` sobre la respuesta de `urlopen` permite filtrar por `Ejercicio` fila por fila sin acumular el archivo completo. (El sample real mostró un carácter mal decodificado en UTF-8 — `Agrupaci�n` — que sugiere que el CSV está en `latin-1`/`cp1252`; se confirma y ajusta al implementar.)
- **Monto: parseo manual del formato argentino, no un parser de moneda:** `Monto_Estimado` viene como `"1,735,400.00"` (coma de miles, punto decimal) — alcanza con `float(valor.replace(",", ""))`, sin sumar una dependencia de formato de moneda.
- **`boletin-cba-pdf-diario` sin Scrapy, HTTP directo:** a diferencia del conector de la Etapa 2 (que necesita seguir links descubiertos en HTML), este sitio publica sus 5 secciones diarias en URLs 100% predecibles (`{base_url}/wp-content/4p96humuzp/{año}/{mes}/{sección}_Secc_{ddmmyy}.pdf`, confirmado navegando el sitio real) — no hace falta descubrir nada, solo construir la URL y descargar. Se reusa `extraer_texto_pdf` de `src/connectors/bop_cordoba/pdf.py` tal cual, sin duplicarlo.
- **User-Agent genérico, no el default de `urllib` (`Python-urllib/x.y`) ni un nombre de bot de IA:** `boletinoficial.cba.gov.ar/robots.txt` bloquea por nombre a `ClaudeBot` y otros bots de IA, pero no a crawlers genéricos en rutas de contenido (decisión ya tomada en `spec.md`). Se declara un User-Agent descriptivo propio (`bo-ia-connector/1.0`), ni el default de la librería ni uno de los nombres bloqueados.
- **Segundo stack por override de Compose, no un `docker-compose.yml` duplicado:** duplicar el archivo entero crearía dos fuentes de verdad que divergen con el tiempo. Un override que solo reemplaza el volumen de `installation.yaml` del backend, combinado con `-p bo-ia-licitaciones` (namespacing automático de red/volúmenes por proyecto de Compose) y un `.env.licitaciones` con puertos y `POSTGRES_DB` distintos, es suficiente y no duplica configuración de servicios.
- **`bop-cordoba-scrapy` no se borra:** sigue registrado en `registry.py` y sus tests siguen pasando; solo deja de estar referenciado desde `installation.yaml`. Se documenta en `README.md` como conector de referencia sin uso en producción, en vez de eliminar código ya probado (decisión ya tomada en `spec.md`, FR-013).
