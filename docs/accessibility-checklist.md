# Checklist de accesibilidad — página de búsqueda (WCAG 2.1 AA)

T029. Verificación manual sobre `web/templates/search.html` y `_resultados.html`. Se corre con el stack levantado (`docker compose up --build`) contra `http://localhost:9102`.

## Navegación por teclado

- [ ] Se puede llegar al campo de consulta, los dos campos de fecha, el botón "Buscar" y a cada botón de pulgar arriba/abajo usando solo `Tab` / `Shift+Tab`, en un orden lógico (de arriba hacia abajo).
- [ ] El foco nunca queda atrapado en un elemento (se puede seguir tabulando hasta salir del formulario y de la lista de resultados).
- [ ] Se puede enviar la búsqueda presionando `Enter` con el foco en el campo de consulta, sin necesidad del mouse.
- [ ] Se puede activar cada botón de pulgar arriba/abajo con `Enter` o `Espacio` con el foco puesto en el botón.

## Foco visible

- [ ] Cada elemento interactivo (campo de texto, campos de fecha, botón de buscar, botones de pulgar) muestra un contorno de foco claramente visible al navegar con teclado (`:focus-visible` en `style.css`).
- [ ] El contorno de foco tiene contraste suficiente contra el fondo, tanto en modo claro como oscuro (la hoja de estilos define `--accent` para ambos esquemas de color vía `prefers-color-scheme`).

## Etiquetas y semántica

- [ ] El campo de consulta, "Desde" y "Hasta" tienen cada uno un `<label>` asociado por `for`/`id` (no solo un `placeholder`).
- [ ] Los botones de pulgar arriba/abajo tienen `aria-label` describiendo la acción ("Marcar este resultado como útil" / "...no útil"), porque su contenido visible es solo un emoji.
- [ ] El formulario usa `role="search"` para que un lector de pantalla lo identifique como región de búsqueda.
- [ ] Los resultados están dentro de una `<section aria-live="polite">`, para que un lector de pantalla anuncie cuando cambian tras una búsqueda.
- [ ] El mensaje de "no encontramos resultados confiables" usa `role="status"`, igual que el mensaje de agradecimiento tras valorar un resultado.

## Contraste de color

- [ ] El texto principal (`--fg` sobre `--bg`) cumple una relación de contraste de al menos 4.5:1, tanto en modo claro como oscuro.
- [ ] El texto secundario (`--muted`, usado en fechas y subtítulos) cumple al menos 4.5:1 para texto normal o 3:1 si se usa en tamaño grande.
- [ ] El color de acento (`--accent`, usado en el botón "Buscar" y el foco) cumple 3:1 contra el fondo adyacente.

## Zoom y tamaño de texto

- [ ] La página se sigue leyendo y usando correctamente con el zoom del navegador al 200%, sin scroll horizontal ni contenido recortado.
- [ ] Los tamaños de fuente están en unidades relativas (`rem`) en `style.css`, no en píxeles fijos, así respetan la configuración de tamaño de fuente del usuario.

## Cómo correrla

1. `docker compose up --build`
2. Abrir `http://localhost:9102` en un navegador.
3. Recorrer cada ítem de esta checklist a mano (no hay una herramienta automática corriendo esto todavía; queda como tarea futura evaluar axe-core o Lighthouse CI).
4. Marcar cada casillero y anotar cualquier hallazgo antes de dar el MVP por cerrado (ver criterio de salida en la sección 14 del design spec).
