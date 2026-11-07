# Apuntes: giro visual (vidrio, luz y materiales)

Definido por Fable el 2026-11-04 a petición del autor («mucho más visual, efectos glassy, transiciones, hovers, diseños, agéntico todo»). Manda sobre `DESIGN-agentico.md` y `DESIGN-equipo.md` en todo lo estético; lo funcional de los dos (eventos reales, texto completo, vista que no se mueve, Modo reunión, presupuesto de tokens, ids del DOM) sigue intacto. Prototipo que lo muestra: `pruebas\_visual\prototipo.html` (autónomo, datos ficticios).

> **Estado (2026-11-04).** Implementado en `web/` (inicio, reunión, Modo reunión y revisión). **Renombrado decidido por el autor:** el panel que se llamaba «Bandeja» pasa a llamarse **«Hallazgos»** en todo texto visible, `aria-label`, `title` y documentos (botón «Hallazgos N», cabecera, vacío «Todavía no hay hallazgos.»). Los ids (`r-bandeja`, `r-bandeja-btn`, `r-bandeja-lista`…) y las claves internas (`apuntes_bandeja_*`) no cambian. No tiene relación con la «Bandeja (reunión sin proyecto)» ni con la carpeta `bandeja\`, que son otro concepto y siguen llamándose así.

> **Revisión de capturas (2026-11-04).** (1) En Modo reunión los avisos van SIEMPRE sobre `--elev-solido`, sea cual sea el nivel de Efectos. (2) En medio y en movimiento reducido, avisos, cajón y diálogo también pasan a sólido. (3) Con Hallazgos abierto, la pila de avisos se desplaza a su izquierda (right 428 px, con transición); en Modo reunión empieza bajo la cabecera y los filtros del panel (`--bj-cab-h`). «Cerrar» y los filtros quedan siempre pulsables. (4) Los temas de la banda Sesión nunca se solapan: cada uno empieza donde acaba el anterior y, si queda con ancho casi nulo, la barra la ocupa el más reciente y el otro va en su tooltip. (5) La leyenda de la banda Sesión usa los colores reales de cada tipo; un filtro apagado pasa a `--soft` y tachado (≥ 3:1). (6) Sin textos cortados (requisito del autor): ver §14.5. La cabecera pasa a dos filas (tema y proyecto debajo) cuando no caben; por debajo de 1400 px cede el nombre de la marca, los medidores y los monogramas de los nodos.

> **Jerarquía de la vista de reunión (2026-11-06).** El autor: «está todo muy desordenado, tamaños de letras…», «no se ve lo importante», «no se distingue», «los iconos de las notis son muy cutres». Cambios que mandan sobre lo anterior (§5, §9, §11 y §14.12 ya recogen lo que cambia): (1) **escala única de CINCO tamaños** (22 · 15 · 14 · 12 · 11; desaparecen el 28 y el 13) y una sola etiqueta de sección (11, mayúsculas, 600, `--soft`); (2) **cabecera de una fila de 48 px** (en menos de 1620 px, Efectos, Modo y Ajustes pasan a «Más»); (3) **banda Orquestación plegada por defecto** a una línea («Equipo: hecho · Monitor escuchando · 3 turnos · 5,5k»; se despliega con un clic y la preferencia se recuerda); (4) **dos columnas**: izquierda la transcripción (una fila por intervención) y las Notas plegables; derecha el carril «Ahora» fijo arriba y pestañas (Consejos e Insights primero; Objetivos, Equipo, Pregúntale y Sesión detrás); (5) «Ahora»: la respuesta es el titular (22) y una no-respuesta («No hay base…») va atenuada en una línea; (6) **un icono SVG por tipo** (`web/iconos.js`, trazo único, sin red) con color semántico propio (`--t-*`) y jerarquía: lo importante (decisión, pendiente, riesgo, contradicción) lleva barra de color y tinta plena, lo secundario (pregunta, idea, regla, definición) va atenuado. El Modo reunión hereda la misma escala y jerarquía.
> **Medido a 1536×880 CSS (1920×1100 a 125 % de Windows).** Los «12, 13, 14, 16, 18, 20, 28, 34 px» de la captura son tamaños de pantalla (CSS × 1,25): 28/34 = el titular de 22 y el cronómetro de 28; 16 = el 13 de los monogramas y las pestañas del Modo reunión. La escala se verifica ahora midiendo en CSS (`tests/test_visual.py`).

## 1. La idea en una frase

**Tres materiales: la reunión es grafito, el equipo es vidrio que solo se enciende cuando hay trabajo real, y lo tuyo es papel.**

- **Grafito**: la transcripción y el fondo. Opaco, continuo, denso, sin brillo. Es la materia prima.
- **Vidrio**: todo lo que el equipo extrae de la reunión (tarjetas de perfil, insights, nodos de orquestación, notificaciones, Hallazgos, Registro). Translúcido, con canto iluminado, flota sobre el grafito. Apagado en reposo; cuando un agente trabaja, su lámina se enciende con una **luz de trabajo** azul que recorre su contorno y viaja por los conectores. Esa luz es la única fuente de color saturado de la pantalla y solo existe mientras hay un evento `tarea` abierto.
- **Papel**: lo que escribe el usuario (Notas, anotación rápida, carril «Tú», objetivos propios). Superficie cálida, mate, sin vidrio ni luz: lo humano no se enciende, se escribe.

Firma visual reconocible: pantalla oscura de vidrio sobre una luz ambiente fija y fría; nada parpadea ni respira; **la luz aparece solo donde hay trabajo**. No es un dashboard de IA morado con degradados: la paleta es casi monocroma (grafito, hielo, azul de trabajo) y el calor viene únicamente del papel.

## 2. Los cinco movimientos que dan el 80 % del salto

1. **Materiales y elevación.** Una capa ambiente fija bajo toda la app (dos luces radiales estáticas, sin animación) y cuatro niveles de superficie (grafito, vidrio fino, vidrio flotante, papel) con canto iluminado de 1 px y sombra tintada. Es lo que convierte «paneles planos con filete» en profundidad. Toca `app.css` (tokens y `.panel`, `.tarj`, `.eq-tarj`, `.nodo`, `.registro`, `.drawer`, `.notif`, `#r-bandeja`, `.notas`, `.tuya`).
2. **Luz de trabajo.** La tarjeta del perfil que trabaja recibe un anillo cónico que gira por su borde (`conic-gradient` + máscara, 1.600 ms lineal) y un halo fijo; el nodo de la banda hace lo mismo; el conector de salida lleva un haz con estela; al terminar, la marca se traza y la cabecera de la columna que recibe resultados recibe un pulso de 400 ms. Todo nace de `tarea inicio` y muere en `tarea fin`: cero temporizadores decorativos. Es lo que hace que «agéntico» se vea.
3. **Notificaciones y Hallazgos de vidrio.** La pila entra con desenfoque que se resuelve (blur 6→0, y −12→0, escala .97→1, 320 ms), escalonada a 900 ms, y al cumplir su vida **vuela** hasta el botón «Hallazgos N», que la recibe con un pulso del contador. El panel Hallazgos es una lámina de vidrio flotante que se desliza desde la derecha con sus filtros como chips; los tipos van por forma + color + etiqueta.
4. **Sistema de hover y pulsación.** Toda superficie interactiva de vidrio se eleva 1 px y aclara su canto en 160 ms; toda pulsación comprime a .985; todo chip de minuto enciende la línea de transcripción destino antes de llevar a ella; foco en doble anillo (azul + separación del fondo). Hoy el hover solo cambia el fondo: esto es lo que hace sentir que la interfaz responde.
5. **Transiciones de pantalla y de estado.** Cambio inicio → reunión → revisión con la API nativa de View Transitions (cross-fade 260 ms con la cabecera fija); plegado de las bandas Orquestación y Sesión con altura interpolada (260 ms) en vez de salto; colapso de diffs decididos y de la lista de checks con la misma curva. Un solo `document.startViewTransition` envolviendo el `mostrarVista` actual (hook `AP.hooks`), con fallback a lo de hoy.

