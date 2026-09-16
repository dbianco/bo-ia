# Plataforma de búsqueda semántica del Boletín Oficial

## Estado

Draft v0.1 — 2026-09-16

## Contexto

La plataforma permitirá consultar el contenido del Boletín Oficial de la Provincia de Córdoba mediante búsquedas semánticas y filtros por intervalo de fechas. Cada resultado conservará el texto indexado, la fecha de publicación y el enlace oficial al boletín de origen.

El primer alcance será público y sin autenticación. La arquitectura deberá permitir incorporar posteriormente usuarios, suscripciones por tags, notificaciones personalizadas, otras provincias y un cliente MCP para que herramientas de IA accedan a la información de forma controlada.

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

### Búsqueda

- REQ-07: El usuario debe poder buscar mediante una consulta en lenguaje natural.
- REQ-08: El usuario debe poder indicar fecha desde, fecha hasta o ambas.
- REQ-09: Los resultados deben ordenarse por relevancia semántica.
- REQ-10: Cada resultado debe mostrar un fragmento contextual, la fecha y el enlace oficial.
- REQ-11: El sistema debe informar cuando no encuentra resultados confiables.
- REQ-12: La API debe permitir limitar la cantidad de resultados y devolver metadatos suficientes para citarlos.

### Clasificación

- REQ-13: El modelo de tagging debe soportar múltiples tags por documento o fragmento.
- REQ-14: Cada predicción debe incluir tag, confianza, versión del modelo y fecha de procesamiento.
- REQ-15: El sistema debe permitir configurar umbrales por tag.
- REQ-16: Una predicción de baja confianza no debe convertirse automáticamente en una suscripción activa.

### Futuro MCP

- REQ-17: El servidor MCP debe exponer una operación de búsqueda con consulta y filtros de fecha.
- REQ-18: El servidor MCP debe devolver siempre la URL oficial y la fecha del documento utilizado.
- REQ-19: El servidor MCP debe limitar el volumen de resultados y evitar acceso irrestricto a la base.
- REQ-20: Las consultas MCP deben quedar auditadas con herramienta, fecha, parámetros normalizados y cantidad de resultados.

## 6. Arquitectura propuesta

La primera versión debe ser modular, pero mantenerse en pocos componentes:

1. **Ingestor:** recibe registros de boletines, valida campos y genera fragmentos.
2. **Procesador:** normaliza texto, genera embeddings y ejecuta el tagging cuando esté disponible.
3. **API:** ofrece búsqueda, filtros y consulta de resultados.
4. **Base de datos:** almacena documentos, fragmentos, metadatos, tags y vectores.
5. **Interfaz web:** permite buscar y navegar resultados.
6. **Módulo de entrenamiento:** notebook separado para anotación, evaluación y exportación del modelo.

Para el MVP se recomienda PostgreSQL con pgvector, porque permite mantener en un mismo lugar los datos relacionales, los filtros de fecha, la búsqueda textual futura y los embeddings. La búsqueda híbrida —textual más vectorial— queda preparada sin agregar un motor independiente prematuramente.

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

La columna `jurisdiccion` debe existir desde el inicio aunque solo se cargue Córdoba. Evita rediseñar el esquema cuando se incorpore otra provincia.

## 8. Búsqueda e indexación

La búsqueda inicial será vectorial con filtro por `fecha_publicacion`. Se recomienda dejar una segunda vía textual disponible para nombres propios, números de ley, decretos y códigos que una búsqueda semántica puede tratar de forma imperfecta.

La estrategia futura será:

- búsqueda vectorial para significado y contexto;
- búsqueda textual para coincidencias exactas;
- filtros relacionales para fechas, jurisdicción y tags;
- combinación de rankings mediante una estrategia simple de fusión.

## 9. Tagging y notebook de entrenamiento

El notebook debe tratar el tagging como clasificación multilabel documental. No se debe confundir con un agente autónomo: el resultado esperado es un modelo reproducible de predicción de etiquetas.

### Herramientas iniciales

- Label Studio para anotación y revisión.
- scikit-learn para el baseline TF-IDF.
- SetFit para fine-tuning eficiente con pocos ejemplos.
- `intfloat/multilingual-e5-base` como candidato inicial de embeddings.
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
- enlace al documento oficial.

No se requiere una interfaz conversacional en el MVP. La conversación queda para el cliente MCP o una etapa posterior, cuando existan métricas suficientes sobre la calidad de recuperación.

## 11. Seguridad y confianza

- La URL oficial debe mostrarse como fuente primaria de verificación.
- El sistema debe distinguir texto recibido de texto generado por modelos.
- Los resúmenes futuros deben enlazar siempre al documento de origen.
- No se deben presentar inferencias como si fueran texto oficial.
- La API debe validar tamaño, formato y campos obligatorios en la ingesta.
- El MCP debe aplicar límites de uso y no permitir consultas administrativas.
- Deben registrarse versiones de embeddings, modelos y taxonomías.

## 12. Métricas de éxito

### MVP

- Al menos 95% de los registros ingresados correctamente identificados como únicos.
- 100% de los resultados con fecha y URL oficial.
- Consulta con filtro de fechas funcionando en todos los resultados.
- Tiempo de respuesta objetivo menor a 2 segundos para búsquedas comunes sobre el corpus inicial.
- Evaluación manual positiva en al menos 80% de las primeras consultas representativas.

### Tagging

- Métrica principal: F1 macro por tag.
- Métricas secundarias: precision de tags automáticos y cobertura de documentos etiquetados.
- Ningún tag debe activarse para notificaciones futuras sin un umbral definido y validado.

## 13. Preguntas abiertas

1. ¿Cuál será el formato exacto de entrada de los textos y metadatos?
2. ¿Qué volumen histórico inicial de boletines estará disponible?
3. ¿Cuál será la frecuencia de incorporación de nuevos boletines?
4. ¿Quién revisará la calidad de los datos y las predicciones?
5. ¿Se requerirá búsqueda por secciones o tipos de acto además de fechas?
6. ¿Qué audiencia tendrá prioridad para los futuros resúmenes?
7. ¿El cliente MCP será solo de lectura o incluirá operaciones de suscripción?

## 14. Criterio de salida del MVP

El MVP estará listo cuando una persona pueda ingresar una consulta en lenguaje natural, acotar un intervalo de fechas, recibir resultados relevantes y verificar cada resultado en el enlace oficial correspondiente, con datos reproducibles y sin autenticación.

