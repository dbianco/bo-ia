# Reporte de PoC: herramientas open source para ingesta operativa

## Decisión

Podemos usar herramientas existentes. La recomendación es **Scrapy como motor
principal de conectores HTTP** y **Playwright solo como fallback para fuentes
que requieran JavaScript o interacción de navegador**.

No conviene desarrollar un crawler desde cero ni introducir Crawlee todavía.
La Etapa 2 necesita scheduler, reintentos, estados y observabilidad alrededor
del conector; no necesita un lenguaje declarativo universal.

## Alcance probado

- Fuente: `https://bop.dipucordoba.es/dia/05-06-2026`.
- Extracción: anuncios, título, organismo, fecha, URL del PDF e identificador.
- Normalización al contrato `DocumentoNormalizado` de la especificación.
- Comprobación de identificadores únicos, como proxy de idempotencia.
- Ejecución real con HTTP y navegador headless.

La PoC es descartable y vive en `poc/scraping/`; no modifica el backend ni sus
dependencias.

## Resultados medidos

| Herramienta | HTTP | Documentos | IDs únicos | Tiempo |
|---|---:|---:|---:|---:|
| Scrapy spider real | 200 | 30 | 30 | 5,000 s |
| Playwright + Chrome | 200 | 30 | 30 | 5,209 s |

Ambos produjeron el mismo primer documento y la misma URL de PDF. El HTML de
la fuente ya contiene los anuncios; no fue necesario ejecutar JavaScript para
descubrirlos. La medición de Scrapy usa un spider real con su downloader,
scheduler y `RETRY_TIMES=2`.

## Evaluación operativa

### Scrapy

Encaja mejor con la aplicación actual:

- Es Python, igual que el backend.
- Modela cada fuente como un spider y entrega items simples.
- Tiene pipelines para validación, deduplicación y persistencia.
- Tiene scheduler, middleware de descarga, reintentos y estadísticas del crawl.
- Exporta JSON/JSONL si se quiere desacoplar descubrimiento de ingesta.

La documentación oficial describe esa separación entre spiders, items,
scheduler, downloader middleware, pipelines y feed exports:
[Scrapy building blocks](https://docs.scrapy.org/en/latest/topics/concepts.html).

### Playwright

Es útil, pero no debería ser el núcleo de la ingesta:

- Resuelve páginas renderizadas por JavaScript, formularios, sesiones y
  navegación interactiva.
- Requiere navegador y sus binarios, con mayor consumo y tiempo de ejecución.
- Por sí solo no ofrece el modelo completo de crawling operativo que necesita
  la Etapa 2; habría que agregar scheduler, reintentos, deduplicación,
  límites, métricas y persistencia.

La API Python oficial soporta Chromium, Firefox y WebKit:
[Playwright Python](https://playwright.dev/python/docs/library).

### Crawlee

Es una alternativa válida para investigar si aparecen muchas fuentes dinámicas:
combina crawlers HTTP y Playwright, con throttling, reintentos y escalado.
Pero introduce una segunda capa de abstracción y su ventaja no fue necesaria
en esta fuente. La documentación de Crawlee for Python confirma ambos modos:
[HTTP crawlers y Playwright crawler](https://crawlee.dev/python/docs/guides).

## Cómo integrarlo en la Etapa 2

La separación mínima recomendada sería:

```text
Scrapy spider / Playwright fallback
        ↓
DocumentoNormalizado
        ↓
ingerir_documento(session, doc)
        ↓
EjecucionFuente + estados + métricas
```

El spider no debe escribir directamente en `documentos` ni conocer embeddings.
Debe:

1. recibir la configuración de una fuente;
2. descubrir publicaciones;
3. normalizarlas al contrato común;
4. devolver o persistir un resultado de ejecución;
5. dejar la idempotencia final en la restricción y función de ingesta del
   backend.

Para el primer incremento usaría un proceso de scheduler sencillo que lance
un spider por fuente y registre `inicio`, `fin`, descubiertos, nuevos, errores
y versión del conector. No agregaría Celery, Kafka ni un orquestador.

## Límites descubiertos

- Esta PoC extrae el índice/anuncio y la URL del PDF; todavía no extrae el
  texto del PDF.
- La extracción de PDF debe ser una etapa separada y probada con fixtures
  reales. Scrapy y Playwright no reemplazan un extractor PDF.
- La prueba de idempotencia fue por identificador repetido en la salida; la
  garantía productiva debe seguir estando en `(fuente_id,
  identificador_externo)` y/o `hash_contenido` en PostgreSQL.
- No se validó autenticación, rate limiting ni cambios de layout históricos.

## Recomendación final

Adoptar Scrapy para el primer conector real y encapsularlo detrás de un
adaptador propio que emita `DocumentoNormalizado`. Mantener Playwright como
dependencia opcional y usarlo solo cuando una fuente demuestre que HTTP no
alcanza. Revaluar Crawlee después de dos o tres fuentes dinámicas, no antes.

La siguiente PoC productiva debería añadir extracción de un PDF, ejecución
fallida/reintento y escritura contra una tabla de `ejecuciones_fuente` antes
de conectar el scheduler al flujo de embeddings.
