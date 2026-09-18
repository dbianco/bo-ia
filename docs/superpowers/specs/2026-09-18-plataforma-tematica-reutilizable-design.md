# Plataforma temática reutilizable de monitoreo y búsqueda semántica

## Estado

Propuesta de arquitectura v0.2 — 2026-09-18 (revisada contra el código; Etapa 1 detallada)

## Resumen ejecutivo

El proyecto comenzó como una plataforma de búsqueda semántica para el Boletín Oficial de la Provincia de Córdoba. El análisis del caso de uso muestra que el motor puede reutilizarse para distintas instituciones y empresas que necesitan incorporar información periódicamente, buscarla por significado y recibir alertas sobre nuevos documentos relevantes.

La propuesta es evolucionar el proyecto hacia un **motor común con instalaciones temáticas independientes**. Cada instalación se enfoca en una temática —por ejemplo boletines, licitaciones o jurisprudencia— y puede tener múltiples clientes, usuarios, búsquedas y suscripciones. Las fuentes y particularidades de cada temática se implementan mediante conectores con código propio; el resto se define mediante configuración.

No se propone crear una aplicación separada para cada caso de uso ni convertir inicialmente el sistema en un SaaS multi-tenant entre temáticas. Cada instalación tiene su propia base de datos y configuración, lo que brinda aislamiento sencillo. Dentro de una instalación sí existe un modelo multiusuario.

## 1. Motivación y casos de uso

### 1.1 Boletines oficiales

Una instalación de boletines puede incorporar información de:

- una o varias provincias;
- municipios;
- organismos públicos;
- distintos tipos de actos o publicaciones.

Los clientes pueden buscar o suscribirse a todo el corpus, a una provincia, a un municipio, a un organismo o a cualquier combinación de filtros disponibles.

### 1.2 Licitaciones

Una instalación de licitaciones puede consultar periódicamente distintos portales configurables. Los clientes pueden suscribirse a consultas como:

- obras viales en una región;
- licitaciones de construcción;
- determinados organismos contratantes;
- rangos presupuestarios;
- oportunidades que coincidan semánticamente con la actividad de una empresa.

### 1.3 Jurisprudencia

Una instalación de jurisprudencia puede almacenar casos, resoluciones y otros documentos judiciales. Los clientes pueden buscar por lenguaje natural y filtrar por tribunal, fuero, materia, fecha u otros metadatos.

La interfaz debe presentar el contenido como fuente consultable y trazable. No debe presentar el sistema como asesoramiento legal ni reemplazar la fuente original.

## 2. Investigación del proyecto actual

El repositorio ya contiene una base útil para esta evolución:

- PostgreSQL con pgvector para datos relacionales y embeddings.
- Fragmentación de documentos extensos.
- Embeddings generados localmente con `Qwen/Qwen3-Embedding-0.6B`.
- Búsqueda semántica, textual e híbrida mediante RRF.
- Filtros de fecha.
- Ingesta idempotente.
- Conservación del texto original y de la URL fuente.
- Feedback sobre resultados.
- API FastAPI e interfaz web simple.
- Migraciones de base de datos con Alembic.

El diseño original ya anticipaba varias extensiones: jurisdicciones, tags, usuarios, suscripciones, notificaciones y otras fuentes. La limitación principal actual es conceptual y de nomenclatura: el modelo central se llama `Boletin` y algunos contratos están expresados exclusivamente en términos del Boletín Oficial.

### 2.1 Observación sobre embeddings

La incorporación de documentos nuevos no requiere volver a entrenar el modelo de embeddings. El modelo se mantiene estable y cada documento nuevo se procesa así:

1. se normaliza;
2. se fragmenta;
3. se genera su embedding;
4. se guarda junto con sus metadatos;
5. queda disponible para búsqueda y evaluación de suscripciones.

El entrenamiento específico de clasificadores o modelos por vertical puede agregarse después, cuando exista un dataset etiquetado y una necesidad comprobada.

### 2.2 Estado verificado en el código

La revisión del repositorio matiza la lista anterior:

- Los filtros de fecha existen, pero están escritos a mano en `_query_base` (`backend/src/api/search.py`). No hay filtros por jurisdicción, tags ni metadatos.
- `jurisdiccion` es un string en `Boletin` que ninguna consulta usa. Las tablas `Tag` y `FragmentoTag` y la columna `Fragmento.metadata_` existen, pero ningún código las lee ni las escribe.
- No existen fuentes o conectores, scheduler, usuarios, autenticación, suscripciones ni notificaciones. La ingesta es un `POST /v1/boletines` que empuja quien llama, más un cargador de datos de ejemplo.
- La lógica de fragmentar y generar embeddings está duplicada entre `backend/src/api/ingest.py` y `backend/src/seed/seed.py`. Hay que extraerla antes de hablar de un "motor común de ingesta".
- La configuración son lecturas dispersas de `os.environ`. `pydantic-settings` es dependencia, pero no se usa.
- La búsqueda vectorial usa un índice HNSW (`ix_fragmentos_embedding_hnsw`, coseno). Ver el riesgo 10.6.

## 3. Decisiones arquitectónicas

### 3.1 Instalación temática independiente

Una instalación representa una temática y se despliega con su propia base de datos, configuración y fuentes.

Ejemplos:

```text
Instalación de boletines
  ├── fuentes provinciales y municipales
  ├── documentos oficiales
  ├── usuarios y clientes
  ├── búsquedas
  └── suscripciones

Instalación de licitaciones
  ├── portales de contratación
  ├── avisos de licitación
  ├── usuarios y clientes
  ├── búsquedas
  └── suscripciones
```

No se agrega inicialmente un `tenant_id` para separar temáticas dentro de una misma base. La instalación y su base de datos ya son el límite de aislamiento. Agregar multi-tenancy entre temáticas tendría sentido si más adelante se decide operar un SaaS centralizado.

### 3.2 Múltiples clientes dentro de una instalación

Cada instalación sí debe soportar varios usuarios o clientes. Un cliente podrá:

- realizar búsquedas;
- guardar búsquedas de interés;
- crear, pausar y eliminar suscripciones según sus permisos;
- recibir notificaciones;
- elegir filtros de alcance;
- consultar el historial de avisos recibidos.

La primera versión puede mantener permisos simples. No hace falta crear desde el inicio un sistema complejo de organizaciones, roles jerárquicos o facturación.

El alcance de un cliente (por ejemplo, solo Córdoba o solo un municipio) se modela como un filtro obligatorio asociado al usuario, aplicado con el mismo mecanismo de filtros que usa la búsqueda. Se implementa en la Etapa 3, no en la Etapa 1.

### 3.3 Motor común y conectores específicos

El motor común provee el comportamiento compartido. Cada conector específico se ocupa únicamente de transformar una fuente externa al contrato común de documentos.

```text
conector específico
        ↓
documento normalizado
        ↓
motor común de ingesta
        ↓
fragmentos + embeddings + metadatos
```

El motor no debe conocer los detalles de HTML, selectores CSS, PDFs, APIs o autenticación de cada fuente.

### 3.4 Configuración antes que código

La configuración debe cubrir, cuando sea razonable:

- identidad de la instalación;
- fuentes habilitadas;
- frecuencia de ejecución;
- campos visibles;
- filtros disponibles;
- taxonomía;
- plantillas de presentación;
- canales de notificación;
- límites operativos.

El código propio queda reservado para conectores que necesiten lógica particular: autenticación, paginación, navegación compleja, extracción de PDFs, interpretación de formatos o resolución de duplicados.

No se debe construir un lenguaje genérico de scrapers antes de tener varios conectores reales. La configuración debe resolver lo repetitivo; el código debe resolver lo específico.

## 4. Componentes del sistema

### 4.1 Núcleo de documentos

Reemplaza el concepto específico de boletín por un documento genérico. Debe almacenar como mínimo:

- fuente (referencia a la tabla `fuentes`);
- identificador externo;
- fecha de publicación o fecha relevante;
- título opcional;
- texto original;
- URL o referencia oficial;
- hash de contenido;
- estado de ingesta;
- metadatos específicos en JSON;
- versión del proceso de ingesta (hoy no existe; entra en la Etapa 1).

El documento debe conservar la información original recibida aun cuando falle una etapa posterior de procesamiento.

### 4.2 Fragmentos e indexación

El flujo actual de fragmentación se mantiene. Cada fragmento conserva:

- documento de origen;
- posición;
- texto;
- fecha relevante;
- embedding;
- metadatos heredados o específicos;
- índice de texto completo.

La búsqueda semántica e híbrida se mantiene sobre PostgreSQL/pgvector. No se agrega un motor de búsqueda separado mientras el volumen no lo justifique.

### 4.3 Conectores

Un conector implementa una fuente concreta y entrega documentos normalizados. Debe permitir:

- ejecución manual;
- ejecución calendarizada;
- reanudación o reintento;
- deduplicación;
- registro de errores;
- identificación de documentos nuevos.

