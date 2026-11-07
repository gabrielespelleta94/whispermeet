# Apuntes: especificación visual agéntica

> **Nota (2026-11-04):** `DESIGN-visual.md` manda sobre este documento en todo lo estético (materiales, tokens, radios, sombras, movimiento y estados); donde se contradigan, vale `DESIGN-visual.md`. Lo funcional de este documento sigue vigente.

Definida por Fable el 2026-11-03 y corregida contra la app real. Manda sobre `DESIGN.md` donde se contradigan; `DESIGN.md` conserva marca, curvas y transiciones de la app de referencia.

## Concepto

Un puesto de trabajo con un colaborador visible: el agente tiene una línea propia, permanente, que dice en qué estado está, qué ha leído y cuánto le falta para actuar. Cada resultado lleva su procedencia (minuto, tramo, modelo, coste) y enlaza con la evidencia. La élite viene de la densidad tranquila: una familia tipográfica bien escalada, filetes finos, cifras tabulares, un solo acento y movimiento solo cuando ocurre algo real.

## Decisiones de mayor impacto

1. Orquestación: banda de 96 px bajo la cabecera (plegable a la línea del agente de 32 px, preferencia recordada) con los agentes que existen de verdad, su estado real y el flujo entre ellos. La línea del agente sigue siendo la fuente de verdad del estado del analista.
2. Traza por análisis: los insights se agrupan por análisis, con cabecera de tramo, modelo, duración, tokens y cambios. Omisiones y fallos van en la misma cronología.
3. Evidencia enlazada: todo minuto es un botón que lleva a su línea; la transcripción muestra "Analizado hasta".
4. Jerarquía por tipografía y espacio, no por cajas: paneles sin borde, separados por filete y aire; etiquetas de 11 px en mayúsculas sin fondo.
5. Entrada silenciosa: nada se mueve si la columna está desplazada; aparece "N nuevos ↑".

## Tokens

Derivados marcados con *.

| Token | Oscuro | Claro |
|---|---|---|
| Fondo | `#1B1B20` | `#FFFFFF` |
| Panel | `#202026`* | `#F2F2F4` |
| Elevado | `#26262D`* | `#FFFFFF` |
| Hover de fila | `#24242B`* | `#F0F0F2` |
| Filete | `#2C2C34`* | `#E0E0E6` |
| Filete fuerte | `#3A3A42` | `#C7C7CC` |
| Texto primario | `#F2F2F4` | `#1B1B20` |
| Texto cuerpo | `#B9B9C3` | `#3A3A42` |
| Texto secundario y apagado | `#909098` | `#686868` |
| Acento de relleno | `#007AFF` | `#007AFF` |
| Acento como texto | `#66ACFF` | `#006EB7` |
| Acento suave | `rgba(0,122,255,.14)`* | `#EAF3FF` |
| Selección de línea | `rgba(0,122,255,.10)`* | `#EAF3FF` |
| Verde | `#5ED38B`* | `#1E8A4C` |
| Rojo | `#F28B82`* | `#B3261E` |
| Ámbar | `#F0A94E`* | `#B25E09` |
| Fondos semánticos | mismo tono a alfa .12 | `#E8F5EE`* `#F9E9E8`* `#FBF0E2`* |

Corrección de contraste: `#686868` sobre `#1B1B20` y `#909098` sobre blanco no llegan a AA, así que no se usan como texto; `#007AFF` tampoco se usa como texto en claro. Única excepción admitida: texto blanco peso 600 sobre relleno `#007AFF` (botón primario y barra Run), por ser el color de marca.

Tipografía, DM Sans con `tabular-nums` global:

| Clase | Medida | Uso |
|---|---|---|
| `t-display` | 22/28 600 −0,01em | Título de reunión y de proyecto |
| `t-title` | 15/20 600 | Cabeceras de panel |
| `t-body` | 14/20 400 | Transcripción, tarjetas, resumen |
| `t-body-m` | 14/20 500 | Hablante, títulos de objetivo y check |
| `t-meta` | 12/16 500 +0,01em | Minutos, modelo, tokens, rutas, citas |
| `t-label` | 11/14 600 +0,06em mayúsculas | Categorías, estados, fases |
| `t-cron` | 20/24 500 | Cronómetro |