## 3. Reglas que quedan derogadas y cuáles las sustituyen

| Regla antigua (`DESIGN-agentico.md` / `DESIGN-equipo.md`) | Queda | Sustituida por |
|---|---|---|
| «Sin gradientes, halos ni sombras en oscuro»; criterio 2 («no hay `gradient` ni `filter: blur`») y criterio 10 de equipo | **Derogada** | §4: gradientes solo en la capa ambiente (radiales, estáticos) y en la luz de trabajo (cónico, solo durante `tarea`); sombras tintadas en ambos temas según nivel; `backdrop-filter` solo en vidrio flotante, con el presupuesto de §6 |
| Radios 3 / 6 / 8 / 0 | **Derogada** | Chips 4, botones e inputs 8, tarjetas de vidrio fino 10, vidrio flotante 14 (como ya tenía `.notif`), papel 10, paneles y bandas 0. Regla concéntrica: radio exterior = interior + relleno |
| Paleta (`#1B1B20`, `#007AFF`, `#686868`…) | **Derogada** | Tokens de §4. El acento pasa de `#007AFF` a un azul de trabajo (`#2E7CF6` relleno; `#7EB4FF` como texto en oscuro, `#1D5FC4` en claro) y aparece el material papel |
| «Iconos, salvo marca de check, rombo de hito y flecha ↑» | **Derogada en parte** | Siguen sin iconos de librería. Se admiten: monogramas de perfil (CO, AF, CT, RV, MO, AN), los glifos geométricos de tipo (ya existentes en Sesión y Hallazgos), la marca de check, el rombo de hito y las flechas |
| «Sombras: ninguna en oscuro; en claro solo menús y popovers» y la excepción de `.notif` | **Derogada** | Sombra por nivel de elevación en ambos temas (§4); la excepción de `.notif` deja de serlo porque es la regla |
| «Un solo acento» | **Matizada** | Un solo acento de luz (azul). El papel no es un acento: es un material neutro cálido sin uso semántico; los semánticos (verde, rojo, ámbar) siguen |
| Hover «fondo 120 ms vaivén» | **Sustituida** | §8: elevación + canto + fondo en 160 ms salida; pulsación .985 en 80 ms |
| Movimiento de la app de referencia (x 16→0 al cambiar de pantalla) | **Sustituida** | View Transitions, §7 |
| Tipografía DM Sans, escala y `tabular-nums` | **Se mantiene** | Ver §5: DM Sans sigue; se añade el peso 300 para el cronómetro y la cabecera de notificación pasa a la escala |
| Todo lo funcional: actividad = evento `tarea`, texto completo, «N nuevos ↑», sin mover la vista, Modo reunión, `prefers-reduced-motion`, contraste AA, foco visible, ids del DOM, sin red ni build, sin exclamaciones ni «IA» ni «pensando» | **Se mantiene** | Y se añade el interruptor «Efectos» (§6) |

## 4. Tokens

Dos temas (`:root[data-theme="dark"]` y `light`, más `prefers-color-scheme` como hoy). Derivados marcados con *.

### Fondo y ambiente

| Token | Oscuro | Claro | Uso |
|---|---|---|---|
| `--bg0` | `#121317` | `#EEF0F4` | Fondo profundo bajo todo |
| `--luz-1` | `radial-gradient(640px 480px at 18% 0%, rgba(46,124,246,.20), transparent 70%)` | `… rgba(46,124,246,.16) …` | Luz ambiente principal, fija |
| `--luz-2` | `radial-gradient(900px 600px at 100% 100%, rgba(80,120,200,.10), transparent 70%)` | `… rgba(46,124,246,.08) …` | Luz ambiente secundaria, fija |
| `--vineta` | `radial-gradient(120% 100% at 50% 50%, transparent 60%, rgba(0,0,0,.35))` | `transparent 60%, rgba(27,27,32,.08)` | Cierra los bordes |

La capa ambiente es UN elemento `position: fixed; inset: 0; z-index: 0; pointer-events: none` con los tres gradientes apilados. **No se anima nunca**: el ambiente no respira, lo único que se mueve es el trabajo. Con `data-efectos="apagado"` no se pinta y `--bg0` pasa a ser el fondo plano.