Ejemplos de conectores futuros:

- boletín oficial provincial;
- boletín municipal;
- portal de licitaciones;
- feed RSS o Atom;
- API institucional;
- carpeta de PDFs;
- base de resoluciones judiciales.

### 4.4 Scheduler

Un scheduler ejecuta las fuentes según su configuración. La primera versión debe priorizar un mecanismo sencillo y observable. No se necesita introducir una cola distribuida o un orquestador pesado sin evidencia de volumen suficiente.

Cada ejecución debe registrar:

- fuente;
- inicio y fin;
- cantidad de elementos encontrados;
- cantidad de documentos nuevos;
- cantidad de documentos actualizados o ignorados;
- errores;
- versión del conector.

### 4.5 Suscripciones

Una suscripción representa una consulta persistente de un usuario. Debe incluir:

- usuario propietario;
- texto de búsqueda;
- filtros estructurados;
- estado activa/pausada;
- frecuencia o política de notificación;
- canales configurados;
- fecha de creación y última evaluación.

Cuando un documento nuevo termina de procesarse, el sistema evalúa las suscripciones activas compatibles con su alcance. Si el documento supera el umbral definido, se genera una entrega pendiente o una notificación.

La evaluación debe guardar evidencia mínima del motivo del match: documento, suscripción, score, filtros aplicados y fecha de evaluación.

### 4.6 Notificaciones

Los canales iniciales pueden ser correo electrónico y una bandeja interna de avisos. WhatsApp, Slack, webhooks u otros canales se agregan cuando exista una necesidad concreta.

El sistema debe registrar:

- estado de la entrega;
- fecha de intento;
- cantidad de reintentos;
- error del proveedor;
- documento y suscripción relacionados.

No debe enviarse una notificación duplicada para el mismo documento y suscripción salvo que exista una política explícita de reenvío.

## 5. Modelo conceptual inicial

```text
Instalacion
  ├── Fuente
  │     └── EjecucionFuente
  ├── Documento
  │     └── Fragmento
  │           └── Tags opcionales
  ├── Usuario
  │     ├── Suscripcion
  │     └── Valoracion
  └── ConfiguracionVertical

Suscripcion + Documento nuevo
  → EvaluacionMatch
  → EntregaNotificacion
```

### 5.1 Documento y metadatos

Los campos comunes deben tener columnas propias cuando participan habitualmente en joins, filtros o índices. Los campos particulares de una vertical comienzan en `metadata` JSON.

Ejemplos de metadatos:

```json
{
  "provincia": "Córdoba",
  "municipio": "Carlos Paz",
  "organismo": "Agencia Córdoba Turismo"
}
```

```json
{
  "rubro": "obra vial",
  "organismo_contratante": "Municipalidad de Córdoba",
  "presupuesto_estimado": 120000000
}
```

```json
{
  "tribunal": "Cámara Civil",
  "fuero": "civil",
  "materia": "contratos"
}
```

Si un metadato se usa de forma intensiva y estable, puede migrarse a una columna indexada posteriormente. No conviene diseñar un esquema rígido para todos los verticales antes de conocer sus consultas reales.

### 5.2 Filtros declarados por instalación

Los metadatos viven en una columna JSONB con índice GIN. Cada instalación declara en su configuración qué filtros expone sobre las claves del metadata; el motor los traduce a SQL sin conocer sus nombres. El núcleo solo incorpora fecha y fuente. El detalle está en la sección 8 (Diseño detallado de la Etapa 1).

## 6. Flujo de datos

### 6.1 Ingesta calendarizada

```text
Scheduler
  → ejecuta conector
  → descubre elementos
  → normaliza documentos
  → deduplica por fuente + identificador/hash
  → persiste documento original
  → fragmenta
  → genera embeddings
  → actualiza índices
  → evalúa suscripciones
  → crea entregas de notificación
```

Un error de scraping o procesamiento no debe eliminar el documento original ni ocultar la ejecución fallida. El estado debe permitir distinguir entre descubierto, persistido, procesado, notificado y fallido.

### 6.2 Búsqueda

La búsqueda conserva los modos actuales:

- `semantic`: recuperación vectorial con umbral;
- `hybrid`: vectorial + texto completo;
- `all`: exploración con mayor recall.

Los filtros estructurados se aplican sobre campos comunes y sobre metadatos configurados para la vertical. Cada resultado debe incluir la fuente original, la fecha y el enlace o referencia verificable.

### 6.3 Suscripción

