# Plataforma de búsqueda semántica del Boletín Oficial

## Estado

Draft v0.6 — 2026-09-16

## Contexto

La plataforma permitirá consultar el contenido del Boletín Oficial de la Provincia de Córdoba mediante búsquedas semánticas y filtros por intervalo de fechas. Cada resultado conservará el texto indexado, la fecha de publicación y el enlace oficial al boletín de origen.

El primer alcance será público y sin autenticación. La arquitectura deberá permitir incorporar posteriormente usuarios, suscripciones por tags, notificaciones personalizadas, otras provincias y un cliente MCP para que herramientas de IA accedan a la información de forma controlada.

Se asume que la ingesta consumirá un feed estructurado de boletines como fuente de datos, no un scraping de una interfaz web (ver no objetivo en sección 3). El formato exacto del feed queda pendiente de definir con la fuente (ver pregunta abierta 1).

## 1. Objetivo

Construir una fuente institucional consultable que reduzca el costo de encontrar información relevante dentro de los boletines oficiales, combinando búsqueda por significado, filtros estructurados y trazabilidad hacia la fuente oficial.

## 2. Alcance por etapas

### Etapa 1 — MVP público

- Ingresar información textual de boletines oficiales.
- Conservar fecha, identificador y URL oficial del documento.
- Dividir documentos extensos en fragmentos indexables.
- Generar embeddings y almacenarlos en una base vectorial.
- Buscar por lenguaje natural.
- Filtrar por intervalo de fechas.
- Mostrar fragmentos relevantes y enlace al boletín oficial.
- Exponer una API de consulta interna, preparada para el futuro cliente MCP.
- Registrar la versión del proceso de ingesta y del modelo de embeddings.

### Etapa 2 — Clasificación y tags

- Crear un dataset anotado.
- Probar un baseline TF-IDF con clasificación multilabel.
- Entrenar un modelo SetFit con embeddings multilingües.
- Asignar tags automáticos con nivel de confianza.
- Permitir distinguir entre tags automáticos, sugeridos y revisados.
- Usar los tags como filtros y como base de futuras suscripciones.

### Etapa 3 — Usuarios y suscripciones

- Incorporar autenticación.
- Permitir que cada usuario configure tags, organismos y frecuencia de aviso.
- Detectar nuevos boletines relevantes.
- Generar un resumen adaptado a la audiencia.
- Enviar el resumen y el enlace oficial.
- Registrar entregas, errores y preferencias.

### Etapa 4 — Cliente MCP y expansión

- Publicar un cliente MCP instalable en distintas herramientas de IA.
- Aplicar límites, validación y trazabilidad a cada consulta.
- Permitir consultar una o varias jurisdicciones provinciales.
- Separar la configuración de fuente, taxonomía y permisos por provincia.

## 3. No objetivos iniciales

- No se implementará autenticación en el MVP.
- No se hará scraping dependiente de una interfaz web en la primera etapa.
- No se generarán resúmenes automáticos como requisito del MVP.
- No se entrenará inicialmente un modelo grande de lenguaje propio.
- No se incorporará una taxonomía compleja hasta contar con ejemplos reales anotados.
- No se presentará la plataforma como asesoramiento legal ni como fuente sustitutiva del boletín oficial.
- No se implementará protección contra abuso (rate limiting, cuotas) mientras el MVP corra solo en un entorno de desarrollo.

## 4. Usuarios

### Usuario público

Busca información por lenguaje natural, acota por fechas y verifica el resultado en la URL oficial.

### Curador de contenidos futuro

Controla la calidad de los datos ingresados, revisa tags sugeridos y corrige errores de clasificación.

### Usuario suscripto futuro

Configura intereses y recibe avisos relevantes sin tener que consultar manualmente la plataforma.

### Herramienta de IA futura

Accede mediante MCP a resultados acotados, citables y trazables a documentos oficiales.

## 5. Requisitos funcionales

### Ingesta

- REQ-01: El sistema debe aceptar el texto de un boletín junto con su identificador, fecha de publicación y URL oficial.
- REQ-02: La ingesta debe ser idempotente para no duplicar un mismo boletín.
- REQ-03: El sistema debe conservar una referencia al contenido original recibido.
- REQ-04: El sistema debe dividir textos extensos en fragmentos con tamaño y solapamiento configurables.
- REQ-05: Cada fragmento debe conservar el identificador del boletín, posición dentro del documento y fecha de publicación.
- REQ-06: Un error de procesamiento debe quedar registrado sin perder el documento recibido.
- REQ-07: El sistema debe garantizar que todo boletín ingerido tenga al menos un fragmento asociado; un boletín sin fragmentos no se considera correctamente ingerido.

### Búsqueda