### Niveles de superficie

| Nivel | Token | Oscuro | Claro | Dónde |
|---|---|---|---|---|
| 0 Grafito | `--grafito` | `rgba(24,25,31,.78)` | `rgba(255,255,255,.72)` | Cabecera, pie, columnas, banda Sesión, Modo reunión (ahí opaco: `#18191F` / `#FFFFFF`) |
| 1 Vidrio fino | `--vidrio` | `rgba(255,255,255,.045)` | `rgba(255,255,255,.60)` | Tarjetas de perfil, insights, nodos, línea del Monitor, trazas, botones fantasma en hover |
| 1 canto | `--canto` | `rgba(255,255,255,.08)` | `rgba(27,27,32,.08)` | Borde de 1 px de todo vidrio |
| 1 brillo | `--brillo` | `inset 0 1px 0 rgba(255,255,255,.07)` | `inset 0 1px 0 rgba(255,255,255,.9)` | Canto superior del vidrio fino |
| 2 Vidrio flotante efímero | `--vidrio-f` | `rgba(28,29,36,.90)` | `rgba(255,255,255,.90)` | Notificaciones y tooltip: pequeños, breves. **Revisado 2026-11-04**: a .62/.66 el texto de debajo se leía a través del aviso en cuanto el desenfoque fallaba o faltaba (Efectos medio, WebView2 sin GPU). Con .90 el peor caso (píxel de texto debajo) da ink ≥ 7:1 y `--soft` ≥ 4,5:1; el aspecto de vidrio lo dan el canto, el brillo, la sombra tintada y, cuando está, el desenfoque |
| 2 Vidrio flotante de lectura | `--vidrio-fl` | `rgba(24,25,31,.92)` | `rgba(255,255,255,.90)` | Hallazgos, Registro, cajón de contexto, diálogos: superficies largas de lectura; el desenfoque solo suaviza lo que asoma. Medido en el prototipo: a .66 el texto de Insights se leía a través del panel Hallazgos en cuanto faltaba el desenfoque (GPU deshabilitada), así que la legibilidad no puede depender del filtro |
| 2 desenfoque | `--vidrio-blur` | `blur(16px) saturate(140%)` | `blur(16px) saturate(120%)` | Solo nivel 2, ver §6 |
| 2 sombra | `--sombra-f` | `0 16px 48px rgba(0,0,0,.45), 0 1px 0 rgba(255,255,255,.06) inset` | `0 16px 48px rgba(27,27,32,.14), 0 1px 0 #FFF inset` | Solo nivel 2 |
| 1 sombra | `--sombra` | `0 1px 2px rgba(0,0,0,.3)` | `0 1px 2px rgba(27,27,32,.06)` | Vidrio fino en hover |
| Papel | `--papel` | `#26231F` | `#F7F2EA` | Notas, anotación rápida, «Tus anotaciones», objetivos propios, campo de Pregúntale (lo que escribe el usuario) |
| Papel canto | `--papel-canto` | `rgba(255,228,190,.10)` | `rgba(120,90,40,.14)` | Borde del papel |
| Sólido de respaldo | `--elev-solido` | `#1E1F26` | `#FFFFFF` | Lo que usa el nivel 2 con Efectos apagado |
| Hover de fila | `--hover` | `rgba(255,255,255,.05)` | `rgba(27,27,32,.045)` | Filas de transcripción, feed, Hallazgos, lista de proyectos |
| Selección | `--sel` | `rgba(46,124,246,.14)` | `rgba(46,124,246,.10)` | Línea destino, ítem seleccionado |
| Filete | `--hair` | `rgba(255,255,255,.07)` | `rgba(27,27,32,.08)` | Separadores |
| Filete fuerte | `--hair2` | `rgba(255,255,255,.14)` | `rgba(27,27,32,.16)` | Rieles, cajas, scrollbar |

### Texto y acento

| Token | Oscuro | Claro | Contraste mínimo medido sobre el peor fondo del nivel |
|---|---|---|---|
| `--ink` | `#F4F4F6` | `#17181C` | 14:1 |
| `--body` | `#BDBDC7` | `#363842` | 8,6:1 / 10:1 |
| `--soft` | `#9A9AA6` | `#5F6170` | 5,9:1 sobre vidrio flotante oscuro iluminado; 6,2:1 sobre vidrio flotante claro |
| `--acc` | `#2E7CF6` | `#2E7CF6` | Relleno (botón primario, barra de palabras, barras de novedad, línea «ahora») |
| `--acc-t` | `#7EB4FF` | `#1D5FC4` | Texto y chips: 7,4:1 / 6,4:1 |
| `--acc-soft` | `rgba(46,124,246,.16)` | `rgba(46,124,246,.10)` | Fondo de chips |
| `--luz` | `rgba(46,124,246,.55)` | `rgba(46,124,246,.45)` | Anillo y haz de trabajo |
| `--halo` | `0 0 0 1px rgba(46,124,246,.35), 0 0 28px rgba(46,124,246,.22)` | `0 0 0 1px rgba(46,124,246,.35), 0 0 28px rgba(46,124,246,.18)` | Halo fijo del elemento que trabaja |
| `--ok`, `--err`, `--warn` | `#5ED38B`, `#F28B82`, `#F0A94E` | `#1E8A4C`, `#B3261E`, `#B25E09` | Igual que hoy; fondos semánticos a alfa .12 |

Regla de contraste sobre vidrio: `--soft` solo en `t-meta` y `t-label` (≥12 px o 11 px a 600); nunca a 11 px 400. `--acc-t` nunca en claro con peso 400 por debajo de 12 px. El blanco 600 sobre `--acc` (botón primario) sigue siendo la única excepción (4,6:1).

### Color por tipo (revisión 2026-11-06)

