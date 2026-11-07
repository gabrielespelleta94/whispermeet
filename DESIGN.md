# Apuntes: diseño

> Manda `DESIGN-agentico.md` (rediseño agéntico y panel de orquestación) donde se contradigan; aquí quedan marca, curvas y transiciones.

Estructura y movimiento de una app corporativa de planificación de inversiones (referencia previa del autor). Color, tipografía y logo de Stratesys (Brandbook 2026, resumido en `Proyectos\Stratesys\formato-documento-stratesys\tokens\tokens.css`).

## Marca

- **Tipografía:** solo DM Sans, 300-700. Fuentes en `formato-documento-stratesys\marca\fuentes-web.css`, extraídas a `web\fuentes` (`web\fuentes.css`) para funcionar sin internet; logo copiado a `web\marca`. Cifras con `tabular-nums`. Sin monoespaciada ni serifas.
- **Logo:** el propio de la app (`web/marca/apuntes.svg`), sin deformar ni recolorear.
- **Negros y grises:** negro `#1B1B20`, cuerpo `#3A3A42`, gris `#686868`, gris2 `#909098`, filete `#E0E0E6`, filete fuerte `#C7C7CC`, suave `#F2F2F4`, gris claro `#F0F0F2`, texto sobre negro `#B9B9C3`.
- **Acento único:** azul `#007AFF`. Rampa: `#66ACFF #8CBFFF #B0D2FF #D4E6FF #EAF3FF`. Sobre negro, el texto de acento usa `#66ACFF`.
- **Con significado, nunca decoración:** verde `#1E8A4C` = cubierto o hecho; rojo `#B3261E` = contradicción o error; ámbar `#B25E09` = a contrastar o parcial. Sobre negro, usar una variante clara que cumpla contraste AA.
- **Firma:** barra azul de 56x3 px.
- **Fuera:** verdes Nordia, violeta, turquesa, grafito o azul noche, gradientes, halos, brillos, aurora, cuadrícula de fondo.

## Temas

- **Claro:** base blanca, paneles con filete.
- **Oscuro:** base `#1B1B20`, nunca grafito. Paneles con superficie algo más clara y filete sutil.

## Estructura (de la app de referencia)

- Cabecera de 56 px con cristal (blur 16 px), logo Stratesys, título y estado.
- Página con padding 24/20 px y separación de 16 px. Html a 14 px; etiquetas de al menos 11 px en esta app, porque se lee de reojo durante una reunión.
- Paneles: radio 14, borde de 1 px, sin gradiente ni filo de luz.
- Tarjetas de insight: radio 12, borde suave; hover con `translateY(-1px)` y sombra `0 14px 30px -18px`.
- Botones: radio 8, alto 2rem, padding 0 .95rem, .85rem peso 500, primario en azul plano, `:active` con `translateY(1px)`.
- Campos: radio 4. Menús: radio 10. Foco visible: 2 px de acento.

Pantalla de reunión, a petición del autor: transcripción y notas en 1/3 del ancho, y 2/3 para objetivos, checks e insights en dos columnas, sin cajas de scroll anidadas.

La guía de marca evita tarjetas y píldoras en documentos. Aquí se admiten solo donde son interactivas (insights, checks, estados), porque esto es una app, no un documento.

## Movimiento (valores de la app de referencia)

- Tokens: micro 120 ms, corta 180 ms, media 260 ms, trazo 400 ms, paso 35 ms. Curvas: salida `cubic-bezier(.16,1,.3,1)`, entrada `cubic-bezier(.4,0,1,1)`, vaivén `cubic-bezier(.4,0,.2,1)`.
- Entre pantallas: entra con x 16 px y opacidad en 260 ms, sale con x -12 px en 120 ms, según la dirección. Filo azul de 2 px con `scaleX` 0 a 1 en 390 ms.
- Cabecera: y -56 a 0 en 320 ms con la curva de salida.
- Escalonado: hijos con y 8 a 0 y opacidad en 260 ms, paso de 35 ms.
- Insight nuevo: entra escalonado desde abajo. Check u objetivo que cambia: trazo del tick de 400 ms y destello de valor de 400 ms.
- Gantt: barras con `scaleX` de 0 a 1 al seleccionar, línea de hoy trazada, sesión resaltada con transición de 260 ms.
- Avisos: entran con x 32 y scale .96, salen con x 24 en 180 ms, y se paran al pasar el ratón.
- Contadores: 400 ms.

## Reglas de una app abierta en una reunión

- Nada en bucle salvo el indicador de grabación y los medidores de nivel.
- La transcripción en directo no anima cada línea: solo un fundido corto, sin saltos de scroll.
- `prefers-reduced-motion`: todo pasa a inmediato.
- Sin librerías ni paso de build: CSS y Web Animations API.