- REQ-08: El usuario debe poder buscar mediante una consulta en lenguaje natural.
- REQ-09: El usuario debe poder indicar fecha desde, fecha hasta o ambas.
- REQ-10: Los resultados deben ordenarse por relevancia semántica.
- REQ-11: Cada resultado debe mostrar un fragmento contextual, la fecha y el enlace oficial.
- REQ-12: El sistema debe informar cuando no encuentra resultados confiables.
- REQ-13: La API debe permitir limitar la cantidad de resultados y devolver metadatos suficientes para citarlos.
- REQ-14: El usuario debe poder valorar cada resultado como útil o no útil mediante íconos de pulgar arriba / pulgar abajo; la valoración debe quedar asociada a la consulta y al fragmento mostrado.
- REQ-15: En modo SEMANTIC (default), el sistema debe descartar del ranking los fragmentos cuya similitud con la consulta esté por debajo de un umbral mínimo configurable (parámetro interno del servicio, no expuesto al usuario ni en la API pública). Si ningún fragmento supera el umbral, la búsqueda debe devolver una lista vacía y disparar el aviso de REQ-12. En modo HYBRID, una coincidencia de texto exacto (REQ-28) exime a un fragmento de este umbral; en modo ALL no se aplica ningún umbral (REQ-29).
- REQ-26: La búsqueda debe permitir elegir entre los modos SEMANTIC (default, solo vectorial), HYBRID (vectorial + texto exacto) y ALL (unión sin umbral) mediante un parámetro de la API; un valor de modo inválido debe rechazarse.
- REQ-27: El sistema debe indexar el texto de cada fragmento para búsqueda de texto completo en español, usada en los modos HYBRID y ALL.
- REQ-28: En modo HYBRID, el sistema debe combinar el orden por similitud vectorial y el orden por coincidencia de texto en un único ranking; un fragmento con coincidencia de texto exacto debe aparecer aunque su similitud vectorial esté por debajo del umbral de REQ-15.
- REQ-29: En modo ALL, el sistema debe devolver la unión de los candidatos vectoriales y textuales sin aplicar ningún umbral de similitud ni de relevancia de texto.

### Clasificación

- REQ-16: El modelo de tagging debe soportar múltiples tags por documento o fragmento.
- REQ-17: Cada predicción debe incluir tag, confianza, versión del modelo y fecha de procesamiento.
- REQ-18: El sistema debe permitir configurar umbrales por tag.
- REQ-19: Una predicción de baja confianza no debe convertirse automáticamente en una suscripción activa.

### Futuro MCP

- REQ-20: El servidor MCP debe exponer una operación de búsqueda con consulta y filtros de fecha.
- REQ-21: El servidor MCP debe devolver siempre la URL oficial y la fecha del documento utilizado.
- REQ-22: El servidor MCP debe limitar el volumen de resultados y evitar acceso irrestricto a la base.
- REQ-23: Las consultas MCP deben quedar auditadas con herramienta, fecha, parámetros normalizados y cantidad de resultados.

### Entorno de desarrollo

- REQ-24: El MVP debe poder levantarse completo (backend, base de datos e interfaz web) con un solo comando, de forma equivalente en macOS y Windows.
- REQ-25: El entorno local debe incluir datos de ejemplo para poder probar la búsqueda de punta a punta sin depender de que exista un feed real de ingesta.

## 6. Arquitectura propuesta

La primera versión debe ser modular, pero mantenerse en pocos componentes:

1. **Ingestor:** recibe registros de boletines, valida campos y genera fragmentos.
2. **Procesador:** normaliza texto, genera embeddings y ejecuta el tagging cuando esté disponible.
3. **API:** ofrece búsqueda, filtros y consulta de resultados.
4. **Base de datos:** almacena documentos, fragmentos, metadatos, tags y vectores.
5. **Interfaz web:** permite buscar y navegar resultados.
6. **Módulo de entrenamiento:** notebook separado para anotación, evaluación y exportación del modelo.

Para el MVP se recomienda PostgreSQL con pgvector, porque permite mantener en un mismo lugar los datos relacionales, los filtros de fecha, la búsqueda textual futura y los embeddings. La búsqueda híbrida —textual más vectorial— queda preparada sin agregar un motor independiente prematuramente.

Modelo de embeddings: para el MVP se usará `Qwen/Qwen3-Embedding-0.6B` (self-hosted, licencia Apache-2.0, ventana de contexto de 32K tokens, buen desempeño multilingüe y en español), compartido entre la búsqueda semántica de la Etapa 1 y el tagging de la Etapa 2, para no mantener dos modelos distintos. El Procesador lo sirve localmente (por ejemplo con `sentence-transformers`), sin agregar un servicio de embeddings separado. Si las métricas de la sección 12 muestran calidad insuficiente, se puede migrar a una variante mayor de la misma familia (4B u 8B) o a `BAAI/bge-m3`, reindexando el corpus.