| Token | Oscuro | Claro | Uso |
|---|---|---|---|
| `--t-decision` | `#5ED38B` | `#187A41` | decisión (importante) |
| `--t-pendiente` | `#F0A94E` | `#A35508` | pendiente (importante) |
| `--t-riesgo` | `#F28B82` | `#B3261E` | riesgo (importante) |
| `--t-contradiccion` | `#F29AD0` | `#A3226F` | contradicción (importante) |
| `--t-consejo`, `--t-respuesta` | `#7EB4FF` | `#1D5FC4` | consejos y respuesta de «Ahora» |
| `--t-pregunta` | `#6FD0DE` | `#0B7285` | pregunta (secundario) |
| `--t-idea` | `#C4A8F5` | `#6D3FB8` | idea (secundario) |
| `--t-regla` | `#A9B4D0` | `#50607E` | regla (secundario) |
| `--t-definicion` | `#7FD6C2` | `#0F766E` | definición (secundario) |

### Radios, espaciado, foco

- Radios: chip 4; botón, input y nodo 8; tarjeta de vidrio fino y papel 10; vidrio flotante 14; monograma 8 dentro de tarjeta de 14 (concéntrico: 14 − 6 de relleno ≈ 8); paneles y bandas 0.
- Espaciado base 4 como hoy; tarjetas 12×12 (notificación 12 14); columnas 464 | 448 | 448 a 1440 px con padding 0 24.
- Foco: `outline: 2px solid var(--acc); outline-offset: 2px; box-shadow: 0 0 0 4px var(--bg0)` (doble anillo, visible sobre vidrio y sobre luz).
- Scrollbar: 10 px, pulgar `--hair2`, carril transparente, radio 6 (como hoy).

## 5. Tipografía

DM Sans local se mantiene (`web/fuentes`, sin CDN): tiene los pesos 300-700 y las cifras tabulares que necesita una pantalla que cuenta segundos y tokens. **Escala fija de CINCO tamaños** (revisión 2026-11-06), por variable: `--f-22 --f-15 --f-14 --f-12 --f-11`. Cada uno tiene un papel y solo uno:

| Token | Papel | Dónde |
|---|---|---|
| `--f-22` | titular | la respuesta de «Ahora» (solo la primera viñeta), el cronómetro, el título de pantalla y el proyecto del contexto |
| `--f-15` | título | pregunta de «Ahora», titular de cada consejo, tema de la reunión, títulos de Hallazgos y del cajón |
| `--f-14` | cuerpo | transcripción, texto de tarjetas y consejos («por qué»), botones, pestañas, campos |
| `--f-12` | meta | minutos, modelo, confianza, línea de orquestación, recuentos, botones mini |
| `--f-11` | etiqueta | UNA sola etiqueta de sección: 11, mayúsculas, 600, +0,06 em, `--soft` (Transcripción, Notas, Insights e ideas, Equipo, Objetivos, Checks…) y los recuentos de las pestañas |

| Clase | Medida | Cambio |
|---|---|---|
| `t-display` | 22/28 600 −0,01em | igual |
| `t-cron` | **22/28 500 −0,01em** | antes 28/32 300: en la cabecera compacta es el mismo titular de la escala, no un tamaño aparte |
| `t-title` | 15/20 600 | igual |
| `t-body` / `t-body-m` | 14/20 400 / 500 | igual; `text-wrap: pretty` en tarjetas y notificaciones |
| `t-meta` | 12/16 500 +0,01em | igual |
| `t-label` | 11/14 600 +0,06em mayúsculas | igual; es la etiqueta de sección de TODA la pantalla de reunión |
| `t-mono` | 12/16 600 +0,04em | antes 13/18: el 13 sale de la escala |

Prohibido introducir tamaños sueltos: todo por variable.

## 6. Presupuesto de rendimiento (faster-whisper en CPU, horas en WebView2)

**Dónde se permite `backdrop-filter`** (nivel 2, y nada más):

| Elemento | Permitido | Tope simultáneo |
|---|---|---|
| `.notif` | Sí, solo las 4 primeras de la pila (`:nth-child(n+5)` pasa a `--elev-solido`) | 4 |
| `#r-bandeja` | Sí, mientras está abierta | 1 |
| `.registro`, `.sb-tip`, `.drawer`, `.dialogo` | Sí | 1 (son excluyentes en la práctica) |
| `.mr-barra` (Modo reunión) | **No**: la ventana ya tiene opacidad propia y detrás no hay app, solo el propio panel | 0 |
| Columnas, bandas, cabecera, pie, nodos, tarjetas de perfil, insights, trazas, chips | **No**: vidrio por alfa sobre la capa ambiente, sin filtro | 0 |

Total: como máximo **6 elementos con `backdrop-filter` a la vez**, con un área sumada ≤ 25 % del viewport (a 1440×900: 4 notificaciones de 360×~150 más el panel Hallazgos de 420×820 ≈ 23 %). Recuerda que el desenfoque solo ve la propia app: por eso hay una capa ambiente debajo y por eso las columnas son translúcidas; sin eso el vidrio flotante no tendría nada que difuminar.

**Capas de composición**: capa ambiente (1, estática), columnas (sin `will-change`), vidrio flotante (`will-change: transform, opacity` solo durante su entrada y salida, retirado al terminar), luz de trabajo (1 elemento con animación mientras hay `tarea`). Ningún `will-change` permanente.

**Lo que nunca lleva filtro, sombra animada ni gradiente**: `.lin` (transcripción), `.eq-fila` (Minuto a minuto), `.bj-f` (filas del panel Hallazgos), `.tarj` dentro de la lista, `.chk-fila`, `.obj`, marcadores de la banda Sesión, filas del Registro y del diff. En listas largas solo hay `background-color` en hover (160 ms) y el fundido de 180 ms al entrar. Sin `filter: blur` de entrada en nada que pueda llegar de 20 en 20.

**Animaciones en reposo**: `●REC` y los medidores, nada más (como hoy). El ambiente no respira. Con el WebSocket cortado, `getAnimations()` devuelve solo esos dos.