- Espaciado base 4: 4, 8, 12, 16, 24, 32, 48. Tarjeta 12×12, panel 16×16, gutter 16, margen 16. Fila de lista 32; tarjeta mín. 44.
- Radios: 3 chips y casillas; 6 botones e inputs; 8 tarjetas; 0 paneles y bandas.
- Sombras: ninguna en oscuro; en claro `0 1px 2px rgba(27,27,32,.06)` solo en menús y popovers.
- Foco: `outline: 2px solid #007AFF; outline-offset: 2px`.
- Filetes de 1 px; 2 px solo en el indicador lateral de novedad.

## Pantalla de reunión

```
Cabecera 48:  ●REC  Título · Proyecto   [Micro][Reunión]   00:34:12   Contexto  Pausa  [Analizar ahora]  Terminar  Oculta al compartir
Agente 32:    (plegada; desplegada = banda «Orquestación» de 96 px, ver más abajo)  ○ Esperando · 118/150 palabras ▬▬ · próximo en 3:48 · último 25:00–30:00 · haiku · 3,2 s · 4,1k     Registro
Cuerpo:       grid 1fr 2fr, gap 16, padding 0 16
              Transcripción y notas (1/3) | Objetivos y checks | Insights
Pie 28:       Contexto · 6 ficheros · nombres +4           Tokens sesión 48,2k · haiku 12 · sonnet 1 · opus 0
```

A 1440 px: 464, 456 y 456 px. El texto de tarjeta se limita a `max-width: 56ch`. Por debajo de 1100 px la zona derecha pasa a una columna.

**Cabecera.** Fondo base y filete inferior. `●REC` de 8 px en rojo, parpadeo de 1,2 s vaivén entre 1 y .35. Medidores: 5 barras de 3×12 con hueco 2, activas en `#007AFF`, inactivas en filete fuerte, sin transición. Con retraso de transcripción de más de 5 s, `+12 s` en t-meta ámbar bajo "Reunión". Botones de 32 de alto: "Analizar ahora" primario y el resto fantasma. "Oculta al compartir" sigue siendo el interruptor actual de exclusión de captura; no se añade atajo ni bandeja.

**Línea del agente.** 32 px, fondo panel, filete inferior. Separada por " · " en texto apagado:
- Indicador de 6 px: esperando, círculo hueco; analizando, relleno `#007AFF` con bucle 1→.4 en 1,2 s; confirmando, relleno fijo; error, relleno rojo; pausa, hueco apagado.
- Estado en t-body-m.
- Barra de palabras 56×3 (la firma): riel de filete fuerte y relleno `#007AFF` proporcional a palabras/mínimo, con `118/150 palabras`.
- `próximo en 3:48`, actualizado cada segundo.
- `último 25:00–30:00 · haiku · 3,2 s · 4,1k tokens`; sin análisis, `sin análisis todavía`.
- A la derecha, "Registro": popover de 360 px con las últimas 20 entradas de traza. Un campo sin dato no se pinta.

**Transcripción.** Formato compacto de la columna estrecha: minuto y hablante en una línea t-meta, texto t-body debajo, padding 6×8, sin bordes; 8 px extra al cambiar de hablante. Separador `Analizado hasta 30:00` con filete y t-label centrado, que se mueve tras cada análisis. Sin atenuar lo ya leído. Autoscroll solo a menos de 40 px del final; si no, botón flotante "Ir al final". Línea destino: selección de línea y barra izquierda de 2 px durante 1,6 s, y se disipa en 400 ms.

**Notas.** Debajo de la transcripción, plegables, 104 px.

**Objetivos.** Fila de 32 px: indicador de 10 px, título t-body-m y chip de minuto. Sin tratar, círculo hueco; parcial, semicírculo azul; cubierto, círculo verde con marca blanca. El cambio escala .8→1 en 180 ms y nunca reordena. Contador `3/7 cubiertos`.

**Checks.** Fila de 32 px: casilla de 16 px, texto, chip y "Deshacer" (visible 10 s tras un cambio automático; luego en hover o foco). Base, casilla hueca; sugerido, borde azul punteado y botón "Confirmar"; manual, relleno azul; automático, igual más una línea con la cita entre « », máx. 90 caracteres. La marca automática se traza en 400 ms.