## 7. Modelo de datos mínimo

### boletines

- `id`
- `jurisdiccion`
- `identificador_oficial`
- `fecha_publicacion`
- `titulo` opcional
- `texto_original`
- `url_oficial`
- `hash_contenido`
- `estado_ingesta`
- `created_at`

### fragmentos

- `id`
- `boletin_id`
- `posicion`
- `texto`
- `fecha_publicacion` — denormalizada desde `boletines`; la exige REQ-05 y evita un join en el filtro de fecha de REQ-09
- `embedding`
- `metadata`
- `created_at`

### tags

- `id`
- `codigo`
- `nombre`
- `descripcion`
- `activo`

### fragmento_tags

- `fragmento_id`
- `tag_id`
- `origen`: `manual`, `modelo`, `sugerido`
- `confianza`
- `modelo_version`
- `revisado_at`

### valoraciones

- `id`
- `fragmento_id`
- `consulta`
- `valor`: `positivo`, `negativo`
- `created_at`

Los tags a nivel de documento no tienen tabla propia: se derivan de la unión de los tags de sus fragmentos (`fragmento_tags`). Todo boletín debe tener al menos un fragmento generado durante la ingesta (ver REQ-07); un boletín sin fragmentos no se considera correctamente ingerido.

La columna `jurisdiccion` debe existir desde el inicio aunque solo se cargue Córdoba. Evita rediseñar el esquema cuando se incorpore otra provincia.

## 8. Búsqueda e indexación

La búsqueda tiene filtro por `fecha_publicacion` y tres modos (REQ-26):

- **SEMANTIC** (default): solo vectorial, con el umbral de REQ-15.
- **HYBRID**: combina la búsqueda vectorial con una búsqueda de texto completo en español sobre `fragmentos.texto_tsv` (columna generada, con índice GIN), para nombres propios, números de ley, decretos, códigos y términos sueltos que una búsqueda puramente semántica puede tratar de forma imperfecta (REQ-27). Una coincidencia de texto exacto rescata un fragmento aunque su similitud vectorial no supere el umbral (REQ-28). Se agregó tras encontrar que consultas de una sola palabra (ej. "salud") no siempre superan el umbral vectorial aunque el término aparezca literalmente en el texto.
- **ALL**: unión de candidatos vectoriales y textuales sin ningún umbral (REQ-29); modo exploración, máximo recall.

Los rankings de HYBRID y ALL se combinan con *Reciprocal Rank Fusion* (RRF): cada fragmento suma `1/(k + posición)` por cada lista (vectorial, textual) en la que aparece, con `k=60`. Evita normalizar escalas incompatibles (similitud coseno 0-1 vs. `ts_rank` de Postgres).

Umbral de similitud (REQ-15): el score se calcula como similitud coseno entre el embedding de la consulta y el de cada fragmento (0 a 1, a partir de vectores normalizados), y se filtra por resultado, no por consulta completa — se descartan los fragmentos por debajo del umbral antes de aplicar el límite de cantidad de REQ-13. Como todavía no hay corpus real para calibrarlo, arranca en un valor conservador provisional y se ajusta durante la evaluación manual de la sección 12.

## 9. Tagging y notebook de entrenamiento

El notebook debe tratar el tagging como clasificación multilabel documental. No se debe confundir con un agente autónomo: el resultado esperado es un modelo reproducible de predicción de etiquetas.

### Herramientas iniciales

- Label Studio para anotación y revisión.
- scikit-learn para el baseline TF-IDF.
- SetFit para fine-tuning eficiente con pocos ejemplos.
- `Qwen/Qwen3-Embedding-0.6B` como modelo de embeddings (self-hosted), el mismo que se usa para la búsqueda semántica del MVP (ver sección 6).
- Hugging Face Transformers para una futura comparación con BETO o RoBERTa-BNE.

### Flujo

1. Definir ejemplos y reglas de anotación.
2. Etiquetar una muestra inicial.
3. Separar entrenamiento, validación y prueba por fecha para evitar fuga temporal.
4. Entrenar baseline TF-IDF.
5. Entrenar SetFit multilabel.
6. Medir precision, recall y F1 macro por tag.
7. Revisar falsos positivos y falsos negativos.
8. Ajustar umbrales por categoría.
9. Exportar modelo, configuración y versión de tags.
10. Ejecutar predicciones sobre nuevos boletines.

### Nota de próximo paso

Antes de implementar el tagging productivo se debe definir la taxonomía inicial de tags, sus descripciones, ejemplos positivos y negativos, el criterio de multilabel y el flujo de revisión humana. Esa definición es una actividad separada del entrenamiento y condiciona la calidad del modelo.