**Interruptor «Efectos»** (Ajustes y botón en la cabecera; `localStorage` `apuntes_efectos`, `body[data-efectos]`):
- `alto` (defecto en vista completa): todo lo anterior.
- `medio` (defecto en Modo reunión, donde el CPU manda y la ventana ya es translúcida): sin capa ambiente ni desenfoque de entrada en notificaciones; `backdrop-filter` solo en Hallazgos y Registro; la luz de trabajo sigue (es información).
- `apagado`: sin `backdrop-filter` en nada (nivel 2 pasa a `--elev-solido`), sin capa ambiente, sin anillo cónico (el trabajo se indica con el halo fijo, la barra de 2 px y el cronómetro), transiciones a 120 ms. **No se pierde información**: todos los estados siguen distinguibles por texto, forma y color plano.
- `prefers-reduced-motion` fuerza `apagado` para los bucles y la entrada (las transiciones de hover quedan en 0 ms); un dato nuevo aparece en seco.

**Cómo se mide** (criterios para el implementador, en WebView2 con DevTools `--remote-debugging-port` o en Edge con el prototipo):
1. Reposo con reunión en curso, 30 s: Performance muestra 0 repintados por segundo fuera de `●REC` y medidores; proceso del WebView2 en el Administrador de tareas ≤ 3 % de CPU en una máquina con faster-whisper transcribiendo.
2. Entrada de 4 notificaciones escalonadas: ningún frame > 16 ms en la pista Main; Rendering → Paint flashing solo enciende la pila y el botón Hallazgos.
3. Un turno completo (anillo 10 s + fin): la capa animada es una sola (`Layers` muestra la tarjeta) y desaparece al `tarea fin`.
4. Transcripción con 2.000 líneas y scroll a rueda: ≥ 55 fps con el panel Hallazgos abierto encima (el desenfoque del panel Hallazgos no se recalcula al desplazar la columna de debajo si Hallazgos tiene su propia capa; si cae de 55, el implementador quita `saturate` primero y reduce `blur` a 12 antes de tocar nada más).
5. `document.querySelectorAll('[style*=backdrop]').length` y el cómputo de `backdrop-filter` ≠ none ≤ 6 en cualquier momento (test de layout, como los de Gantt).

## 7. Biblioteca de transiciones

Curvas: `--salida: cubic-bezier(.16,1,.3,1)`, `--entrada: cubic-bezier(.4,0,1,1)`, `--vaiven: cubic-bezier(.4,0,.2,1)`, `--muelle: cubic-bezier(.34,1.3,.64,1)` (solo en pulsos y en el aterrizaje en Hallazgos; nunca en salidas).

| Evento | Qué cambia | ms | Curva | Dispara |
|---|---|---|---|---|
| Hover de vidrio (tarjeta, nodo, botón, chip) | `translate 0 −1px`, canto `--hair2`→`rgba(acc,.45)`, fondo | 160 | salida | puntero o foco |
| Pulsación | `scale .985` | 80 ida / 160 vuelta | entrada / salida | `:active` |
| Hover de fila (transcripción, feed, Hallazgos, lista) | solo `background-color` | 160 | salida | puntero |
| Chip de minuto en hover | la línea destino enciende `--sel` y barra de 2 px | 120 | salida | puntero sobre el chip |
| Clic en minuto | scroll al 30 % | 260 | salida | clic o Intro |
| Resaltado de línea | fondo y barra, luego se disipa | 1600 + 400 | salida | tras el scroll |
| Perfil: en espera → su turno | estado, canto a `--acc-t` | 180 | salida | elección del Monitor |
| Perfil: su turno → trabajando | anillo cónico aparece (opacidad 0→1), halo, barra 2 px, cronómetro | 180 | salida | `tarea inicio` |
| Trabajando, en bucle | ángulo del anillo cónico 0→360° | 1600 | lineal | mientras la tarea sigue |
| Haz del conector | `stroke-dashoffset` con estela (dos trazos: 2 px y 6 px al 25 %) en los conectores que ENTRAN al nodo que trabaja (lo que está leyendo: Monitor → Equipo y Contexto → Equipo durante un turno) | 600 | lineal | mientras corre la etapa de destino |
| Pulso de salida | Un trazo único de 14 px recorre los conectores que SALEN del nodo que termina | 400 | salida | `tarea fin` ok |
| Trabajando → hecho | anillo se funde (0 en 200), marca trazada (`stroke-dashoffset`), halo a 0 | 400 | salida | `tarea fin` ok |
| Trabajando → error | anillo a rojo fijo, sin bucle | 180 | salida | `tarea fin` error |
| Pulso de llegada en cabecera de columna | `box-shadow` 0→`--halo`→0 y trazo breve desde la tarjeta | 400 + 400 | muelle, salida | tarjetas nuevas / definición / objetivo cambiado |
| Tarjeta de insight nueva | opacidad 0→1, y 6→0 | 180 | salida, 35·n | evento `tarjetas` |
| Barra de novedad | se disipa | 400 | salida | a los 8 s |
| Notificación entra | opacidad 0→1, y −12→0, escala .97→1, blur 6→0 (solo Efectos alto) | 320 | salida | cola FIFO, 900 ms entre una y otra |
| Notificación vuela a Hallazgos | `translate` al rect del botón, escala .6, opacidad 0; altura colapsa | 320 + 240 | entrada | vida cumplida, «×» o «Ver» |
| Botón Hallazgos recibe | `scale 1→1.08→1` y el contador cambia en seco | 240 | muelle | llegada |
| Hallazgos abre / cierra | x 16→0 y opacidad; chips escalonados 20·n | 200 / 160 | salida / entrada | botón o Esc |
| Fila nueva en Hallazgos | opacidad 0→1 | 180 | salida | si `scrollTop` 0; si no, en seco |
| Registro, tooltip, cajón | opacidad, y 4→0, escala .98→1 | 120 | salida | apertura |
| Plegar / desplegar Orquestación y Sesión | altura interpolada (`grid-template-rows 1fr↔0fr`), contenido se funde | 260 | salida | botón; preferencia recordada |
| Cambio de pantalla | View Transition: cross-fade de `main`, cabecera fija (`view-transition-name: cabecera`) | 260 | salida | `mostrarVista` |
| Barras del Gantt | `scaleX` 0→1 y barrido de luz de izquierda a derecha una sola vez | 260 + 400 | salida, 35·n | primer pintado del inicio |
| Diff decidido | colapso de altura | 260 | entrada | «Aceptar» / «Rechazar» |
| Medidores, `●REC`, cronómetro, tokens | como hoy; cronómetro y contadores cambian en seco | | | |