**Insights.** Cabecera "Insights" con contador. Orden cronológico inverso y agrupado:
- Traza, 28 px, fondo panel, t-meta: `Análisis 3 · 25:00–30:00 · haiku · 3,2 s · 4,1k · 2 insights · 1 objetivo · 1 check`. Los contadores a 0 no se pintan. Al pulsarla se resaltan las líneas del tramo sin desplazar.
- Omisión: misma fila, apagada: `40:00 · Omitido · 94 palabras nuevas (mín. 150)`.
- Fallo: misma fila, en rojo, con "Reintentar": `45:00 · Fallo · límite del plan`.
- Tarjeta: fondo panel, radio 8, padding 12, margen 8. Etiqueta de categoría y chip de minuto; texto t-body, máx. 3 líneas con "Más". Decisión y Pregunta en texto secundario; Pendiente en acento como texto; Riesgo y Contradicción confirmada en rojo; Posible contradicción en ámbar. Si existe el dato, una línea `contra: fichero.md`.
- Nueva con `scrollTop` 0: opacidad 0→1 y y 4→0 en 180 ms, escalonada 35 ms, con barra izquierda de 2 px que dura 8 s y se disipa en 400 ms.
- Nueva con la columna desplazada: se inserta con `overflow-anchor` sin mover la vista, y aparece `2 nuevos ↑`. Igual en objetivos y checks con `1 cambio ↑`.

**Chip de minuto.** 20 px de alto, padding 0 6, radio 3, t-meta, acento suave y acento como texto. Hover: barra en la línea destino sin desplazar. Clic o Enter: lleva la línea al 30 % de la altura visible en 260 ms, la resalta 1,6 s y el foco se queda en el chip.

**Fallos y límites.** Sin banners: todo cabe en la línea del agente y en la traza. Con límite del plan o sesión caducada: estado de error, automático detenido, "Analizar ahora" deshabilitado salvo que la app permita reintentar, y fila de fallo. Sin respuesta: fila de fallo y aviso de reintento en el próximo ciclo. Retraso de más de 15 s: ámbar en el medidor y `Transcripción con 18 s de retraso`.

**Pie.** 28 px, t-meta apagado. Contexto a la izquierda, con nombres completos en tooltip; tokens a la derecha. Cambia en seco.

## Inicio

Grid 400 px + 1fr, gap 32, padding 32. Izquierda: logo de 120 px con firma 56×3; formulario con t-label sobre campos de 36 px; lista de proyectos de 32 px por fila; sesión y cadencia como grupos segmentados de 32 px; casilla de aviso a asistentes, obligatoria para activar "Empezar reunión" (primario de 40 px). Derecha: ficha, Gantt y listas de objetivos, participantes, dependencias y checks en dos columnas.

**Gantt.** Etiqueta de 96 px y 10 columnas S1 a S10, cabeceras t-label de 24 px. Cinco filas de fase de 28 px y una de hitos de 24 px. Barras de 20 px, radio 3, con t-label `#1B1B20`: Prepare `#D4E6FF`, Explore `#B0D2FF`, Realize `#8CBFFF`, Deploy `#66ACFF`; Run `#007AFF` con texto blanco. Hitos: rombo de 8 px azul con etiqueta t-meta. Línea de hoy de 1 px con etiqueta `Hoy`. Sesión seleccionada resaltada. Las sesiones sin fecha van en una fila inferior `Por definir: TR3 · TR4` como chips fantasma punteados; TR5 aparece como propuesta en su fecha. Solo filete entre filas.

## Revisión

Grid 1fr 2fr. Columna 1: resumen a `max-width 56ch` y objetivos cumplidos y pendientes. Zona 2/3: cambios propuestos, uno por fichero, con cabecera de 36 px, contador `+4 −1` y "Aceptar todo / Rechazar todo". Diff en DM Sans con filas t-body; añadidos con fondo verde suave y barra de 2 px; eliminados con fondo rojo suave y tachado. Cada bloque con "Aceptar" y "Rechazar"; al decidir colapsa a una fila de 28 px con "Deshacer". "Pulir con Opus" fantasma: durante la llamada la línea del agente muestra `Puliendo con opus…`; al terminar, dos columnas `Sonnet · 2,1k tokens` y `Opus · 5,4k tokens · 9,8 s`, con diferencias en acento suave y "Usar esta" en cada cabecera. Publicar: casilla, texto y ruta completa sin elipsis.

## Movimiento