```text
Documento nuevo procesado
  → seleccionar suscripciones por alcance
  → aplicar filtros estructurados
  → calcular similitud semántica
  → aplicar umbral
  → evitar duplicados
  → registrar match
  → entregar notificación
```

La evaluación puede comenzar de forma síncrona para un volumen pequeño. Si el procesamiento demora o crece el número de clientes, se separa en tareas asíncronas.

## 7. Evolución del proyecto actual

### 7.1 Renombres conceptuales

La primera migración debería cambiar progresivamente:

- `Boletin` → `Documento`;
- `boletines` → `documentos`;
- `boletin_id` → `documento_id`;
- `identificador_oficial` → `identificador_externo`;
- `url_oficial` → `url_fuente`;
- `fecha_publicacion` → `fecha`;
- `jurisdiccion` (string) → `fuente_id` (referencia a `fuentes`).

Se reforma este repositorio y no se crea uno nuevo. Nada externo consume hoy `/v1/boletines` ni hay datos que preservar, por lo que el renombre se hace sin capa de compatibilidad.

El renombre es más que cambiar una tabla:

- se agrega una migración Alembic nueva, porque las migraciones existentes nombran `boletines` y no se edita el historial;
- hay que renombrar constraints e índices (`uq_boletin_*`, `uq_fragmento_boletin_posicion`, `ix_fragmentos_fecha_publicacion`);
- cambian las claves JSON de la API (`boletin_id`, `identificador_oficial`, `url_oficial`) y los templates que las consumen;
- hay que actualizar los tests que fijan nombres (`tests/conftest.py`, `tests/test_migrations.py`) y el README.

### 7.2 Primer vertical

El Boletín Oficial debe mantenerse como primer vertical y caso de regresión. La generalización debe demostrar que no se pierde:

- ingesta idempotente;
- filtros de fecha;
- búsqueda híbrida;
- trazabilidad a la fuente;
- feedback;
- datos de ejemplo;
- ejecución local con Docker.

### 7.3 Orden recomendado

1. Generalizar el modelo y el contrato de ingesta.
2. Mantener el conector de boletines funcionando mediante el nuevo contrato.
3. Separar configuración de instalación y vertical.
4. Incorporar usuarios y suscripciones.
5. Agregar scheduler y registro de ejecuciones.
6. Agregar notificaciones con un canal inicial.
7. Crear un segundo conector real para validar la reutilización.

El segundo conector es una prueba de arquitectura. Si implementarlo exige duplicar lógica del núcleo, la separación todavía no es correcta.

Se mantiene este orden por capas. El riesgo asumido es que el contrato de documento se pruebe con un solo caso hasta el final: si un segundo vertical lo invalida, habrá que rehacer suscripciones y notificaciones. Los filtros declarados por instalación y los metadatos en JSONB reducen ese riesgo.

## 8. Alcance por etapas

### Etapa 1 — Núcleo genérico

- Documento genérico.
- Fragmentos y embeddings desacoplados del boletín.
- Contrato de documento normalizado.
- Configuración de instalación.
- Búsqueda semántica e híbrida reutilizable.
- Compatibilidad con el vertical de boletines.

### Etapa 2 — Ingesta operativa

- Registro de fuentes.
- Scheduler.
- Ejecuciones, estados, reintentos y errores.
- Primeros conectores configurables.
- Idempotencia por fuente e identificador/hash.

### Etapa 3 — Clientes y suscripciones

- Autenticación básica.
- Usuarios.
- Consultas guardadas.
- Filtros por metadatos.
- Suscripciones activas y pausables.
- Evaluación de documentos nuevos.

### Etapa 4 — Notificaciones

- Bandeja interna de avisos.
- Correo electrónico.
- Historial de entregas.
- Prevención de duplicados.
- Reintentos y errores.

### Etapa 5 — Segundo vertical

Implementar licitaciones o jurisprudencia para validar que:

- el motor no depende de nombres del boletín;
- los metadatos pueden variar;
- los filtros se pueden configurar;
- el conector puede contener lógica propia;
- las suscripciones funcionan sin código específico en el motor.

### Diseño detallado de la Etapa 1

**Datos e ingesta**