Con `prefers-reduced-motion`: todo a 0 ms salvo medidores; el anillo no gira (queda el halo fijo); las notificaciones aparecen y desaparecen en seco con el mismo escalonado.

## 8. Estados de los componentes

| Componente | Reposo | Hover | Pulsado | Foco | Activo / seleccionado | Deshabilitado |
|---|---|---|---|---|---|---|
| Botón fantasma | transparente, `--body` | fondo `--vidrio`, canto `--canto`, `--ink`, −1 px | `.985` | doble anillo | `aria-pressed`: fondo `--acc-soft`, `--acc-t` | opacidad .5, sin hover |
| Botón primario | `--acc`, blanco 600, sombra `0 1px 2px rgba(46,124,246,.4)` | luminosidad +6 %, −1 px | `.985` | doble anillo | | opacidad .5 |
| Botón mini | igual que fantasma con canto `--hair2` | igual | igual | igual | | |
| Chip de minuto | `--acc-soft`, `--acc-t`, radio 4 | fondo `rgba(acc,.26)` + enciende la línea destino | `.96` | doble anillo | | |
| Chip de filtro (Hallazgos, Sesión, Ideas) | canto `--hair2`, `--body` | fondo `--vidrio`, −1 px | `.985` | doble anillo | fondo `--acc-soft`, `--acc-t`, sin canto | |
| Tarjeta de perfil (vidrio fino) | `--vidrio`, canto, brillo | canto a `rgba(acc,.45)`, −1 px, `--sombra` | `.985` | doble anillo | **su turno**: canto `--acc-t`; **trabajando**: anillo cónico + `--halo` + barra 2 px + cronómetro; **hecho**: marca verde trazada; **error**: canto `--err`; **sin presupuesto**: punto ámbar y texto | |
| Nodo de orquestación | igual que la tarjeta a radio 8 | igual | igual | igual | trabajando: anillo + haz de salida; omitido: canto discontinuo | |
| Tarjeta de insight | `--vidrio`, canto; barra 2 px de novedad 8 s | canto `rgba(acc,.45)`, −1 px | | | resaltada desde Sesión: `--sel` 1,6 s | |
| Fila de transcripción | sin caja | `--hover` | | anillo interior (`outline-offset: −2`) | destino: `--sel` + barra 2 px; tramo: `--sel` | |
| Fila de feed y de Hallazgos | sin caja, filete | `--hover` | | anillo interior | | |
| Fila de objetivo / check | sin caja | `--hover` en el texto | | | cubierto: verde con marca; sugerido: canto discontinuo `--acc` | |
| Notificación | `--vidrio-f`, blur, `--sombra-f`, radio 14 | la pila pausa su vida; `--sombra-f` +4 px de desplazamiento | | | | |
| Papel (notas, anotación) | `--papel`, `--papel-canto`, radio 10 | canto más visible | | doble anillo | | |

## 9. Pantallas

**Inicio.** Grafito con la capa ambiente. Izquierda: formulario en una lámina de vidrio flotante (`--vidrio-f` con blur, única del inicio) de 400 px; el título `t-display` ocupa el hueco del logo (sin logo). Lista de proyectos con filas de 32 px y `--hover`; grupos segmentados con el estado activo en `--acc-soft`. «Empezar reunión» primario de 40 px, solo activo con la casilla. Derecha: ficha, Gantt y listas sobre grafito; barras del Gantt con barrido de luz una vez al entrar; hitos como rombo de 8 px `--acc`.

**Reunión** (revisión 2026-11-06; el prototipo `prototipo.html` muestra la versión de tres columnas, anterior). Cabecera de UNA fila de 48: marca · ●REC y cronómetro (`t-cron`, 22) · tema (15 600) y proyecto · medidores · Hallazgos, Contexto, Modo reunión, Pausa, Analizar ahora, Terminar · Oculta al compartir, Sesiones y, por debajo de 1620 px, «Más» (Efectos, Modo, Ajustes). Banda Orquestación **plegada por defecto** a una línea de 36 px: «Equipo: hecho · Monitor escuchando · 3 turnos · 5,5k» más, solo si algo trabaja, falla o está en pausa, su texto; «Orquestación» la despliega (los nodos de §14.12) y la preferencia se recuerda en `localStorage` `apuntes_orq_plegado`. Cuerpo en DOS columnas (la derecha, `clamp(500px, 40vw, 640px)`): **izquierda** Transcripción (una fila por intervención: minuto y quién a la izquierda, texto a la derecha) y Notas en papel, plegadas por defecto (`apuntes_notas_abiertas`); **derecha** el carril «Ahora» fijo arriba y debajo pestañas (`#r-tabs`, `apuntes_pestana`): **Consejos** e **Insights** (lo importante) y detrás **Objetivos**, **Equipo**, **Pregúntale** y **Sesión** (la línea de tiempo). Sin elección del usuario se muestra Consejos si los hay y, si no, Insights. Ninguna zona obliga a desplazar la página: cada una hace scroll en sí misma. Pie 28. Notificaciones de vidrio flotante arriba a la derecha; Hallazgos como lámina lateral de 420.

**Modo reunión.** Paneles **opacos** de grafito (`#18191F` / `#FFFFFF`): la opacidad la pone la ventana (`WS_EX_LAYERED`), no el CSS, y el hueco central es real (`SetWindowRgn`), así que **no hay vidrio contra Teams y no se promete**. Dentro del panel derecho sí: notificaciones y Hallazgos con blur sobre el propio panel (Efectos medio por defecto). Barra del Modo reunión sin filtro. Divisores: línea de 2 px que se enciende en `--acc` al pasar o arrastrar. Perfiles compactos de 52 px con el mismo anillo de trabajo. Banda Orquestación plegada abajo a la izquierda. El panel derecho lleva el mismo carril «Ahora» y las mismas pestañas (en dos filas de tres) con la misma escala y la misma jerarquía de tipos.