| Evento | Qué cambia | ms | Curva | Retardo |
|---|---|---|---|---|
| Hover de fila o botón | Fondo | 120 | vaivén | 0 |
| Barra de palabras | Ancho | 180 | salida | 0 |
| Esperando a analizando | Indicador y texto | 180 | salida | 0 |
| Analizando, en bucle | Opacidad 1↔.4 | 1200 | vaivén | 0 |
| Analizando a esperando | Indicador y tramo | 260 | salida | 0 |
| Tarjeta nueva | Opacidad, y 4→0 | 180 | salida | 35·n |
| Barra de novedad | Se disipa | 400 | salida | 8000 |
| Cambio de objetivo | Escala .8→1 | 180 | salida | 0 |
| Marca de check automático | `stroke-dashoffset` | 400 | salida | 0 |
| Clic en minuto | Scroll de transcripción | 260 | salida | 0 |
| Resaltado de línea | Fondo y barra | 1600 + 400 | salida | 0 |
| Separador "Analizado hasta" | Posición | 260 | salida | 0 |
| Popover | Opacidad, y 4→0 | 120 | salida | 0 |
| Diff decidido | Colapso de altura | 260 | entrada | 0 |
| Cambio de pantalla (de la app de referencia) | x 16→0 y opacidad al entrar; x −12 al salir | 260 y 120 | salida y entrada | 0 |
| Cabecera al entrar (de la app de referencia) | y −48→0 | 320 | salida | 0 |
| Barras del Gantt (de la app de referencia) | `scaleX` 0→1 desde la izquierda | 260 | salida | 35·n |

Con `prefers-reduced-motion`: todo a 0 ms salvo medidores; `●REC` y el resaltado quedan fijos.

## Microcopia de la línea del agente

- `Escuchando · sin análisis todavía`
- `Esperando · 118/150 palabras · próximo en 3:48`
- `Listo · 150/150 palabras · próximo en 1:12`
- `Escuchando · 64/150 palabras · tope en 3:12` (adaptativo, sin señal: la barra va hacia 150 palabras y el tope por tiempo es el de 5 min)
- `Escuchando · señal: decisión · 90/120 palabras · tope en 3:12` (hay señal local; la barra va hacia 120)
- `Señal: decisión · espera mínima · 130/120 palabras` (señal y palabras, falta el enfriamiento de 4 min)
- `Analizando 25:00–30:00 con haiku (señal: decisión)…` (el motivo real; también `5 min`, `a petición`, `cada 5 min`)
- `último 25:00–30:00 · señal: decisión · haiku · 3,2 s · 4,1k tokens`
- `Analizando 25:00–30:00 con haiku…`
- `Confirmando contradicciones con sonnet…`
- `Analizado 25:00–30:00 · haiku · 3,2 s · 4,1k tokens`
- `Analizado 25:00–30:00 · sin novedades`
- `Omitido 40:00 · 94 palabras nuevas (mín. 150)`
- `En pausa · análisis detenido`
- `Sin respuesta del modelo · reintento en el próximo ciclo`
- `Límite del plan alcanzado · análisis automático detenido`
- `Sesión no iniciada en Claude Code`
- `Transcripción con 18 s de retraso`
- `Puliendo con opus…`
- `Reunión terminada · 7 análisis · 48,2k tokens`

Sin signos de exclamación, sin "IA" y sin verbos antropomórficos como "pensando".

## No hacer

- Barra de progreso durante un análisis: no hay dato de avance.
- Más de un color por tarjeta o fondos de color por categoría.
- Sombras, bordes de 2 px o radios mayores de 8 fuera de lo indicado.
- Reordenar objetivos o checks, o mover la vista del usuario sin acción suya.
- Animar contadores de tokens o el cronómetro.
- Iconos, salvo marca de check, rombo de hito y flecha ↑.
- Modales durante la reunión.
- Datos inventados: un campo sin dato no se pinta.

## Orquestación de agentes

Sustituye a la línea de 32 px por una banda de 96 px bajo la cabecera, también en la pantalla de revisión. Se pliega a la línea del agente de 32 px con el botón «Plegar» (y se despliega con «Orquestación»); la preferencia queda en `localStorage` (`apuntes_orq_plegado`). Por debajo de 1100 px de ancho va siempre plegada.