## 10. Interfaz web del MVP

La pantalla inicial debe contener:

- campo de consulta libre;
- fecha desde;
- fecha hasta;
- botón de búsqueda;
- lista de resultados ordenados por relevancia;
- fecha e identificador del boletín;
- fragmento contextual;
- enlace al documento oficial;
- íconos de pulgar arriba / pulgar abajo para valorar cada resultado (ver REQ-14).

No se requiere una interfaz conversacional en el MVP. La conversación queda para el cliente MCP o una etapa posterior, cuando existan métricas suficientes sobre la calidad de recuperación.

## 11. Seguridad y confianza

- La URL oficial debe mostrarse como fuente primaria de verificación.
- El sistema debe distinguir texto recibido de texto generado por modelos.
- Los resúmenes futuros deben enlazar siempre al documento de origen.
- No se deben presentar inferencias como si fueran texto oficial.
- La API debe validar tamaño, formato y campos obligatorios en la ingesta.
- El MCP debe aplicar límites de uso y no permitir consultas administrativas.
- Deben registrarse versiones de embeddings, modelos y taxonomías.
- La protección contra abuso (límites de uso, cuotas) de la API pública queda diferida mientras el MVP corra solo en un entorno de desarrollo; debe implementarse antes de exponer el sistema fuera de ese entorno.

## 12. Métricas de éxito

### MVP

- Al menos 95% de los registros ingresados correctamente identificados como únicos.
- 100% de los resultados con fecha y URL oficial.
- Consulta con filtro de fechas funcionando en todos los resultados.
- Tiempo de respuesta objetivo menor a 2 segundos para búsquedas comunes sobre el corpus inicial.
- Evaluación manual positiva en al menos 80% de las primeras consultas representativas.
- Verificación manual de que consultas fuera de dominio activan el aviso de "sin resultados confiables" (REQ-12/REQ-15), y de que el umbral no descarta resultados relevantes en consultas dentro de dominio; esta verificación es la que calibra el valor final del umbral.

### Tagging

- Métrica principal: F1 macro por tag.
- Métricas secundarias: precision de tags automáticos y cobertura de documentos etiquetados.
- Ningún tag debe activarse para notificaciones futuras sin un umbral definido y validado.

## 13. Preguntas abiertas

1. ¿Cuál será el formato exacto del feed estructurado de entrada (esquema de campos, protocolo de entrega)?
2. ¿Qué volumen histórico inicial de boletines estará disponible?
3. ¿Cuál será la frecuencia de incorporación de nuevos boletines?
4. ¿Quién revisará la calidad de los datos y las predicciones?
5. ¿Se requerirá búsqueda por secciones o tipos de acto además de fechas?
6. ¿Qué audiencia tendrá prioridad para los futuros resúmenes?
7. ¿El cliente MCP será solo de lectura o incluirá operaciones de suscripción?

## 14. Criterio de salida del MVP

El MVP estará listo cuando una persona pueda ingresar una consulta en lenguaje natural, acotar un intervalo de fechas, recibir resultados relevantes y verificar cada resultado en el enlace oficial correspondiente, con datos reproducibles y sin autenticación.

## 15. Entorno de desarrollo local (Docker)

El MVP debe poder correr igual en macOS y Windows sin instalar dependencias del lenguaje o de Postgres a mano. Se orquesta con `docker compose` en tres servicios:

- **`db`:** PostgreSQL con la extensión pgvector (por ejemplo `pgvector/pgvector:pg16`). Un volumen nombrado persiste los datos entre reinicios; un script de inicialización crea la extensión y el esquema de la sección 7.
- **`backend`:** Ingestor, Procesador y API consolidados en un solo servicio Python (ver sección 6). La imagen no incluye el modelo de embeddings; un volumen nombrado aparte cachea `Qwen/Qwen3-Embedding-0.6B` (se descarga la primera vez que arranca el contenedor y persiste en arranques posteriores). Corre en CPU, sin dependencias de GPU.
- **`web`:** la interfaz de búsqueda de la sección 10, depende de `backend`.

Al arrancar, el `backend` ejecuta un seed idempotente que carga un pequeño conjunto de boletines de ejemplo si la tabla `boletines` está vacía, para que la búsqueda funcione de punta a punta sin depender de un feed real todavía indefinido (ver pregunta abierta 1). El seed no se repite en arranques posteriores si ya hay datos.

Todo el entorno se levanta con un único comando, `docker compose up --build`, igual en las dos plataformas. La configuración (credenciales de desarrollo, puertos) se maneja por variables de entorno, con un `.env.example` versionado en el repositorio.