**Revisión.** Grafito con ambiente. Resumen en columna de 56ch; cambios propuestos como láminas de vidrio fino, uno por fichero, con cabecera de 36 px y diff dentro; al decidir, colapsan a 28 px con «Deshacer». Comparación Sonnet / Opus: dos láminas de vidrio fino lado a lado con las diferencias en `--acc-soft`; «Usar esta» en cada cabecera. Publicar: lámina de papel con la ruta completa. Banda Orquestación desplegada arriba con Verificador → Redactor → Pulidor encendiéndose en serie (eventos reales del cierre).

## 10. Presencia de cada agente

- **Identidad**: monograma de 32×32 (28 en nodo) con radio 8 sobre vidrio fino; letras `t-mono` en `--acc-t`; el mismo monograma en tarjeta, nodo, notificación, Hallazgos y Registro. MO (Monitor) lleva canto discontinuo porque es local; AN (Analista genérico de 5/10 min) sin perfil.
- **En espera**: vidrio apagado, punto hueco, `siguiente: en 1:12 · motivo: …` en `t-meta`.
- **Su turno**: canto `--acc-t`, punto relleno fijo, 180 ms. Dura lo que tarde en arrancar la llamada (habitualmente < 1 s).
- **Trabajando**: anillo cónico girando, halo, barra 2 px, cronómetro real `Trabajando 0:07`; en la banda, el nodo «Equipo» muestra el monograma del perfil (CO, AF…) con el mismo anillo y el haz corre por los conectores que entran en él (Monitor → Equipo, Contexto → Equipo: es lo que está leyendo); la línea plegada dice `Coordinador trabajando 05:40–10:10 con haiku…`.
- **Hecho**: anillo se funde, marca verde trazada, línea 2 cambia en seco, un pulso único sale por los conectores de salida del nodo (Equipo → Verificador, Equipo → Consultas), pulso en la cabecera de la columna que recibe (Insights, Definiciones, Objetivos), tarjetas y notificaciones entran escalonadas.
- **Error / sin presupuesto**: canto rojo fijo o punto ámbar; texto literal del motivo; nada gira.
- **Flujo entre ellos**: la banda Orquestación es el mapa (Escucha → Transcriptor → Monitor → Equipo → Verificador → Redactor → Pulidor; Contexto → Equipo; Equipo → Consultas). La columna Equipo es la vista de cerca del nodo «Equipo»: clic en el nodo abre el Registro filtrado; mientras un perfil trabaja, el nodo «Equipo» muestra su monograma y el mismo anillo. Las llamadas van en serie, así que nunca hay dos anillos a la vez salvo el Transcriptor (local, en paralelo), que no lleva anillo sino el medidor.

## 11. Notificaciones y Hallazgos

Como en `DESIGN-equipo.md` §5 (cola, vida, pausa en hover, «Ver», «Pregúntale», derivación de datos reales, filtros, glifos) con este acabado:
- `.notif`: vidrio flotante radio 14, monograma 32 radio 8, nombre `t-mono`, categoría `t-label` con glifo, texto `t-body` en `--ink` con `text-wrap: pretty`, `t-meta` solo con datos reales, botones mini. Entrada con desenfoque que se resuelve (Efectos alto), vuelo a Hallazgos al salir.
- `#r-bandeja`: lámina de vidrio flotante a `right 0, top 48, bottom 28`, 420 px, canto izquierdo de 1 px; cabecera pegajosa de grafito con «Hallazgos N» y «Cerrar»; chips de filtro con glifo y contador, escalonados al abrir; filas sin caja con filete, glifo + etiqueta + chip de minuto + texto completo + meta + «Ver».
- Tipos (**icono SVG + color + etiqueta**, nunca solo color; revisión 2026-11-06): un solo juego de iconos en línea (`web/iconos.js`: caja de 24×24, trazo redondeado de 1,5 px de pantalla —`vector-effect: non-scaling-stroke`, nítido a 1× y a 1,25×—, `currentColor`; trazados de Lucide, licencia ISC, y de la misma rejilla), sin librería ni red. Decisión: bandera, `--t-decision` (verde). Pendiente: lista de tareas, `--t-pendiente` (ámbar). Riesgo: triángulo de alerta, `--t-riesgo` (rojo). Contradicción: dos flechas opuestas, `--t-contradiccion` (magenta; «posible» lleva el borde discontinuo y la palabra). Pregunta: círculo con interrogación, `--t-pregunta` (cian). Idea: bombilla, `--t-idea` (violeta). Regla: llaves, `--t-regla` (azul grisáceo). Definición: libro, `--t-definicion` (verde azulado). Objetivo sin tratar: diana, `--warn`. Consejo: brújula, `--t-consejo`. Respuesta de «Ahora»: bocadillo, `--t-respuesta`. Aviso, error, éxito e información: círculo con signo (`--warn`, `--err`, `--ok`, `--acc-t`). **Jerarquía:** decisión, pendiente, riesgo y contradicción son lo importante: barra de 3 px del color del tipo, etiqueta en negrita y texto en `--ink` 500; pregunta, idea, regla y definición son secundarias: sin caja ni sombra, texto en `--body`. **Avisos emergentes (revisión 2026-11-06, mandan sobre §6 y §11 anteriores):** un carril propio, EN EL FLUJO, al pie de la columna derecha (`#r-notifs`): nunca flotan sobre «Ahora», las pestañas, los consejos ni otro aviso (las pestañas se encogen para dejarles sitio). Fondo OPACO (`--elev-solido`, sin vidrio ni desenfoque), como máximo 2 a la vez y apilados; lo que no cabe espera en cola (caduca a los 30 s) y se agrupa en «+N hallazgos», que lleva a la pestaña Insights. Solo decisión, contradicción y riesgo avisan; pendiente, pregunta, idea, regla, definición y objetivo sin tratar solo suman al contador de su pestaña (con resaltado) y a Hallazgos. Hay test que mide las cajas (`tests/test_jerarquia.py`). Las notificaciones llevan una baldosa de 28 con el icono del tipo (el monograma del agente pasa a chip junto al nombre) y las importantes la misma barra. Los colores `--t-*` cumplen 4,5:1 sobre el vidrio y el papel en los dos temas (hay test).