**Contenido.** A la izquierda (408 px) la línea del agente apilada: estado en t-body-m, barra de palabras 56×3 con `118/150 palabras · próximo en 3:48`, `último …`, y los botones «Registro» y «Plegar». A la derecha el grafo, en 6 columnas y 2 filas de 37 px.

**Nodos.** Cada nodo es un agente o tarea que existe en la app, con nombre, modelo (o «local»), estado y su último dato real (tramo, duración, tokens, palabras, retraso). Un dato ausente no se pinta.

| Nodo | Qué es | Modelo |
|---|---|---|
| Escucha Micro, Escucha Reunión | Captura de audio (medidores) | captura |
| Transcriptor | Whisper, tramo a tramo | local |
| Contexto | Digest de los ficheros del proyecto | haiku (o caché) |
| Analista | Análisis periódico y «Analizar ahora» | haiku |
| Verificador | Confirma TODAS las contradicciones en una llamada, al terminar | sonnet |
| Redactor | Resumen final y cambios al contexto | sonnet |
| Pulidor | Solo si se pulsa «Pulir con Opus» | opus |
| Consultas | «Pregúntale»: una llamada por pregunta, solo si el usuario la lanza | haiku (sonnet si lo elige para esa pregunta) |

Estados: en espera, trabajando, hecho, error, omitido. Las escuchas son continuas y no llevan anillo: su movimiento son los medidores («escuchando» es su estado de trabajo). En simulación, escuchas y transcriptor figuran como «omitido · simulación».

**Conectores** (SVG): Escucha → Transcriptor → Analista; Contexto → Analista; Analista → Verificador → Redactor → Pulidor y Analista → Consultas (Verificador y Consultas comparten columna). Reflejan el orden real: Escucha y Transcriptor corren a la vez que el Analista; las llamadas al modelo van en serie.

**Animación, solo mientras hay trabajo real** (azul y neutros; sin halos, gradientes ni neón):

| Evento | Qué cambia | ms | Curva |
|---|---|---|---|
| Nodo trabajando | Anillo azul fino que recorre el contorno (`stroke-dashoffset`, bucle) y cronómetro real | 1600 | lineal |
| Conector activo | Trazos azules que avanzan en el sentido del flujo mientras corre la etapa de origen | 600 | lineal |
| Tarea terminada | Un pulso único por los conectores de salida; la marca del nodo se traza; el dato cambia en seco | 400 | salida |
| Resultado en una columna | Un trazo breve del Analista al encabezado de Insights, Objetivos o Checks, sin mover el scroll de nadie | 400 + 400 | salida |
| Popover «Registro» | Opacidad, y 4→0 | 120 | salida |

En reposo solo se mueven `●REC` y los medidores. Con `prefers-reduced-motion` no hay bucles: estado fijo y texto.

**Datos reales, sin puesta en escena.** El backend emite por el WebSocket `{tipo: "tarea", fase: inicio|fin, id, agente, modelo, tramo, hora, ms, tokens, ok, error}` desde el punto único de las llamadas al LLM (`Analista._llamar`, envuelto en `apuntes/orquesta.py`) y desde el transcriptor (cada tramo y la carga del modelo), y `{tipo: "traza", fila: analisis|omitido|fallo, …}` por cada análisis. El snapshot de reconexión lleva `tareas` y `traza`. No hay llamadas nuevas al modelo ni cambia el reparto de modelos. Ningún temporizador simula actividad: el único `setInterval` de la orquestación solo existe mientras haya una tarea en curso y solo refresca el cronómetro.

**Clic en un nodo** abre el «Registro» filtrado por ese agente, con sus llamadas reales (hora, tramo, modelo, duración, tokens, resultado). «Registro» sin filtro muestra las últimas 20 entradas de traza.

## Banda «Sesión» (línea de tiempo de la propia reunión)

Distinta del Gantt del proyecto (ese es del plan y solo existe si hay plan; esta es de la reunión en curso y existe siempre). Va a todo el ancho, entre la línea de avisos y el cuerpo de la pantalla de reunión, y en la revisión aparece completa sobre el resumen. Solo pinta datos reales: sin dato no hay marca y nada se inventa (`web/sesion.js`, `web/sesion.css`; componente `window.GanttSesion`, independiente de la app).

