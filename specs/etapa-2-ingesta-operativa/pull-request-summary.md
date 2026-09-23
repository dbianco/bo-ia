# Pull request — Etapa 2: ingesta operativa

Feature ID: `f_01m37nm2axpsc7gyjt6sq9vktt` · Framework: spec-kit

Nota: igual que las etapas anteriores, este trabajo se hizo directo sobre `main` (sin rama separada), así que este documento cumple el rol del resumen de PR que pide la fase `integrate`, sin un pull request real de GitHub que mergear.

## Historia de usuario

Como operador de la instalación, quiero que el sistema descubra e incorpore automáticamente nuevos documentos del Boletín Oficial de la Provincia de Córdoba según una frecuencia configurada, sin intervención manual, para no depender de cargar cada documento a mano vía la API.

## Requisitos funcionales implementados

FR-001 a FR-013 (`spec.md`, Etapa 2 completa): `ejecuciones_fuente` (inicio, fin, estado, descubiertos, nuevos, existentes, errores, versión de conector), interfaz `Conector` + `ejecutar_conector`, el primer conector real (BOP Córdoba: Scrapy + extracción de PDF con `pypdf`, en subproceso propio por corrida), scheduler in-process con APScheduler, ejecución manual (`POST /v1/fuentes/{clave}/ejecutar`), y bloque `conector` opcional en `installation.yaml`.

## Resumen de evidencia

- 81 tests automatizados en verde (`pytest --ignore=tests/smoke -m "not live"`), lint (`ruff`) en 0, smoke Docker real en verde (reconstruye con las dependencias nuevas — scrapy/twisted/apscheduler/pypdf — y arranca con el scheduler wireado).
- Conector real verificado contra `bop.dipucordoba.es` en el host: 30/30 documentos, 0 errores, mismo conteo que el PoC de scraping que motivó esta etapa.
- 2 hallazgos reales, documentados como gaps abiertos (ninguno bloquea un FR/SC): Scrapy corre notablemente más lento dentro de este contenedor Docker de desarrollo que en el host (mitigado subiendo el timeout de proceso); el endpoint de ejecución manual es sincrónico sin timeout HTTP propio, y una corrida real quedó sin resolverse dentro de esta sesión por contención de memoria de otros contenedores no relacionados en esta máquina. Detalle completo en `verify-evidence.md`.
- Se commiteó además el PoC de scraping (`docs/superpowers/reports/2026-09-23-scraping-poc.md`, `poc/scraping/`) que esta etapa cita como fuente de la decisión de usar Scrapy, y que había quedado sin commitear de una sesión anterior.

## Enlaces

- `specs/etapa-2-ingesta-operativa/spec.md`
- `specs/etapa-2-ingesta-operativa/plan.md`
- `specs/etapa-2-ingesta-operativa/tasks.md`
- `specs/etapa-2-ingesta-operativa/verify-evidence.md`
- `docs/superpowers/reports/2026-09-23-scraping-poc.md`
- `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md`

## Estado de merge

Ya integrado a `main` (commits `eb26c39`..`5b22dd1`). No requiere un merge adicional. Falta hacer `git push` al remoto — no se hizo en esta sesión porque no se pidió explícitamente.
