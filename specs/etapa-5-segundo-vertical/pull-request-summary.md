# Pull request — Etapa 5: segundo vertical

Feature ID: `f_01m39qv30dtyfw4mhypkdt2ysb` · Framework: spec-kit

Nota: igual que las etapas anteriores, este trabajo se hizo directo sobre `main` (sin rama separada), así que este documento cumple el rol del resumen de PR que pide la fase `integrate`, sin un pull request real de GitHub que mergear.

## Historia de usuario

Como operador de una nueva instalación temática, quiero incorporar un vertical distinto al de boletines (licitaciones públicas argentinas) declarando fuentes y filtros propios en un `installation.yaml` nuevo, sin modificar el motor genérico, para validar que la plataforma es realmente reutilizable entre temáticas.

## Requisitos funcionales implementados

FR-001 a FR-013 (`spec.md`, Etapa 5 completa): dos conectores nuevos con lógica genuinamente distinta entre sí y del conector Scrapy existente (`comprar-gob-ar-csv`, streaming de un CSV abierto de 55MB con parseo de moneda argentina; `boletin-cba-pdf-diario`, HTTP directo por `curl` contra URLs predecibles), una instalación "Licitaciones Argentina" nueva con sus propios filtros declarados (`organismo`, `monto`) sin ningún cambio al motor, y la corrección de la fuente `cordoba-provincial` (apuntaba al sitio equivocado desde la Etapa 2 — España en vez de Argentina).

## Resumen de evidencia

- 136/136 tests automatizados en verde (`pytest -m "not slow and not docker and not live"`), lint (`ruff`) en 0, smoke Docker real en verde (`pytest -m docker`, reconstruye la imagen con `curl` instalado).
- **Verificación real con dos stacks de Docker Compose corriendo en paralelo** (proyecto de Compose separado, bases de datos y puertos propios): el stack de licitaciones terminó con exactamente 2 fuentes reales y miles de documentos reales ingeridos desde el dataset nacional de comprar.gob.ar (organismo y monto poblados); el filtro `monto` se verificó contra esos datos reales (50/50 resultados muestreados cumplen el umbral, 188 documentos reales lo superan); se confirmó aislamiento total entre ambos stacks con búsquedas cruzadas reales; el stack de boletines, ya corregido, siguió funcionando de punta a punta (registro, login, notificaciones) sin tocar ninguna de sus etapas anteriores.
- **Una limitación real de CloudFront/WAF** (no un bug de código) quedó documentada: `boletinoficial.cba.gov.ar` empezó a devolver 403 sostenido tras varias descargas de prueba en poco tiempo — confirmado con `curl -v` que es un bloqueo de CloudFront, no de la aplicación. El camino feliz del conector ya estaba probado con una descarga real exitosa (200, 3.8MB, texto extraído) antes de que empezara el bloqueo; el manejo de error (FR-007) también se probó real, dos veces, con el mismo resultado correcto.
- 5 bugs/decisiones reales encontrados y resueltos durante `implement`, todos con decisión explícita del usuario: fuente `cordoba-provincial` apuntaba a España en vez de Argentina (bug preexistente de la Etapa 2, corregido acá); `boletinoficial.cba.gov.ar/robots.txt` bloquea bots de IA por nombre pero no crawlers genéricos (se procedió con un User-Agent genérico); `urllib` recibe 403 de ese sitio pero `curl` recibe 200 (el conector usa `curl` como subproceso); `sembrar_si_vacio` sembraba datos del Boletín en cualquier instalación nueva (se agregó un flag `seed` a `InstallationConfig`); una corrida sin límite de `comprar-gob-ar-csv` superó los 5600 documentos reales antes de cancelarla (se agregó `limite_filas`, con un gap de cobertura parcial permanente documentado y aceptado). Detalle completo en `verify-evidence.md`.
- Sin dependencias Python nuevas: ambos conectores usan la librería estándar (`urllib`, `csv`) o `curl` como herramienta del sistema (agregada al `Dockerfile`, no a `pyproject.toml`).

## Enlaces

- `specs/etapa-5-segundo-vertical/spec.md`
- `specs/etapa-5-segundo-vertical/plan.md`
- `specs/etapa-5-segundo-vertical/tasks.md`
- `specs/etapa-5-segundo-vertical/verify-evidence.md`
- `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md`

## Estado de merge

Ya integrado a `main` (commits `86f9c59`..`43a08b6`). No requiere un merge adicional. Falta hacer `git push` al remoto — no se hizo en esta sesión porque no se pidió explícitamente.