- **Altura.** Unos 132 px con cinco filas: cabecera 28 (plegar, rango `00:00 – 12:34`, filtros), eje 14, Temas 20, Objetivos 30 (crece solo si hay más de 4 objetivos: 8 px por fila y objetivo, reservado desde el principio, nunca durante la reunión), Insights 28 y Tú 14. Plegada mide 28 px; la preferencia se recuerda (`apuntes_sesion_plegado`) y también los filtros. En el Modo reunión no se pinta (queda plegada del todo; el Gantt completo está en la revisión).
- **Eje.** De 00:00 al minuto actual, con un mínimo de 2 minutos para que la línea de «ahora» no pegue al borde. Se reescala con la reunión en 900 ms lineales (`left` y `width`), así que no hay saltos; no toca el scroll de ninguna columna. Marcas de tiempo cada 30 s, 1, 2, 5, 10, 15, 30 o 60 min según el ancho (≥56 px entre marcas). Marcas pequeñas de análisis sobre el eje, con su motivo en el `title` («Análisis 3 · señal: decisión · 25:00»). Línea de «ahora» en acento.
- **Temas.** Una barra por tramo con el título corto del tema (campo `e` de la llamada periódica, máx. 40 caracteres). Los tramos seguidos con el mismo título se unen y cada tema llega hasta el inicio del siguiente; alternan fondo acento suave y panel. Sin título no hay barra.
- **Objetivos.** Una barra por objetivo con evidencia, desde su primera evidencia hasta la última (`t_primero` y `t_seg`), con el color de su estado: parcial acento al 75 %, cubierto verde. Un objetivo sin evidencia no tiene barra; uno sugerido sin confirmar, tampoco. Ancho mínimo 6 px. Una barra por fila: nunca se solapan.
- **Insights y Tú.** Marcadores de 12 px, forma y color por tipo: decisión, cuadrado lleno en texto primario; pendiente, círculo lleno en acento; pregunta, anillo en texto cuerpo; riesgo, triángulo rojo; contradicción, rombo rojo (ámbar si es «posible»); idea, rombo hueco apagado. El carril Tú lleva las anotaciones propias (comentario, cuadrado hueco; pregunta, anillo; idea, rombo hueco) en acento como texto. Filtro por tipo en la cabecera (`aria-pressed`), con «tú» como un tipo más.
- **Sin solapes.** Los marcadores se reparten en dos filas (Tú, una) y, si en un punto no caben, se agrupan en un marcador de 22 px con contador (`99+` como máximo). Cada dato está representado: sueltos más los de dentro de grupos suman el total. Se mide con `getBoundingClientRect` a 1440 y 1920 px (`tests\test_gantt_sesion_layout.py`): 0 solapes con 293 datos, unos 110 de ellos en cuatro ventanas de pocos segundos.
- **Interacción.** Hover o foco: tooltip con el texto completo (`[12:34] Decisión: …`; en un grupo, hasta 6 líneas y «… y N más»). Clic o Intro: lleva a la línea de transcripción (30 %, igual que el chip de minuto) y a la tarjeta, anotación o fila de objetivo, con la barra lateral de 2 px durante 1,6 s; un grupo lleva a su primer miembro. Teclado: un solo tabulador por carril (tabindex itinerante); flechas, Inicio y Fin recorren el carril; Esc cierra el tooltip. Cada marcador es un `button` con `aria-label` («Decisión 01:55: …»).
- **Movimiento.** Solo entra con un fundido de 180 ms (salida) al aparecer un marcador, barra o tema nuevo (no en el primer pintado ni con movimiento reducido). Con `prefers-reduced-motion`, sin transiciones.

## Anotaciones propias, «Pregúntale» y objetivos propios