- Tabla `fuentes` mínima: `clave` (por ejemplo `cordoba-provincial`), `nombre` y `config` JSONB. Reemplaza al string `jurisdiccion`. La Etapa 2 le agrega frecuencia y estado de ejecución.
- `documentos` (antes `boletines`): `fuente_id`, `identificador_externo`, `fecha`, `titulo`, `texto`, `url_fuente`, `hash_contenido`, `estado`, `metadata` JSONB y `version_ingesta`. La idempotencia es por `(fuente_id, identificador_externo)` o por `hash_contenido`.
- Estados en la Etapa 1: `persistido`, `procesado` y `fallido`. Los demás se agregan con el scheduler y las notificaciones. Si falla el procesamiento, se conserva el texto original.
- `fragmentos.documento_id` reemplaza a `boletin_id`. `fecha` sigue denormalizada para filtrar sin join. Los metadatos se filtran mediante join a `documentos.metadata`, para tener una única fuente de verdad. `Valoracion` solo cambia su referencia. Las tablas de tags no se tocan.
- Contrato `DocumentoNormalizado` (`fuente`, `identificador_externo`, `fecha`, `titulo`, `texto`, `url_fuente`, `metadata`) y una única función `ingerir_documento(session, doc)`, extraída de la lógica duplicada entre `ingest.py` y `seed.py`. `POST /v1/documentos` es una capa fina sobre esa función.
- Un adaptador específico del Boletín traduce sus campos al contrato y completa `provincia`, `municipio` y `organismo` en el metadata.

**Configuración y búsqueda**

- Un archivo `installation.yaml`, cuya ruta se indica con `INSTALLATION_CONFIG`, validado al arrancar con un modelo pydantic. Contiene nombre y textos, fuentes iniciales (cargadas de forma idempotente en `fuentes`), filtros declarados y campos del metadata visibles en los resultados. Las variables de entorno quedan para infraestructura (`DATABASE_URL`, modelo de embeddings, umbral).
- Filtros declarados:

  ```yaml
  filtros:
    - clave: provincia
      etiqueta: Provincia
      tipo: seleccion
      opciones: desde_datos
    - clave: municipio
      tipo: seleccion
      opciones: desde_datos
  ```

  Tipos: `seleccion` (uno o varios valores) y `rango_numerico` (mínimo y máximo). `opciones: desde_datos` hace un `SELECT DISTINCT` sobre el metadata; alcanza para corpus chicos y puede cambiarse por lista fija o cache.
- Módulo puro `aplicar_filtros(consulta, filtros, config)`: `@>` para selección (aprovecha el índice GIN), cast numérico para rango, error 422 ante una clave no declarada. Las suscripciones de la Etapa 3 reutilizan este módulo.
- `GET /v1/config` publica filtros y etiquetas. `GET /v1/search` acepta `filtro.<clave>=valor` además de fecha y modo. Los modos `semantic`, `hybrid` y `all` no cambian. Cada resultado devuelve `documento_id`, `fuente`, `identificador_externo`, `url_fuente` y `metadata`.
- La web genera los controles de filtro desde `/v1/config` y muestra los campos configurados.

**Migración**

Una revisión Alembic nueva, con downgrade:

1. crea `fuentes` con una fila por cada valor distinto de `jurisdiccion`;
2. renombra `boletines` → `documentos`, sus columnas, constraints e índices, y `fragmentos.boletin_id` → `documento_id`;
3. agrega `fuente_id` con backfill desde `jurisdiccion` y elimina esa columna;
4. agrega `metadata` (backfill con `provincia`), `estado`, `version_ingesta` y un índice GIN sobre `metadata`.

**Orden de trabajo** (la suite queda en verde en cada paso): extraer `ingerir_documento` conservando los nombres actuales; migración y renombre; `fuentes`, `metadata` y carga de la configuración; módulo de filtros, API y web; seed con documentos de varios municipios.

**Pruebas**

Se migran por renombre las pruebas existentes. Se agregan pruebas del módulo de filtros (selección, rango, clave inválida), de validación de la configuración, del backfill de la migración, del mismo `identificador_externo` en dos fuentes y un caso de punta a punta: filtrar por "Carlos Paz" excluye "Noetinger". También una prueba de recall con un filtro selectivo (ver 10.6).

**Criterio de salida de la Etapa 1**

1. El núcleo no menciona `Boletin` (se verifica con grep). Solo el adaptador, el seed y la configuración lo nombran.
2. Dos fuentes conviven en una instalación.
3. Los filtros `provincia` y `municipio` se declaran en `installation.yaml`; cambiarlos no requiere tocar el motor.
4. Siguen pasando la ingesta idempotente, los filtros de fecha, la búsqueda híbrida, el feedback y el smoke de Docker.

## 9. Decisiones postergadas

No forman parte de la primera generalización:

- SaaS multi-tenant entre temáticas;
- facturación y planes comerciales;
- marketplace de conectores;
- lenguaje declarativo universal para scrapers;
- entrenamiento de un modelo diferente por vertical;
- generación automática de resúmenes como requisito;
- múltiples motores de búsqueda;
- colas distribuidas y procesamiento masivo;
- permisos organizacionales complejos;
- aplicación móvil nativa.

Estas capacidades pueden agregarse cuando haya evidencia de volumen, clientes o necesidades que las justifiquen.

## 10. Riesgos y mitigaciones

### 10.1 Modelo demasiado genérico

Riesgo: un documento común pierde información importante de un vertical.

Mitigación: conservar metadatos específicos y permitir extensiones de presentación y filtros. Promover columnas específicas solo cuando exista una necesidad demostrada.

### 10.2 Conectores frágiles

Riesgo: cambios en los sitios externos rompen la extracción.

Mitigación: versionar conectores, registrar ejecuciones, conservar datos originales y agregar pruebas con fixtures reales.

### 10.3 Notificaciones ruidosas

Riesgo: una consulta amplia genera demasiados avisos.

Mitigación: umbral configurable, filtros estructurados, modo de prueba, pausa de suscripciones y feedback de relevancia.

### 10.4 Duplicación de documentos

Riesgo: una misma publicación aparece en distintas fuentes.

Mitigación: deduplicación por fuente, identificador, hash y reglas específicas del vertical cuando haga falta.

### 10.5 Costo de embeddings

Riesgo: procesar corpus grandes puede aumentar tiempos y consumo de recursos.

Mitigación: procesamiento incremental, idempotencia, cache de modelo, métricas de duración y reindexación explícita por versión.

### 10.6 Filtrado sobre el índice HNSW

Riesgo: con un índice HNSW, los filtros SQL se aplican sobre los candidatos que devuelve el índice. Un filtro muy selectivo (un municipio pequeño) puede devolver menos resultados de los pedidos aunque existan. El filtro de fecha actual puede estar sujeto al mismo comportamiento.

Mitigación: confirmar la versión de pgvector y evaluar `hnsw.iterative_scan` (pgvector 0.8 o posterior) o un `hnsw.ef_search` mayor. Cubrirlo con una prueba de recall con filtro selectivo antes de cerrar la Etapa 1.

## 11. Métricas de éxito

La generalización debería medirse por resultados operativos, no solo por cantidad de abstracciones:

- un segundo vertical puede incorporarse sin copiar el motor;
- una nueva fuente puede agregarse sin modificar la búsqueda;
- los documentos nuevos quedan disponibles automáticamente;
- una suscripción no genera duplicados;
- los resultados conservan trazabilidad a la fuente;
- los errores de una fuente son visibles y reintentables;
- los filtros específicos de una instalación no contaminan otras instalaciones;
- el tiempo y costo de ingesta son observables.

## 12. Preguntas abiertas

1. ¿Cuál será el primer canal de notificación real: correo, bandeja interna o ambos?
2. ¿La primera instalación multiusuario requerirá invitaciones y roles, o alcanza con usuarios independientes?
3. ¿El scheduler debe correr dentro del backend o como un proceso separado?
4. ¿Cuál será el primer segundo vertical para validar el diseño: licitaciones o jurisprudencia?
5. ¿Qué fuentes concretas están disponibles para construir fixtures de scraping?
6. ~~¿Qué filtros deben ser configurables por instalación y cuáles deben formar parte del núcleo?~~ Resuelta: el núcleo solo trae fecha y fuente; el resto se declara por instalación (sección 8, diseño detallado de la Etapa 1).
7. ¿Qué volumen esperado de documentos y suscripciones condicionaría pasar a procesamiento asíncrono?

## 13. Criterio de salida de la primera generalización

La primera generalización (Etapas 1 a 3) estará completa cuando una instalación de boletines pueda hacer lo siguiente. El criterio de salida de la Etapa 1 por sí sola está en la sección 8.

1. configurar más de una fuente;
2. ingerir documentos mediante un contrato genérico;
3. buscar por lenguaje natural y filtros;
4. mantener varios usuarios o clientes;
5. crear una suscripción con consulta y filtros;
6. evaluar documentos nuevos contra esa suscripción;
7. conservar la trazabilidad y el estado de cada operación;
8. hacerlo sin que el núcleo dependa del nombre o estructura de `Boletin`.

El segundo vertical será el criterio práctico de validación de que la plataforma es realmente reutilizable.