## 12. Decisiones que necesitan el visto bueno del autor

1. **Papel como material del usuario** (superficie cálida en Notas, anotación rápida, «Tú», objetivos propios, campo de Pregúntale). Rompe la monocromía a propósito; si no convence, esas zonas quedan en grafito con canto y se pierde la lectura «humano / equipo».
2. **Acento `#007AFF` → `#2E7CF6` / `#7EB4FF`**: cambia el tono de botones, chips y barra de palabras en toda la app (también inicio y revisión).
3. **Radios** 4 / 8 / 10 / 14 en lugar de 3 / 6 / 8 y la excepción de `.notif` convertida en regla.
4. **Efectos por defecto**: `alto` en vista completa y `medio` en Modo reunión. Si prefiere ahorrar CPU siempre, `medio` en todo.
5. **View Transitions** para el cambio de pantalla: exige envolver `mostrarVista` en `document.startViewTransition` (un hook en `app.js`, con fallback). Es el único cambio de JS de la lista; el resto es CSS y `equipo.js` / `agentes.js` para las clases de estado.
6. **Cronómetro a 28 px peso 300**: más presencia en la cabecera; ocupa 12 px más de ancho.
7. **Monogramas** como única «iconografía» de agente (sin avatares ni colores por perfil).

## 13. Orden de implementación sugerido (cada paso deja la app usable)

1. Tokens y capa ambiente (`app.css`), interruptor Efectos (`app.js` o `agentes.js`, `localStorage`), `body[data-efectos]`.
2. Materiales: `.panel`, `.tarj`, `.eq-tarj`, `.nodo`, `.eq-monitor`, `.traza-f`, `.notas`, `.tuya`, `.pregunta-form .input` → vidrio fino y papel; `.registro`, `.drawer`, `.dialogo`, `.sb-tip`, `.notif`, `#r-bandeja` → vidrio flotante.
3. Luz de trabajo: `.eq-tarj[data-estado="trabajando"]` y `.nodo[data-estado="trabajando"]` (anillo cónico con `@property --ang`), haz del conector, pulso de cabecera. Mismos disparadores de hoy (`tarea inicio` / `fin`).
4. Hover, pulsación y foco en todo lo interactivo.
5. Notificaciones y Hallazgos (entrada, vuelo, apertura de la lámina).
6. Plegados interpolados, View Transitions, barrido del Gantt, cronómetro.
7. Medición del presupuesto (§6) y ajuste de `blur` / `saturate` si hace falta.

## 14. Criterios de aceptación, medibles en el navegador

1. `getComputedStyle` de cada elemento con `backdrop-filter` ≠ `none`: nunca más de 6 a la vez; ninguno dentro de `.trans`, `#eq-feed-lista`, `#r-insights`, `#r-bandeja-lista`, `.sb-plot`.
2. En reposo (sin `tarea` abierta), `document.getAnimations()` devuelve solo `●REC` y medidores; con una tarea, además exactamente un anillo y un haz, que desaparecen en el `tarea fin`.
3. Con `data-efectos="apagado"`: 0 elementos con `backdrop-filter`, la capa ambiente no existe en el DOM o está `display: none`, y todos los estados de perfil siguen distinguibles (texto de estado y color del canto).
4. Contraste: `--body` ≥ 7:1 y `--soft`, `--acc-t` y etiquetas ≥ 4,5:1 medidos sobre el color efectivo del vidrio flotante en su punto más iluminado por el ambiente, en los dos temas.
5. Ningún `text-overflow: ellipsis` ni `-webkit-line-clamp` computado, ni texto cortado (`scrollWidth > clientWidth` o `scrollHeight > clientHeight`), en tarjetas, notificaciones, Hallazgos, feed, definiciones, tema y proyecto de la cabecera (`.reunion-id`), lista de proyectos del inicio (`.item .n`, `.item .tag`), línea de orquestación (`.orq-estado`, `.orq-ult`, que crece en altura), `.traza-b`, `.ctx-proy` y `.cambio-h .m`: el texto envuelve. **Excepciones admitidas (recorte con tooltip):** barras geométricas estrechas (`.g-bt` del Gantt y `.sb-tema-t` de la banda Sesión), `.pie-ctx` y el dato del nodo de Orquestación (`.nodo-l2`, que muestra lo esencial y deja el texto completo en el tooltip y el `aria-label`).
6. Con Insights a `scrollTop` 600, insertar 5 tarjetas no cambia la línea visible y aparece `5 nuevos ↑`.
7. Foco visible con Tab en todo botón, chip, fila-botón y campo, también sobre vidrio flotante y papel.
8. Los ids del DOM de las pruebas (`r-notifs`, `r-bandeja`, `r-bandeja-btn`, `eq-perfiles`, `r-insights`, `v-rev-*`, `mr-*`…) no cambian.
9. Modo reunión: los paneles computan fondo opaco (`alpha` 1); el único vidrio está dentro del panel derecho.
10. Con `prefers-reduced-motion`, `getAnimations()` devuelve solo medidores y ningún elemento tiene `filter: blur` de entrada.
11. Las clases de entrada (`nueva`, `entra`, `traza`) se retiran en `animationend`: una animación con `fill-mode: both` ya terminada sigue contando en `getAnimations()` y en la memoria del compositor si no se quita (en el prototipo no se retiran; en la app sí).
12. Nodos de la banda (con la banda desplegada; plegada por defecto desde 2026-11-06): 7 columnas × 2 filas de 48 px, monograma de 24, nombre 12/15 600 y dato 11/13 que envuelve; ningún nodo con `scrollWidth > clientWidth` a 1440 px. Ninguna tarjeta de perfil es un `<button>` con chips dentro: es `div[role=button][tabindex=0]` (un `button` anidado en otro rompe el árbol HTML).