- **Anotación rápida**, junto a «Notas»: un campo y tres botones (Comentario, Pregunta, Idea; Intro guarda un comentario). Se guarda con el minuto actual, aparece en el carril Tú y en Insights («Tus anotaciones», con la marca «tú»), se edita y se borra, y viaja con el siguiente análisis como las notas. Nunca se convierte en decisión. «Preguntar a la IA» en una pregunta tuya la lanza a Pregúntale solo con ese clic.
- **Pregúntale**, debajo de Insights, en su propia zona: campo, selector haiku/sonnet para esa pregunta y «Preguntar». Una llamada por pregunta, una a la vez. La respuesta es corta y lleva citas clicables: el minuto (como cualquier chip) y el fichero (abre el contexto). Si no hay base en los datos, lo dice («sin base en los datos»). El historial es visible y entra en el .md. Es el nodo «Consultas» de la orquestación; no se pinta en el Modo reunión.
- **Objetivos propios.** Sin plan (o en «Otra reunión») se escriben antes de empezar (inicio) o durante la reunión (campo bajo la lista). Los que sugiere el digest llevan «sugerido» (borde punteado azul, como los checks) con «Confirmar» y «Descartar»; no se evalúan hasta que se confirman.
- **Añadir carpeta de proyecto**, en el inicio y en Ajustes: nombre, ruta y «compartida». El Guardian la valida y muestra el motivo si la rechaza; se guarda en `proyectos_extra`.

## Modo reunión (implementado; ver README y `pruebas\probar_modo_reunion.py`)

Aprobado por el autor. Para seguir la reunión de Teams con la app delante, sin incrustar Teams.

- Un botón en la cabecera compacta la ventana y la deja siempre encima (`HWND_TOPMOST`). Otro clic vuelve a la vista completa. Nunca corta la grabación.
- Paneles laterales con hueco central real (`SetWindowRgn`): Teams se ve nítido y recibe los clics a través del hueco. A 1440 px, unos 360, 720 y 360 px, con divisores arrastrables; la medida se recuerda.
- Panel izquierdo: transcripción. Panel derecho: insights, objetivos y checks. Orquestación plegada en su línea de 32 px.
- Control de opacidad de los paneles, 60-100 %, por ventana entera (`WS_EX_LAYERED`). Si falla con WebView2, se oculta el control y se documenta; el hueco central no depende de él.
- Debe mantenerse la exclusión de captura. Comprobar `GetWindowDisplayAffinity` en este modo y, con el usuario, en un Teams compartido.
- Por debajo de 1280 px de ancho de pantalla, el hueco no cabe: pasa a un único panel lateral.

## Criterios de aceptación, medibles en el navegador

1. Todo texto usa DM Sans y `tabular-nums`; nada usa `monospace` ni `serif`.
2. Los colores computados están en la tabla; no hay `gradient` ni `filter: blur` (el cristal de cabecera de la app de referencia queda fuera).
3. Esperando: ningún bucle además de `●REC` y medidores. Trabajando: solo los de la tarea en curso (anillo del nodo, trazos del conector de salida e indicador de la línea del agente), y vuelven a cero al terminar. Un nodo solo anima durante su trabajo real.
4. Con Insights a `scrollTop` 600, insertar 5 tarjetas no cambia la línea visible y muestra `5 nuevos ↑`.
5. Clic en un chip: la línea queda al 30 % ±8 px y resaltada al menos 1,5 s.
6. La barra de palabras mide 56×3 y su relleno es proporcional, con tope de 56 px.
7. A 1440 px, columnas de 464, 456 y 456 ±2. A 1920, proporción 1:2 ±1 %.
8. Toda traza usa datos reales; un dato ausente no se renderiza, sin guiones.
9. Botones y chips accesibles con Tab y con outline; orden: cabecera, línea del agente, transcripción, objetivos, checks, insights.
10. Texto cuerpo ≥7:1; etiquetas y chips ≥4,5:1 en ambos temas, con la única excepción declarada.
11. Con movimiento reducido, `getAnimations()` devuelve solo los medidores.
12. Con un límite del plan simulado, el indicador es rojo y la última fila es un fallo con "Reintentar".
13. Los estados de los nodos salen de eventos `tarea` reales: orden Analista → Verificador → Redactor → Pulidor en serie, sin nodo en `trabajando` sin evento de inicio.
14. Con la banda plegada mide 32 px y desplegada 96 px; la preferencia se recuerda.
15. Banda «Sesión»: plegada mide 28 px y desplegada unos 132 px (más solo si hay más de 4 objetivos); al avanzar la reunión ningún `scrollTop` cambia.
16. Con 200 o más marcadores (unos cien en ventanas de pocos segundos) no hay dos elementos del mismo carril cuyos `getBoundingClientRect` se crucen a 1440 y a 1920 px, y ninguno sale de su carril.
17. Cada marcador es un botón con `aria-label`; Tab entra una vez por carril y las flechas recorren el carril; Intro lleva a la tarjeta y a la línea de transcripción.
